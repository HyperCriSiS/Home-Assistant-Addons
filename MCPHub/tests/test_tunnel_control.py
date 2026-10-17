"""Regression tests for independent OpenAI and Cloudflare controls."""
import importlib.util
import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, file_name):
    spec = importlib.util.spec_from_file_location(name, ROOT / file_name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TunnelControllerTests(unittest.TestCase):
    def setUp(self):
        self.mod = load("mcphub_tunnel_dashboard_test", "tunnel_control.py")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name)
        self.mod.OPTIONS = directory / "options.json"
        self.mod.CF_SECRET = directory / "secret" / "token"
        self.mod.CF_CLIENT_KEY = directory / "secret" / "client_key"
        self.mod.CF_CLIENT_KEY.parent.mkdir()
        self.mod.CF_CLIENT_KEY.write_text("c" * 48, encoding="utf-8")
        self.set_options()

    def set_options(self, **options):
        self.mod.OPTIONS.write_text(json.dumps(options), encoding="utf-8")

    def test_cloudflare_start_protects_secret_and_checks_both_health_probes(self):
        self.set_options(cloudflare={
            "cloudflare_tunnel_enabled": True,
            "cloudflare_tunnel_token": "sensitive-token",
            "cloudflare_mcp_path": "/mcp/development",
        })
        cloudflare = self.mod.Cloudflare()
        with patch.object(self.mod.subprocess, "Popen") as spawn, \
             patch.object(self.mod, "check", return_value=False) as check:
            proc = MagicMock()
            proc.poll.return_value = None
            spawn.return_value = proc
            cloudflare.command("start")
            self.assertEqual(self.mod.CF_SECRET.read_text(), "sensitive-token")
            self.assertEqual(self.mod.CF_SECRET.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("sensitive-token", str(spawn.call_args))
            cloudflare.tick(cloudflare.started + 45)
            self.assertEqual(cloudflare.state, "degraded")
            self.assertFalse(cloudflare.status(cloudflare.started + 45)["transport_ready"])
            self.assertEqual(check.call_count, 2)
            cloudflare.command("stop")
            self.assertEqual(cloudflare.state, "stopped")

    def test_stale_cloudflare_ready_never_appears_healthy(self):
        cloudflare = self.mod.Cloudflare()
        process = MagicMock()
        process.poll.return_value = None
        cloudflare.proc = process
        cloudflare.state = "ready"
        cloudflare.desired = True
        cloudflare.checked = 3.0
        result = cloudflare.status(30.0)
        self.assertEqual(result["state"], "stale")
        self.assertFalse(result["transport_ready"])

    def test_unconfigured_cloudflare_fails_closed_without_leaking_credentials(self):
        cloudflare = self.mod.Cloudflare()
        with patch.object(self.mod.subprocess, "Popen") as spawn:
            cloudflare.command("start")
            spawn.assert_not_called()
        self.assertEqual(cloudflare.state, "error")
        self.assertFalse(cloudflare.desired)
        self.assertNotIn("token", json.dumps(cloudflare.status(2.0)).lower())

    def test_two_tunnels_only_and_stale_openai_is_unhealthy(self):
        controller = self.mod.Controls()
        controller.cloudflare.status = Mock(return_value={"state": "stopped"})
        controller.openai = Mock(return_value={
            "state": "ready", "health_age_seconds": 35, "last_error": ""
        })
        snapshot = controller.snapshot()
        self.assertEqual(set(snapshot), {"openai", "cloudflare"})
        self.assertEqual(snapshot["openai"]["state"], "stale")
        self.assertFalse(snapshot["openai"]["transport_ready"])
        with self.assertRaises(ValueError):
            controller.command("funnel", "start")
        with self.assertRaises(ValueError):
            controller.command("serve", "stop")

    def test_page_contains_lan_navigation_without_tailscale(self):
        self.assertIn('href="#lan"', self.mod.PAGE)
        self.assertIn("Deaktivierte Ports einblenden", self.mod.PAGE)
        self.assertIn("3001/tcp", self.mod.PAGE)
        self.assertIn("3001", self.mod.PAGE)
        self.assertNotIn("Tailscale", self.mod.PAGE + self.mod.SCRIPT)

    def test_key_rotation_reloads_proxy_and_rejects_previous_token(self):
        controller = self.mod.Controls()
        original = self.mod.CF_CLIENT_KEY.read_text()
        with patch.object(self.mod.subprocess, "run") as run:
            response = controller.rotate_client_key()
        changed = self.mod.CF_CLIENT_KEY.read_text()
        self.assertEqual(response, {"rotated": True})
        self.assertNotEqual(changed, original)
        self.assertEqual(len(changed), 64)
        self.assertEqual(self.mod.CF_CLIENT_KEY.stat().st_mode & 0o777, 0o600)
        self.assertEqual(controller.client_key()["key"], changed)
        self.assertEqual(run.call_count, 3)
        self.assertIn("nginx", str(run.call_args_list))
        self.assertNotIn(changed, str(run.call_args_list))

    def test_key_rotation_failure_restores_original_key(self):
        controller = self.mod.Controls()
        original = self.mod.CF_CLIENT_KEY.read_text()
        from subprocess import CalledProcessError
        with patch.object(self.mod.subprocess, "run", side_effect=[
            None, CalledProcessError(1, "nginx -t"), None, None
        ]), self.assertRaises(RuntimeError):
            controller.rotate_client_key()
        self.assertEqual(self.mod.CF_CLIENT_KEY.read_text(), original)

    def test_http_controls_deny_missing_headers_and_unknown_tunnels(self):
        manager = Mock()
        manager.snapshot.return_value = {"openai": {"state": "ready"}}
        manager.command.return_value = {"state": "stopped"}
        manager.client_key.return_value = {"key": "test_sensitive_key"}
        manager.rotate_client_key.return_value = {"rotated": True}
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.mod.handler_for(manager))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(method, route, body=None, headers=None):
            conn = HTTPConnection(*server.server_address, timeout=5)
            try:
                conn.request(method, route, body=body, headers=headers or {})
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()

        try:
            status, body = request("GET", "/api/status")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["openai"]["state"], "ready")
            status, _ = request("POST", "/api/control/cloudflare/stop", "{}",
                                {"Content-Type": "application/json"})
            self.assertEqual(status, 403)
            status, _ = request("POST", "/api/control/funnel/start", "{}",
                                {"Content-Type": "application/json", "X-MCPHub-Tunnel-Control": "1"})
            self.assertEqual(status, 403)
            manager.command.assert_not_called()
            status, body = request("POST", "/api/control/cloudflare/stop", "{}",
                                   {"Content-Type": "application/json", "X-MCPHub-Tunnel-Control": "1"})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["state"], "stopped")
            manager.command.assert_called_once_with("cloudflare", "stop")
            status, _ = request("GET", "/api/client-key")
            self.assertEqual(status, 403)
            status, body = request("GET", "/api/client-key", headers={
                "X-MCPHub-Tunnel-Control": "1"})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)["key"], "test_sensitive_key")
            status, _ = request("POST", "/api/client-key/rotate", "{}",
                                {"Content-Type": "application/json"})
            self.assertEqual(status, 403)
            status, body = request("POST", "/api/client-key/rotate", "{}",
                                {"Content-Type": "application/json", "X-MCPHub-Tunnel-Control": "1"})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(body)["rotated"])
            manager.rotate_client_key.assert_called_once()
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
