"""Regression checks for trusted OpenAI/Cloudflare updates."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "scripts" / "update-mcphub-tunnel-clients.py"
spec = importlib.util.spec_from_file_location("tunnel_update", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

DOCKER = "ARG OPENAI_TUNNEL_VERSION=v0.0.16\nARG CLOUDFLARED_VERSION=2026.10.1\n"
NOTES = "# Changelog\n\n## v2026.10.17-1\n\n- Existing notes.\n\n## v2026.10.16\n\n- Previous.\n"


class UpdateTests(unittest.TestCase):
    def test_no_update(self):
        self.assertEqual(mod.prepare(DOCKER, NOTES, "v0.0.16", "2026.10.1"),
                         (DOCKER, NOTES, False))

    def test_update_both(self):
        docker, notes, changed = mod.prepare(DOCKER, NOTES, "v0.0.17", "2026.10.2")
        self.assertTrue(changed)
        self.assertEqual(mod.pins(docker), ("v0.0.17", "2026.10.2"))
        self.assertIn("OpenAI tunnel-client v0.0.16 to v0.0.17", notes)
        self.assertIn("cloudflared 2026.10.1 to 2026.10.2", notes)
        self.assertIn("## v2026.10.16\n\n- Previous.", notes)

    def test_update_one(self):
        docker, notes, changed = mod.prepare(DOCKER, NOTES, "v0.0.16", "2026.11.1")
        self.assertTrue(changed)
        self.assertIn("cloudflared 2026.10.1 to 2026.11.1", notes)
        self.assertNotIn("OpenAI tunnel-client", notes)
        self.assertEqual(mod.pins(docker)[0], "v0.0.16")

    def test_reject_downgrades_prereleases_and_malformed_data(self):
        for versions in (("v0.0.15", "2026.10.1"),
                         ("v0.0.16", "2026.9.4"),
                         ("v0.0.17-rc1", "2026.10.1"),
                         ("v0.0.17", "latest")):
            with self.subTest(versions=versions), self.assertRaises(ValueError):
                mod.prepare(DOCKER, NOTES, *versions)
        with self.assertRaises(ValueError):
            mod.prepare(DOCKER, "wrong header", "v0.0.17", "2026.10.2")

    def test_unique_stable_branch_name(self):
        branch = mod.branch_for("v0.0.17", "2026.10.2")
        self.assertEqual(branch, "automation/mcphub-tunnel-clients-v0_0_17-2026_10_2")
        self.assertIsNotNone(mod.BRANCH.fullmatch(branch))
        with self.assertRaises(ValueError):
            mod.branch_for("v0.0.17-rc", "2026.10.2")

    def test_reject_unrelated_changes_before_reading_sources(self):
        branch = mod.branch_for("v0.0.17", "2026.10.2")
        sha = "a" * 40
        pr = {"number": 84, "title": mod.TITLE, "draft": False, "state": "open",
              "head": {"sha": sha, "ref": branch, "repo": {"full_name": "x/y"}},
              "base": {"ref": "dev-mcphub"}}
        files = [{"filename": p, "status": "modified"} for p in
                 ("MCPHub/Dockerfile", "MCPHub/CHANGELOG.md", "MCPHub/run.sh")]
        with patch.object(mod, "api", side_effect=[[pr], files]), \
             patch.object(mod, "git") as git:
            with self.assertRaisesRegex(ValueError, "unexpected or missing"):
                mod.verify_candidate("x/y", branch, sha, "v0.0.17", "2026.10.2")
            git.assert_not_called()

    def test_failed_ci_cannot_merge(self):
        branch = mod.branch_for("v0.0.17", "2026.10.2")
        sha = "a" * 40
        run = {"head_sha": sha, "head_branch": branch, "event": "workflow_dispatch",
               "head_repository": {"full_name": "x/y"},
               "actor": {"login": "github-actions[bot]"},
               "status": "completed", "conclusion": "failure"}
        with patch.object(mod, "api", return_value={"workflow_runs": [run]}):
            with self.assertRaisesRegex(ValueError, "CI failed"):
                mod.wait_for_ci("x/y", branch, sha, attempts=1)


if __name__ == "__main__":
    unittest.main()
