"""Tests for the unified, Ingress-only multi-tunnel controller."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class TunnelControllerTests(unittest.TestCase):
    def setUp(self):
        self.mod = load('test_mcphub_tunnel_control', 'tunnel_control.py')
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.mod.OPTIONS = root / 'options.json'
        self.mod.CF_SECRET = root / 'cf_secret'
        self.mod.GATE_FILE = root / 'ts_state'
        self.set_options()

    def set_options(self, **cfg):
        self.mod.OPTIONS.write_text(json.dumps(cfg), encoding='utf-8')

    def test_tailscale_defaults_deny_without_config(self):
        manager = self.mod.Tailscale()
        for mode in ('serve', 'funnel'):
            self.assertFalse(manager.allowed(mode))
            status = manager.status(mode)
            self.assertFalse(status['configured'])
            self.assertIsNone(status['transport_ready'])
            self.assertEqual(status['control_type'], 'access_gate')

    def test_tailscale_gates_are_independent_and_persist(self):
        self.set_options(tailscale={
            'tailscale_serve_enabled': True,
            'tailscale_serve_mcp_path': '/mcp/development',
            'tailscale_serve_access_token': 'a' * 48,
            'tailscale_funnel_enabled': True,
            'tailscale_funnel_mcp_path': '/mcp/home',
            'tailscale_funnel_access_token': 'b' * 48,
        })
        control = self.mod.Tailscale()
        self.assertTrue(control.allowed('serve'))
        self.assertTrue(control.allowed('funnel'))
        control.command('serve', 'stop')
        self.assertFalse(control.allowed('serve'))
        self.assertTrue(control.allowed('funnel'))
        self.assertFalse(self.mod.Tailscale().allowed('serve'))
        self.assertEqual(self.mod.GATE_FILE.stat().st_mode & 0o777, 0o600)
        control.command('serve', 'start')
        self.assertTrue(self.mod.Tailscale().allowed('serve'))

    def test_reject_incomplete_external_tailscale_origin(self):
        control = self.mod.Tailscale()
        with self.assertRaises(ValueError):
            control.command('funnel', 'start')
        self.assertFalse(control.allowed('funnel'))

    def test_cloudflare_process_metrics_and_origin_are_both_required(self):
        self.set_options(cloudflare={
            'cloudflare_tunnel_enabled': True,
            'cloudflare_tunnel_token': 'sensitive-token',
            'cloudflare_access_token': 'c' * 48,
            'cloudflare_mcp_path': '/mcp/development',
        })
        ctrl = self.mod.Cloudflare()
        with patch.object(self.mod.subprocess, 'Popen') as spawn, patch.object(self.mod, 'check', return_value=False):
            proc = MagicMock()
            proc.poll.return_value = None
            spawn.return_value = proc
            ctrl.command('start')
            self.assertNotIn('sensitive-token', str(spawn.call_args.args[0]))
            self.assertIn('--token-file', spawn.call_args.args[0])
            self.assertEqual(self.mod.CF_SECRET.read_text(), 'sensitive-token')
            self.assertEqual(self.mod.CF_SECRET.stat().st_mode & 0o777, 0o600)
            ctrl.tick(ctrl.started + 45)
            self.assertEqual(ctrl.state, 'degraded')
            self.assertFalse(ctrl.status(ctrl.started + 45)['transport_ready'])
            self.assertNotIn('sensitive-token', json.dumps(ctrl.status(ctrl.started + 45)))
            ctrl.command('stop')

    def test_nginx_enforces_route_and_dynamic_access_gate(self):
        proxy = load('test_mcphub_proxy_gate', 'prepare_proxy_config.py')
        for port, mode in ((8094, 'serve'), (8095, 'funnel')):
            result = proxy.tailscale_origin_server_block(
                port=port, enabled=True, mcp_path='/mcp/development',
                client_token='s' * 48, internal_token='internal')
            self.assertIn('auth_request /__mcphub_tailscale_gate;', result)
            self.assertIn('internal;', result)
            self.assertIn('api/gate/' + mode, result)
            self.assertIn('return 401;', result)
            self.assertIn('return 404;', result)
            self.assertNotIn('X-MCPHub-HA-Proxy-Secret "trusted"', result)
            self.assertIn('proxy_set_header X-MCPHub-HA-Proxy-Secret "";', result)

if __name__ == '__main__':
    unittest.main()
