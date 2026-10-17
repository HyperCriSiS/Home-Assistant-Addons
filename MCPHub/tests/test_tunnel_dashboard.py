"""Dashboard entry, log sanitization and tunnel-scoped admin API regression tests."""
import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(module_name, file):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NavigationTests(unittest.TestCase):
    def test_mcphub_shell_is_not_modified_for_tunnel_controls(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("inject_tunnel_nav.py", dockerfile)
        self.assertNotIn("ha_tunnel_nav.js", dockerfile)
        self.assertFalse((ROOT / "inject_tunnel_nav.py").exists())
        self.assertFalse((ROOT / "ha_tunnel_nav.js").exists())
        self.assertIn("COPY tunnel_dashboard.html", dockerfile)
        self.assertIn("COPY tunnel_dashboard.js", dockerfile)


class LiveLogsTests(unittest.TestCase):
    def test_redact_secret_values_and_header_credentials(self):
        module = load("mcphub_log_redaction", "tunnel_diagnostics.py")
        text = "Bearer abc123.token access_token=xyz? username=harmless TOPSECRETXYZ"
        clean = module.redact(text, ["TOPSECRETXYZ"])
        self.assertNotIn("abc123.token", clean)
        self.assertNotIn("xyz", clean)
        self.assertNotIn("TOPSECRETXYZ", clean)
        self.assertIn("harmless", clean)

    def test_bounded_log_buffer_and_subprocess_capture(self):
        module = load("mcphub_log_capture", "tunnel_diagnostics.py")
        logs = module.TunnelLog()
        for i in range(250):
            logs.add("entry-" + str(i))
        self.assertEqual(len(logs.snapshot()["lines"]), module.MAX_LINES)
        self.assertNotIn("entry-0", logs.snapshot()["lines"][0])
        proc = Mock()
        proc.stdout = StringIO("live log one\napi_key=sensitive-secret\n")
        logs.follow(proc)
        for _ in range(100):
            if any("live log one" in x for x in logs.snapshot()["lines"]):
                break
            time.sleep(0.01)
        transcript = "\n".join(logs.snapshot()["lines"])
        self.assertIn("live log one", transcript)
        self.assertNotIn("sensitive-secret", transcript)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.dashboard = load("mcphub_dashboard_ui", "tunnel_control.py")

    def test_separate_cards_and_optional_diagnostics(self):
        page = self.dashboard.PAGE
        script = self.dashboard.SCRIPT
        openai = page.index('id="t-openai"')
        cloud = page.index('id="t-cloudflare"')
        self.assertLess(openai, cloud)
        self.assertGreater(page.index("OpenAI Secure Tunnel"), openai)
        self.assertGreater(page.index('id="copy-key"'), cloud)
        self.assertEqual(page.count('data-panel="diagnostics"'), 3)
        self.assertEqual(page.count('data-panel="logs"'), 2)
        self.assertEqual(page.count('data-action="start"'), 3)
        self.assertIn("Protokoll anzeigen", page)
        self.assertIn('href="../"', page)
        self.assertIn("if (!section.open) return;", script)
        self.assertNotIn("JSON.stringify", script)
        self.assertNotIn("Cloudflare Access", page)

    def test_local_logs_endpoint_is_separate_and_unrecognized_modes_forbidden(self):
        manager = Mock()
        manager.logs.side_effect = lambda mode: {
            "lines": ["openai-one"] if mode == "openai" else ["cloudflare-two"]
        }
        manager.diagnostics.side_effect = lambda mode: {"mode": mode}
        server = ThreadingHTTPServer(("127.0.0.1", 0),
                                     self.dashboard.handler_for(manager))
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        def get(path):
            connection = HTTPConnection(*server.server_address, timeout=3)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()
        try:
            status, value = get("/api/logs/openai")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(value)["lines"], ["openai-one"])
            status, value = get("/api/logs/cloudflare")
            self.assertEqual(json.loads(value)["lines"], ["cloudflare-two"])
            status, value = get("/api/diagnostics/openai")
            self.assertEqual(json.loads(value)["mode"], "openai")
            status, value = get("/api/diagnostics/cloudflare")
            self.assertEqual(json.loads(value)["mode"], "cloudflare")
            self.assertEqual(get("/api/logs/serve")[0], 404)
            self.assertEqual(get("/api/diagnostics/funnel")[0], 404)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
