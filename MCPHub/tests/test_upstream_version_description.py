"""Verify updater version and descriptions using the packaged version as baseline."""

from datetime import date, timedelta
import importlib.util
import pathlib
import re
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

        config = yaml.safe_load((self.root / "MCPHub/config.yaml").read_text())
        build = yaml.safe_load((self.root / "MCPHub/build.yaml").read_text())
        self.current_upstream = build["build_from"]["amd64"].rsplit(":", 1)[1]
        parts = [int(part) for part in self.current_upstream.split(".")]
        self.target_upstream = f"{parts[0]}.{parts[1]}.{parts[2] + 1}"

        match = re.fullmatch(r"v(\d{4}\.\d{2}\.\d{2})(?:-\d+)?", config["version"])
        self.assertIsNotNone(match, "Unexpected wrapper version in test fixture")
        self.test_date = date.fromisoformat(match.group(1).replace(".", "-")) + timedelta(days=1)
        self.target_wrapper = f"v{self.test_date:%Y.%m.%d}"

    def run_updater(self):
        with patch.object(MODULE, "ROOT", self.root):
            with patch.object(
                sys, "argv",
                ["update-mcphub-upstream.py", "--version", self.target_upstream,
                 "--release-url", "https://example.invalid",
                 "--date", self.test_date.isoformat()],
            ):
                MODULE.main()

    def test_upstream_bump_updates_description_and_image(self):
        self.run_updater()
        config = yaml.safe_load((self.root / "MCPHub/config.yaml").read_text())
        build = yaml.safe_load((self.root / "MCPHub/build.yaml").read_text())
        self.assertEqual(config["version"], self.target_wrapper)
        self.assertEqual(
            config["description"],
            f"MCPHub {self.target_upstream} - central MCP server management "
            "with optional Home Assistant, OpenAI and Cloudflare integrations",
        )
        self.assertEqual(
            set(build["build_from"].values()),
            {f"samanhappy/mcphub:{self.target_upstream}"},
        )
        self.assertTrue(
            (self.root / "MCPHub/CHANGELOG.md").read_text().startswith(
                f"# Changelog\n\n## {self.target_wrapper}\n"
            )
        )

    def test_stale_description_is_rejected(self):
        config = self.root / "MCPHub/config.yaml"
        original = config.read_text()
        marker = f"MCPHub {self.current_upstream} - central"
        self.assertIn(marker, original)
        config.write_text(original.replace(marker, "MCPHub 0.0.0 - central"))
        with self.assertRaisesRegex(SystemExit, "MCPHub/config.yaml: expected"):
            self.run_updater()


if __name__ == "__main__":
    unittest.main()
