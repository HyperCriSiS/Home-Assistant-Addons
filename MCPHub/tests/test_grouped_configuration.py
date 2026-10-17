"""Regression tests for grouped Home Assistant App option parsing and translations."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml


ADDON = Path(__file__).resolve().parents[1]
GROUPS = {
    "openai": (
        "tunnel_enabled", "openai_runtime_api_key", "tunnel_id", "tunnel_mcp_path",
    ),
    "cloudflare": (
        "cloudflare_tunnel_enabled", "cloudflare_tunnel_token",
        "cloudflare_mcp_path",
    ),
    "tailscale": (
        "tailscale_funnel_enabled", "tailscale_mcp_path", "tailscale_funnel_url",
    ),
    "home_assistant": (
        "home_assistant_mcp_enabled", "home_assistant_mcp_server_name",
        "home_assistant_mcp_auth_mode", "home_assistant_mcp_user_token",
        "home_assistant_mcp_url", "home_assistant_mcp_ca_file",
    ),
    "github": ("github_cli_mcp_enabled", "github_token"),
    "logging": ("tunnel_log_level",),
}


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, ADDON / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GroupedConfigurationTests(unittest.TestCase):
    def test_manifest_options_schema_and_translations_match(self):
        config = yaml.safe_load((ADDON / "config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(list(config["options"]), list(GROUPS))
        self.assertEqual(list(config["schema"]), list(GROUPS))

        for group, keys in GROUPS.items():
            with self.subTest(group=group):
                self.assertEqual(tuple(config["options"][group]), keys)
                self.assertEqual(tuple(config["schema"][group]), keys)

        for language in ("en", "de"):
            translations = yaml.safe_load(
                (ADDON / "translations" / f"{language}.yaml").read_text(encoding="utf-8")
            )["configuration"]
            self.assertEqual(list(translations), list(GROUPS))
            for group, keys in GROUPS.items():
                with self.subTest(language=language, group=group):
                    self.assertTrue(translations[group]["name"])
                    self.assertEqual(tuple(translations[group]["fields"]), keys)
                    for key in keys:
                        self.assertTrue(translations[group]["fields"][key]["name"])

    def test_option_readers_support_legacy_and_nested_values(self):
        legacy = {
            "tunnel_enabled": True,
            "tunnel_mcp_path": "/mcp/development",
            "home_assistant_mcp_enabled": True,
            "github_token": "test-token",
        }
        grouped = {
            "openai": {
                "tunnel_enabled": True, "tunnel_mcp_path": "/mcp/development",
            },
            "home_assistant": {"home_assistant_mcp_enabled": True},
            "github": {"github_token": "test-token"},
        }
        mixed = {
            **legacy,
            "openai": {"tunnel_enabled": False},
            "home_assistant": {"home_assistant_mcp_enabled": False},
        }
        with tempfile.TemporaryDirectory() as directory:
            options_file = Path(directory) / "options.json"
            for name in ("prepare_config", "prepare_proxy_config"):
                module = load_module(name)
                for label, values in (
                    ("legacy", legacy), ("grouped", grouped), ("mixed", mixed),
                ):
                    with self.subTest(reader=name, format=label):
                        options_file.write_text(json.dumps(values), encoding="utf-8")
                        with patch.object(module, "OPTIONS_FILE", options_file):
                            loaded = module.load_options()
                        self.assertEqual(loaded["tunnel_mcp_path"], "/mcp/development")
                        self.assertEqual(loaded["github_token"], "test-token")
                        should_enable = label != "mixed"
                        self.assertIs(loaded["tunnel_enabled"], should_enable)
                        self.assertIs(loaded["home_assistant_mcp_enabled"], should_enable)


if __name__ == "__main__":
    unittest.main()
