"""Test fail-closed Tailscale Serve/Funnel origin configuration and isolated keys."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.mod = load("tailscale_proxy", "prepare_proxy_config.py")

    def origin(self, port, enabled, path="/mcp/development", token="a" * 48):
        return self.mod.tailscale_origin_server_block(
            port=port, enabled=enabled, mcp_path=path,
            client_token=token, internal_token="internal")

    def test_disabled_and_invalid_fail_closed(self):
        for port in (8094, 8095):
            for active, route, key in ((False, "/mcp", "a" * 48),
                                       (True, "/admin", "a" * 48),
                                       (True, "/mcp", "short")):
                result = self.origin(port, active, route, key)
                self.assertNotIn("proxy_pass", result)
                self.assertIn("return 404", result)
                mode = "serve" if port == 8094 else "funnel"
                self.assertIn(f"listen unix:/share/mcphub/tailscale-{mode}.sock;", result)

    def test_exact_route_and_private_authorization(self):
        for port in (8094, 8095):
            result = self.origin(port, True)
            self.assertIn("location ~ ^/mcp/development$", result)
            self.assertNotIn("listen 8094", result)
            self.assertNotIn("listen 8095", result)
            self.assertIn("return 401;", result)
            self.assertIn('proxy_set_header Authorization "Bearer internal";', result)
            self.assertIn('proxy_set_header X-MCPHub-HA-Proxy-Secret "";', result)
            self.assertIn('proxy_set_header X-Remote-User-Id "";', result)
            self.assertIn("location / { return 404; }", result)

    def test_reject_unexpected_port(self):
        with self.assertRaises(ValueError):
            self.origin(8099, True)


class KeyTests(unittest.TestCase):
    def setUp(self):
        self.mod = load("tailscale_settings", "prepare_config.py")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.mod.DATA_DIR = root / "mcphub"
        self.mod.SECRET_DIR = root / "secrets"
        self.mod.OPTIONS_FILE = root / "options.json"
        self.mod.SETTINGS_FILE = root / "mcphub" / "mcp_settings.json"
        self.mod.MANAGED_HOME_ASSISTANT_NAME_FILE = root / "mcphub" / ".managed_home_assistant_mcp_name"
        names = {
            "JWT_SECRET_FILE": "jwt", "OPENAI_TOKEN_FILE": "openai",
            "OPENAI_AUTH_FILE": "auth", "HA_INGRESS_PROXY_SECRET_FILE": "ingress",
            "LEGACY_INGRESS_TOKEN_FILE": "legacy", "CLOUDFLARE_INTERNAL_TOKEN_FILE": "cf",
            "TAILSCALE_SERVE_INTERNAL_TOKEN_FILE": "serve",
            "TAILSCALE_FUNNEL_INTERNAL_TOKEN_FILE": "funnel", "GITHUB_TOKEN_FILE": "gh",
        }
        for attr, filename in names.items():
            setattr(self.mod, attr, root / "secrets" / filename)

    def run_with(self, **options):
        self.mod.OPTIONS_FILE.write_text(json.dumps(options))
        self.mod.main()
        return json.loads(self.mod.SETTINGS_FILE.read_text())

    def test_independent_scoped_keys(self):
        config = self.run_with(tailscale={
            "tailscale_serve_enabled": True, "tailscale_serve_mcp_path": "/mcp/development",
            "tailscale_funnel_enabled": True, "tailscale_funnel_mcp_path": "/mcp/home",
        })
        keys = {key["name"]: key for key in config["bearerKeys"]}
        serve = keys["Home Assistant Tailscale Serve"]
        funnel = keys["Home Assistant Tailscale Funnel"]
        self.assertNotEqual(serve["token"], funnel["token"])
        self.assertEqual(serve["allowedGroups"], ["development"])
        self.assertEqual(funnel["allowedGroups"], ["home"])

    def test_disabled_revokes_key_but_preserves_secret(self):
        self.run_with(tailscale={"tailscale_serve_enabled": True})
        initial = self.mod.TAILSCALE_SERVE_INTERNAL_TOKEN_FILE.read_text()
        keys = self.run_with(tailscale={"tailscale_serve_enabled": False})["bearerKeys"]
        self.assertNotIn("Home Assistant Tailscale Serve", [key["name"] for key in keys])
        self.assertEqual(initial, self.mod.TAILSCALE_SERVE_INTERNAL_TOKEN_FILE.read_text())

    def test_existing_openai_unchanged(self):
        config = self.run_with(openai={"tunnel_enabled": True})
        names = [key["name"] for key in config["bearerKeys"]]
        self.assertIn("Home Assistant OpenAI Tunnel", names)
        self.assertNotIn("Home Assistant Tailscale Serve", names)


if __name__ == "__main__":
    unittest.main()
