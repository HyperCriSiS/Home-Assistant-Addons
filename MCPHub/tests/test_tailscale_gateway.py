"""Fail-closed regression tests for the separate Home Assistant Tailscale Funnel origin."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TailscaleGatewayTests(unittest.TestCase):
    def setUp(self):
        self.ts = load("tailscale_gateway_test", "tailscale_gateway.py")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "secrets" / "state"
        self.options = {"tailscale_funnel_enabled": True, "tailscale_mcp_path": "/mcp/home"}
        self.gateway = self.ts.TailscaleGateway(lambda: self.options, self.state)

    def test_gateway_start_stop_persists_and_never_starts_tailscale(self):
        with patch.object(self.ts, "is_origin_response", return_value=True) as probe:
            s = self.gateway.status()
            self.assertEqual(s["state"], "gateway_ready")
            self.assertTrue(s["gateway_ready"])
            self.assertFalse(s["transport_ready"])
            self.assertEqual(s["funnel_control"], "manual")
            probe.assert_called_with("/mcp/home")
        self.assertTrue(self.gateway.authorized())
        self.gateway.command("stop")
        self.assertFalse(self.gateway.authorized())
        self.assertEqual(self.state.read_text(), "stopped")
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)
        after_restart = self.ts.TailscaleGateway(lambda: self.options, self.state)
        self.assertFalse(after_restart.authorized())
        after_restart.command("start")
        self.assertTrue(after_restart.authorized())
        self.assertEqual(self.state.read_text(), "running")
        self.options["tailscale_funnel_enabled"] = False
        self.assertFalse(after_restart.authorized())
        with self.assertRaises(ValueError):
            after_restart.command("start")

    def test_invalid_configuration_never_opens_gateway(self):
        self.options["tailscale_mcp_path"] = "/api/servers"
        self.assertFalse(self.gateway.authorized())
        with self.assertRaises(ValueError):
            self.gateway.command("start")
        self.assertFalse(self.gateway.status()["transport_ready"])
        self.assertEqual(self.gateway.status()["state"], "error")
        for value in ("/mcp/", "/mcp/foo/../admin", "/mcp/foo?key=1"):
            self.options["tailscale_mcp_path"] = value
            self.assertFalse(self.gateway.authorized())

    def test_strict_https_url_prevents_untrusted_probes(self):
        v = self.ts.validate_public_url
        self.assertEqual(v("https://node.tailnet.ts.net/mcp/home", "/mcp/home"),
                         "https://node.tailnet.ts.net/mcp/home")
        self.assertEqual(v("", "/mcp"), "")
        invalid = (
            "http://node.tailnet.ts.net/mcp/home",
            "https://127.0.0.1/mcp/home",
            "https://node.ts.net/mcp/home",
            "https://node.tailnet.ts.net:8443/mcp/home",
            "https://user:pw@node.tailnet.ts.net/mcp/home",
            "https://node.tailnet.ts.net/api/servers",
            "https://node.tailnet.ts.net/mcp/home?key=secret",
            "https://node.tailnet.ts.net/mcp/home#frag",
            "https://node.tailnet.ts.net.evil.com/mcp/home",
            "https://localhost/mcp/home",
        )
        for url in invalid:
            with self.subTest(url=url), self.assertRaises(ValueError):
                v(url, "/mcp/home")

    def test_https_probe_never_sends_auth_or_follows_redirect(self):
        self.options["tailscale_funnel_url"] = "https://node.tailnet.ts.net/mcp/home"
        with patch.object(self.ts, "probe_https", return_value=True) as mock_probe:
            result = self.gateway.check_https()
            mock_probe.assert_called_once_with("https://node.tailnet.ts.net/mcp/home")
            self.assertEqual(result["result"], "gateway_answered")
            self.assertFalse(result["public_internet_proven"])
        self.assertFalse(self.gateway.status()["transport_ready"])
        self.assertIn("NoRedirect", self.ts.probe_https.__code__.co_names)
        self.assertNotIn("Authorization", self.ts.probe_https.__code__.co_consts)


class TailscaleProxyTests(unittest.TestCase):
    def setUp(self):
        self.proxy = load("prepare_proxy_tailscale_test", "prepare_proxy_config.py")

    def server(self, route="/mcp/home", enabled=True, client=None, internal=None):
        return self.proxy.tailscale_gateway_server_block(
            enabled=enabled,
            mcp_path=route,
            client_token="a" * 48 if client is None else client,
            internal_token="mts_" + "b" * 48 if internal is None else internal,
        )

    def test_fail_closed_and_only_mcp_route(self):
        for config in (
            {"enabled": False},
            {"route": "/api/servers"},
            {"route": "/mcp/../api"},
            {"client": "bad"},
            {"internal": "invalid"},
        ):
            with self.subTest(config=config):
                result = self.server(**config)
                self.assertIn("listen 3002;", result)
                self.assertIn("return 404;", result)
                self.assertNotIn("proxy_pass http://127.0.0.1:3000", result)
        good = self.server()
        self.assertIn("location ~ ^/mcp/home$", good)
        self.assertIn('if ($http_authorization != "Bearer ', good)
        self.assertIn("auth_request /__mcphub_tailscale_gate;", good)
        self.assertIn("internal;", good)
        self.assertIn('proxy_set_header Authorization "Bearer mts_', good)
        self.assertIn('proxy_set_header X-MCPHub-HA-Proxy-Secret "";', good)
        self.assertIn('proxy_set_header X-Remote-User-Id "";', good)
        self.assertIn("location / { return 404; }", good)
        self.assertNotIn("location / {\n        proxy_pass", good)

    def test_unpublished_port_by_default(self):
        config = (ROOT / "config.yaml").read_text(encoding="utf-8")
        self.assertIn("3002/tcp: null", config)
        self.assertIn("tailscale_funnel_enabled: false", config)
        self.assertIn("share_homeassistant: disabled", (ROOT / "DOCS.md").read_text())


class TailscaleKeyTests(unittest.TestCase):
    def setUp(self):
        self.prepare = load("prepare_tailscale_test", "prepare_config.py")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.prepare.DATA_DIR = root / "mcphub"
        self.prepare.SECRET_DIR = root / "secret"
        self.prepare.OPTIONS_FILE = root / "options.json"
        self.prepare.SETTINGS_FILE = root / "mcphub" / "mcp_settings.json"
        self.prepare.MANAGED_HOME_ASSISTANT_NAME_FILE = root / "mcphub" / ".managed_ha"
        for attr, filename in (
            ("JWT_SECRET_FILE", "jwt"), ("OPENAI_TOKEN_FILE", "openai"),
            ("OPENAI_AUTH_FILE", "auth"), ("HA_INGRESS_PROXY_SECRET_FILE", "ingress"),
            ("LEGACY_INGRESS_TOKEN_FILE", "legacy"),
            ("CLOUDFLARE_INTERNAL_TOKEN_FILE", "cloudflare_internal"),
            ("CLOUDFLARE_CLIENT_KEY_FILE", "cloudflare_client"),
            ("TAILSCALE_INTERNAL_TOKEN_FILE", "tailscale_internal"),
            ("TAILSCALE_CLIENT_KEY_FILE", "tailscale_client"),
            ("GITHUB_TOKEN_FILE", "github"),
        ):
            setattr(self.prepare, attr, root / "secret" / filename)

    def run_config(self, **options):
        self.prepare.OPTIONS_FILE.write_text(json.dumps(options), encoding="utf-8")
        self.prepare.main()
        return json.loads(self.prepare.SETTINGS_FILE.read_text(encoding="utf-8"))

    def test_keys_scoped_and_independent_and_survive_restart(self):
        state = self.run_config(tailscale={
            "tailscale_funnel_enabled": True,
            "tailscale_mcp_path": "/mcp/home"
        }, cloudflare={
            "cloudflare_tunnel_enabled": True,
            "cloudflare_mcp_path": "/mcp/development"
        })
        keys = {x["name"]: x for x in state["bearerKeys"]}
        tail = keys[self.prepare.TAILSCALE_KEY_NAME]
        cf = keys[self.prepare.CLOUDFLARE_KEY_NAME]
        self.assertEqual(tail["allowedGroups"], ["home"])
        self.assertNotEqual(tail["accessType"], "all")
        self.assertNotEqual(tail["token"], cf["token"])
        self.assertNotEqual(
            self.prepare.TAILSCALE_CLIENT_KEY_FILE.read_text(),
            self.prepare.TAILSCALE_INTERNAL_TOKEN_FILE.read_text())
        self.assertRegex(self.prepare.TAILSCALE_CLIENT_KEY_FILE.read_text(),
                         r"^[A-Za-z0-9_-]{64}$")
        self.assertEqual(self.prepare.TAILSCALE_CLIENT_KEY_FILE.stat().st_mode & 0o777, 0o600)
        before = self.prepare.TAILSCALE_CLIENT_KEY_FILE.read_text()
        again = self.run_config(tailscale={
            "tailscale_funnel_enabled": True, "tailscale_mcp_path": "/mcp/home"
        })
        self.assertEqual(self.prepare.TAILSCALE_CLIENT_KEY_FILE.read_text(), before)
        self.assertIn(self.prepare.TAILSCALE_KEY_NAME, [x["name"] for x in again["bearerKeys"]])

    def test_disabled_or_invalid_revokes_internal_key(self):
        self.run_config(tailscale={
            "tailscale_funnel_enabled": True,
            "tailscale_mcp_path": "/mcp/home"
        })
        for settings in (
            {"tailscale_funnel_enabled": False, "tailscale_mcp_path": "/mcp/home"},
            {"tailscale_funnel_enabled": True, "tailscale_mcp_path": "/api/servers"},
        ):
            result = self.run_config(tailscale=settings)
            self.assertNotIn(self.prepare.TAILSCALE_KEY_NAME,
                             [x["name"] for x in result["bearerKeys"]])


if __name__ == "__main__":
    unittest.main()
