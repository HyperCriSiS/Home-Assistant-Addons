"""Verify an upstream update also refreshes the Home Assistant App description."""

import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml


REPOSITORY = pathlib.Path(__file__).resolve().parents[2]
UPDATER = REPOSITORY / ".github/scripts/update-mcphub-upstream.py"
SPEC = importlib.util.spec_from_file_location("mcphub_updater", UPDATER)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

RELEASE_FILES = (
    "MCPHub/build.yaml",
    "MCPHub/Dockerfile",
    "MCPHub/run.sh",
    "MCPHub/ingress.conf",
    "MCPHub/NOTICE.md",
    "MCPHub/config.yaml",
    "MCPHub/CHANGELOG.md",
    "MCPHub/patch_home_assistant_auth.py",
)


class DescriptionUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = pathlib.Path(self.temp_dir.name)
        for name in RELEASE_FILES:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((REPOSITORY / name).read_bytes())

    def run_updater(self):
        with patch.object(MODULE, "ROOT", self.root):
            with patch.object(
                sys, "argv",
                ["update-mcphub-upstream.py", "--version", "1.1.4",
                 "--release-url", "https://example.invalid", "--date", "2026-10-13"],
            ):
                MODULE.main()

    def test_upstream_bump_updates_description_and_image(self):
        self.run_updater()
        config = yaml.safe_load((self.root / "MCPHub/config.yaml").read_text())
        build = yaml.safe_load((self.root / "MCPHub/build.yaml").read_text())
        self.assertEqual(config["version"], "v2026.10.13")
        self.assertEqual(
            config["description"],
            "MCPHub 1.1.4 - central MCP server management with optional "
            "Home Assistant, OpenAI and Cloudflare integrations",
        )
        self.assertEqual(
            set(build["build_from"].values()), {"samanhappy/mcphub:1.1.4"}
        )
        self.assertTrue(
            (self.root / "MCPHub/CHANGELOG.md").read_text().startswith(
                "# Changelog\n\n## v2026.10.13\n"
            )
        )

    def test_stale_description_is_rejected(self):
        config = self.root / "MCPHub/config.yaml"
        config.write_text(
            config.read_text().replace(
                "MCPHub 1.1.3 - central", "MCPHub 0.0.0 - central"
            )
        )
        with self.assertRaisesRegex(SystemExit, "MCPHub/config.yaml: expected"):
            self.run_updater()


if __name__ == "__main__":
    unittest.main()
