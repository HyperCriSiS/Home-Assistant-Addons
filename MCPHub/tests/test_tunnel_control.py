"""Regression tests for independent OpenAI, Cloudflare and Tailscale access."""
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


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
        self.mod.TS_CLIENT_KEY = directory / "secret" / "tailscale_key"
        self.mod.CF_CLIENT_KEY.parent.mkdir()
        self.mod.CF_CLIENT_KEY.write_text("c" * 48, encoding="utf-8")
        self.mod.TS_CLIENT_KEY.write_text("t" * 48, encoding="utf-8")
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

    def test_three_cards_and_stale_openai_is_unhealthy(self):
        controller = self.mod.Controls()
        controller.cloudflare.status = Mock(return_value={"state": "stopped"})
        controller.openai = Mock(return_value={
            "state": "ready", "health_age_seconds": 35, "last_error": ""
        })
        snapshot = controller.snapshot()
        self.assertEqual(set(snapshot), {"openai", "cloudflare", "tailscale"})
        self.assertEqual(snapshot["openai"]["state"], "stale")
        self.assertFalse(snapshot["openai"]["transport_ready"])
        with self.assertRaises(ValueError):
            controller.command("funnel", "start")
        with self.assertRaises(ValueError):
            controller.command("serve", "stop")

    def test_dashboard_contains_one_tailscale_card(self):
        self.assertIn('id="t-openai"', self.mod.PAGE)
        self.assertIn('id="t-cloudflare"', self.mod.PAGE)
        self.assertIn("Konfiguration", self.mod.PAGE)
        self.assertEqual(self.mod.PAGE.count('id="t-tailscale"'), 1)
        self.assertIn("Tailscale Funnel", self.mod.PAGE)
        self.assertNotIn("Tailscale Serve</h2>", self.mod.PAGE)
        self.assertNotIn("Cloudflare Access", self.mod.PAGE)
        self.assertNotIn("Zero Trust erforderlich", self.mod.PAGE)

    def test_dashboard_is_independent_and_diagnostics_are_optional(self):
        page, script = self.mod.PAGE, self.mod.SCRIPT
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('href="../"', page)
        self.assertIn("Tunnelverwaltung", page)
        self.assertIn("Diagnose anzeigen", page)
        self.assertIn("Protokoll anzeigen", page)
        self.assertIn('data-panel="diagnostics"', page)
        self.assertIn('data-panel="logs"', page)
        self.assertIn("setInterval(refresh, 10000)", script)
        self.assertIn("if (!section.open) return;", script)
        self.assertNotIn("JSON.stringify", script)
        self.assertNotIn("inject_tunnel_nav.py", dockerfile)
        self.assertNotIn("ha_tunnel_nav.js", dockerfile)
        self.assertIn("COPY tunnel_dashboard.html", dockerfile)
        self.assertIn("COPY tunnel_dashboard.js", dockerfile)

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

    def test_tailscale_key_rotation_is_separate_and_rollback_safe(self):
        controller = self.mod.Controls()
        old_cf = self.mod.CF_CLIENT_KEY.read_text()
        old_ts = self.mod.TS_CLIENT_KEY.read_text()
        with patch.object(self.mod.subprocess, "run") as run:
            self.assertEqual(controller.rotate_tailscale_client_key(), {"rotated": True})
        new_ts = self.mod.TS_CLIENT_KEY.read_text()
        self.assertNotEqual(old_ts, new_ts)
        self.assertEqual(len(new_ts), 64)
        self.assertEqual(self.mod.TS_CLIENT_KEY.stat().st_mode & 0o777, 0o600)
        self.assertEqual(controller.tailscale_client_key()["key"], new_ts)
        self.assertEqual(self.mod.CF_CLIENT_KEY.read_text(), old_cf)
        self.assertEqual(run.call_count, 3)
        from subprocess import CalledProcessError
        with patch.object(self.mod.subprocess, "run", side_effect=[
            None, CalledProcessError(1, "nginx -t"), None, None
        ]), self.assertRaises(RuntimeError):
            controller.rotate_tailscale_client_key()
        self.assertEqual(self.mod.TS_CLIENT_KEY.read_text(), new_ts)

    def test_tailscale_control_http_safety(self):
        manager = Mock()
        manager.tailscale.authorized.return_value = False
        manager.tailscale_client_key.return_value = {"key": "never_leak_without_header"}
        manager.rotate_tailscale_client_key.return_value = {"rotated": True}
        manager.command.return_value = {"state": "stopped"}
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

        allowed = {"X-MCPHub-Tunnel-Control": "1"}
        post_headers = {**allowed, "Content-Type": "application/json"}
        try:
            self.assertEqual(request("GET", "/api/tailscale/client-key")[0], 403)
            manager.tailscale_client_key.assert_not_called()
            status, body = request("GET", "/api/tailscale/client-key", headers=allowed)
            self.assertEqual(status, 200)
            self.assertIn(b"never_leak_without_header", body)
            self.assertEqual(request("GET", "/api/tailscale/https-check")[0], 403)
            self.assertEqual(request("GET", "/api/tailscale/gate")[0], 403)
            manager.tailscale.authorized.return_value = True
            self.assertEqual(request("GET", "/api/tailscale/gate")[0], 204)
            self.assertEqual(request("POST", "/api/tailscale/client-key/rotate",
                                     "{}", {"Content-Type": "application/json"})[0], 403)
            self.assertEqual(request("POST", "/api/tailscale/client-key/rotate",
                                     "{}", post_headers)[0], 200)
            manager.rotate_tailscale_client_key.assert_called_once()
            self.assertEqual(request("POST", "/api/control/tailscale/stop",
                                     "{}", post_headers)[0], 200)
            manager.command.assert_called_once_with("tailscale", "stop")
            self.assertEqual(request("POST", "/api/control/tailscale/reload",
                                     "{}", post_headers)[0], 200)
            # Route parsing allows legacy action spelling, but an actual
            # TailscaleGateway rejects reload; controller uses that class.
        finally:
            server.shutdown()
            server.server_close()

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
