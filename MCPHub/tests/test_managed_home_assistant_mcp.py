"""Regression tests for the wrapper-owned Home Assistant MCP server lifecycle."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "prepare_config", Path(__file__).resolve().parents[1] / "prepare_config.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ManagedHomeAssistantMCPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        MODULE.DATA_DIR = root / "mcphub"
        MODULE.SECRET_DIR = root / "secrets"
        MODULE.OPTIONS_FILE = root / "options.json"
        MODULE.SETTINGS_FILE = MODULE.DATA_DIR / "mcp_settings.json"
        MODULE.MANAGED_HOME_ASSISTANT_NAME_FILE = (
            MODULE.DATA_DIR / ".managed_home_assistant_mcp_name"
        )
        for constant, filename in (
            ("JWT_SECRET_FILE", "mcphub_jwt_secret"),
            ("OPENAI_TOKEN_FILE", "mcphub_tunnel_token"),
            ("OPENAI_AUTH_FILE", "mcphub_tunnel_authorization"),
            ("HA_INGRESS_PROXY_SECRET_FILE", "mcphub_ha_ingress_proxy_secret"),
            ("LEGACY_INGRESS_TOKEN_FILE", "mcphub_ingress_token"),
            ("CLOUDFLARE_INTERNAL_TOKEN_FILE", "mcphub_cloudflare_token"),
            ("CLOUDFLARE_CLIENT_KEY_FILE", "mcphub_cloudflare_client_key"),
            ("TAILSCALE_INTERNAL_TOKEN_FILE", "mcphub_tailscale_funnel_token"),
            ("TAILSCALE_CLIENT_KEY_FILE", "mcphub_tailscale_client_key"),
            ("GITHUB_TOKEN_FILE", "github_token"),
        ):
            setattr(MODULE, constant, MODULE.SECRET_DIR / filename)
        self.options(home_assistant_mcp_enabled=True)

    def options(self, **values):
        MODULE.OPTIONS_FILE.write_text(json.dumps(values), encoding="utf-8")

    def servers(self):
        return json.loads(MODULE.SETTINGS_FILE.read_text(encoding="utf-8"))[
            "mcpServers"
        ]

    def test_default_name_and_migration(self):
        MODULE.main()
        self.assertIn("ha-home-assistant", self.servers())
        self.options(
            home_assistant_mcp_enabled=True,
            home_assistant_mcp_server_name="ha-livingroom",
        )
        MODULE.main()
        self.assertIn("ha-livingroom", self.servers())
        self.assertNotIn("ha-home-assistant", self.servers())
        self.assertEqual(
            MODULE.MANAGED_HOME_ASSISTANT_NAME_FILE.read_text().strip(),
            "ha-livingroom",
        )

    def test_legacy_entry_migrates_without_a_tracking_file(self):
        MODULE.main()
        MODULE.MANAGED_HOME_ASSISTANT_NAME_FILE.unlink()
        self.options(
            home_assistant_mcp_enabled=True,
            home_assistant_mcp_server_name="ha-renamed",
        )
        MODULE.main()
        self.assertEqual(list(self.servers()), ["ha-renamed"])

    def test_disable_removes_only_managed_entry(self):
        MODULE.main()
        existing = json.loads(MODULE.SETTINGS_FILE.read_text())
        existing["mcpServers"]["my-own-server"] = {"command": "echo"}
        MODULE.SETTINGS_FILE.write_text(json.dumps(existing))
        self.options(home_assistant_mcp_enabled=False)
        MODULE.main()
        self.assertEqual(self.servers(), {"my-own-server": {"command": "echo"}})
        self.assertFalse(MODULE.MANAGED_HOME_ASSISTANT_NAME_FILE.exists())

    def test_rename_rejects_collision_without_overwriting(self):
        MODULE.main()
        settings = json.loads(MODULE.SETTINGS_FILE.read_text())
        settings["mcpServers"]["other-server"] = {"command": "echo"}
        MODULE.SETTINGS_FILE.write_text(json.dumps(settings))
        self.options(
            home_assistant_mcp_enabled=True,
            home_assistant_mcp_server_name="other-server",
        )
        with self.assertRaisesRegex(ValueError, "non-managed server"):
            MODULE.main()
        self.assertEqual(self.servers()["other-server"], {"command": "echo"})
        self.assertIn("ha-home-assistant", self.servers())

    def test_reused_managed_name_is_never_deleted(self):
        MODULE.main()
        settings = json.loads(MODULE.SETTINGS_FILE.read_text())
        settings["mcpServers"]["ha-home-assistant"] = {"command": "my-own-service"}
        MODULE.SETTINGS_FILE.write_text(json.dumps(settings))
        self.options(
            home_assistant_mcp_enabled=True,
            home_assistant_mcp_server_name="ha-fresh",
        )
        MODULE.main()
        self.assertEqual(
            self.servers()["ha-home-assistant"],
            {"command": "my-own-service"},
        )
        self.assertIn("ha-fresh", self.servers())

    def test_invalid_names(self):
        for name in ("", "/mcp/bad", "with spaces", "ha-github-cli", "x" * 65):
            with self.subTest(name=name):
                self.options(
                    home_assistant_mcp_enabled=True,
                    home_assistant_mcp_server_name=name,
                )
                with self.assertRaises(ValueError):
                    MODULE.main()


if __name__ == "__main__":
    unittest.main()
