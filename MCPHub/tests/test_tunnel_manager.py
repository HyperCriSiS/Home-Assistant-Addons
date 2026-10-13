"""Tests for isolated tunnel lifecycle, backoff, health and local controls."""
import importlib.util
import json
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import Mock, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / 'tunnel_manager.py'
spec = importlib.util.spec_from_file_location('tunnel_manager', MODULE_PATH)
manager_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager_module)


class TunnelManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        self.options_file = home / 'options.json'
        self.key = home / 'secret' / 'key'
        self.auth = home / 'auth'
        self.auth.write_text('Bearer test-auth')
        self.values = {'openai': {
            'tunnel_enabled': True,
            'openai_runtime_api_key': 'test-private-key',
            'tunnel_id': 'tunnel_' + 'a' * 32,
            'tunnel_mcp_path': '/mcp',
        }, 'logging': {'tunnel_log_level': 'info'}}
        self.options_file.write_text(json.dumps(self.values))
        for name, value in [('OPTIONS_FILE', self.options_file), ('KEY_FILE', self.key), ('AUTH_FILE', self.auth)]:
            patcher = patch.object(manager_module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.process = Mock()
        self.process.pid = 71
        self.process.poll.return_value = None
        self.process.wait.return_value = 0
        patcher = patch.object(manager_module.subprocess, 'Popen', return_value=self.process)
        self.popen = patcher.start()
        self.addCleanup(patcher.stop)
        self.check = patch.object(manager_module, 'probe', return_value=True)
        self.probe = self.check.start()
        self.addCleanup(self.check.stop)
        self.manager = manager_module.TunnelManager(enabled=True)

    def test_start_and_ready_then_stop_without_stopping_mcphub(self):
        self.manager.tick(100)
        self.assertEqual(self.manager.snapshot()['state'], 'starting')
        self.assertEqual(self.key.read_text(), 'test-private-key')
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
        env = self.popen.call_args.kwargs['env']
        self.assertEqual(env['MCP_SERVER_URL'], 'http://127.0.0.1:3000/mcp')
        self.assertEqual(env['HEALTH_LISTEN_ADDR'], '127.0.0.1:8080')
        self.manager.tick(105)
        self.assertEqual(self.manager.snapshot()['state'], 'ready')
        self.assertNotIn('test-private-key', json.dumps(self.manager.snapshot()))
        self.manager.command('stop')
        self.process.terminate.assert_called_once()
        self.manager.tick(120)
        self.assertEqual(self.popen.call_count, 1)
        self.assertEqual(self.manager.snapshot()['state'], 'stopped')

    def test_crash_retries_exponential_backoff(self):
        self.manager.tick(100)
        self.process.poll.return_value = 12
        self.manager.tick(110)
        self.assertEqual(self.manager.failure_count, 1)
        self.assertEqual(self.manager.next_attempt, 115)
        self.manager.tick(114)
        self.assertEqual(self.popen.call_count, 1)
        self.process.poll.return_value = None
        self.manager.tick(115)
        self.assertEqual(self.popen.call_count, 2)
        self.process.poll.return_value = 2
        self.manager.tick(118)
        self.assertEqual(self.manager.next_attempt, 128)

    def test_temporarily_unready_is_not_restarted(self):
        self.manager.tick(100)
        with patch.object(manager_module, 'probe', side_effect=lambda path: path == '/healthz'):
            self.manager.tick(110)
            self.manager.tick(250)
        self.assertEqual(self.manager.snapshot()['state'], 'degraded')
        self.process.terminate.assert_not_called()

    def test_too_long_unready_is_restarted_after_grace(self):
        self.manager.tick(100)
        with patch.object(manager_module, 'probe', side_effect=lambda path: path == '/healthz'):
            self.manager.tick(110)
            self.manager.tick(711)
        self.assertEqual(self.manager.snapshot()['state'], 'retrying')
        self.process.terminate.assert_called_once()

    def test_health_endpoint_missing_long_enough_retries(self):
        self.manager.tick(100)
        with patch.object(manager_module, 'probe', return_value=False):
            self.manager.tick(110)
            self.manager.tick(171)
        self.assertEqual(self.manager.state, 'retrying')

    def test_invalid_credentials_fail_safe_without_exposing_secret(self):
        self.values['openai']['tunnel_id'] = 'bad'
        self.options_file.write_text(json.dumps(self.values))
        self.manager.tick(100)
        self.popen.assert_not_called()
        self.assertEqual(self.manager.state, 'error')
        self.assertFalse(self.manager.requested)
        self.assertNotIn('test-private-key', self.manager.last_error)

    def test_reload_picks_up_new_configuration(self):
        self.manager.tick(100)
        self.values['openai']['tunnel_mcp_path'] = '/mcp/development'
        self.options_file.write_text(json.dumps(self.values))
        self.manager.command('reload')
        self.assertEqual(self.popen.call_count, 2)
        self.assertEqual(self.popen.call_args.kwargs['env']['MCP_SERVER_URL'], 'http://127.0.0.1:3000/mcp/development')

    def test_flat_options_are_still_accepted(self):
        self.options_file.write_text(json.dumps(self.values['openai'] | {'tunnel_log_level': 'warn'}))
        self.manager.tick(100)
        self.assertEqual(self.popen.call_args.kwargs['env']['LOG_LEVEL'], 'warn')


class TunnelControlTests(unittest.TestCase):
    def test_control_requires_custom_header(self):
        manager = Mock()
        manager.snapshot.return_value = {'state': 'stopped'}
        manager.command.return_value = {'state': 'starting'}
        handler = manager_module.handler_for(manager)
        from http.server import ThreadingHTTPServer
        import threading
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = HTTPConnection(*server.server_address, timeout=5)
            conn.request('POST', '/api/start', '{}', {'Content-Type': 'application/json'})
            self.assertEqual(conn.getresponse().status, 403)
            conn.close()
            manager.command.assert_not_called()
            conn = HTTPConnection(*server.server_address, timeout=5)
            conn.request('POST', '/api/start', '{}', {'Content-Type': 'application/json', 'X-MCPHub-Tunnel-Control': '1'})
            self.assertEqual(conn.getresponse().status, 200)
            manager.command.assert_called_once_with('start')
            conn.close()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
