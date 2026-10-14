"""Integration regression tests for MCPHub Dev and Stable changelog generation."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GENERATOR = Path(__file__).resolve().parents[2] / ".github/scripts/generate-mcphub-changelog.py"


class ChangelogGenerationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.command("git", "init", "-q")
        self.command("git", "config", "user.name", "Changelog CI")
        self.command("git", "config", "user.email", "ci@example.invalid")
        self.write("MCPHub/config.yaml", 'version: "v2026.10.07-4"\n')
        self.write("MCPHub/CHANGELOG.md", "# Changelog\n\n## v2026.10.07-4\n\n- Existing stable notes.\n")
        self.commit("stable")
        self.command("git", "branch", "-M", "main")
        self.command("git", "update-ref", "refs/remotes/origin/main", "HEAD")
        self.command("git", "switch", "-q", "-c", "dev-mcphub")
        self.write("MCPHub/config.yaml", 'version: "v2026.10.12-1"\n')
        self.write("MCPHub/CHANGELOG.md", "# Changelog\n\n## v2026.10.12-1\n\n- Curated fix notes.\n\n## v2026.10.07-4\n\n- Existing stable notes.\n")
        self.write("MCPHub/README.md", "Initial feature.\n")
        self.commit("feat(mcphub): first dev feature (#1)")
        self.command("git", "update-ref", "refs/remotes/origin/dev-mcphub", "HEAD")
        self.command("git", "switch", "-q", "-c", "dev-store")
        self.write("MCPHub/config.yaml", 'version: "v2026.10.12-1-dev.42"\n')
        self.state(42)
        self.commit("prepare dev-store snapshot")

    def command(self, *args, ok=True):
        result = subprocess.run(args, cwd=self.root, capture_output=True, text=True)
        if ok and result.returncode:
            self.fail(f"{args}: {result.stderr}")
        return result

    def generate(self, *args, ok=True):
        return self.command(sys.executable, str(GENERATOR), *args, ok=ok)

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self, title):
        self.command("git", "add", ".")
        self.command("git", "commit", "-qm", title)

    def state(self, revision):
        self.write(".dev-store-revisions.json", json.dumps({"mcphub": {"revision": revision}}))

    def test_dev_history_is_complete_and_idempotent(self):
        self.generate("dev")
        first = (self.root / "MCPHub/CHANGELOG.md").read_text()
        self.assertIn("## v2026.10.12-1-dev.42", first)
        self.assertIn("feat(mcphub): first dev feature", first)
        self.assertIn("Curated fix notes.", first)
        self.generate("dev")
        self.assertEqual(first, (self.root / "MCPHub/CHANGELOG.md").read_text())
        self.commit("compose initial dev-store")
        self.command("git", "switch", "-q", "dev-mcphub")
        self.write("MCPHub/README.md", "Updated feature.\n")
        self.commit("fix(mcphub): next individual fix (#2)")
        self.command("git", "update-ref", "refs/remotes/origin/dev-mcphub", "HEAD")
        self.command("git", "switch", "-q", "dev-store")
        self.command("git", "checkout", "origin/dev-mcphub", "--", "MCPHub")
        self.write("MCPHub/config.yaml", 'version: "v2026.10.12-1-dev.43"\n')
        self.state(43)
        self.generate("dev")
        latest = (self.root / "MCPHub/CHANGELOG.md").read_text()
        for expected in (
            "## v2026.10.12-1-dev.43",
            "## v2026.10.12-1-dev.42",
            "feat(mcphub): first dev feature",
            "fix(mcphub): next individual fix",
            "MCPHub/README.md",
            "Curated fix notes.",
            "Existing stable notes.",
        ):
            self.assertIn(expected, latest)
        history = json.loads((self.root / ".dev-store-mcphub-changes.json").read_text())
        self.assertEqual([entry["revision"] for entry in history], [43, 42])
        self.generate("dev")
        self.assertEqual(latest, (self.root / "MCPHub/CHANGELOG.md").read_text())

    def test_stable_gate_rejects_missing_or_tampered_notes(self):
        self.command("git", "switch", "-q", "dev-mcphub")
        self.assertNotEqual(self.generate("stable", "--check", ok=False).returncode, 0)
        self.generate("stable")
        expected = (self.root / "MCPHub/CHANGELOG.md").read_text()
        self.assertIn("Complete changes since stable v2026.10.07-4", expected)
        self.assertIn("feat(mcphub): first dev feature", expected)
        self.assertIn("Curated fix notes.", expected)
        self.generate("stable", "--check")
        self.generate("stable")
        self.assertEqual(expected, (self.root / "MCPHub/CHANGELOG.md").read_text())
        self.write("MCPHub/CHANGELOG.md", expected.replace("first dev feature", "hidden"))
        self.assertNotEqual(self.generate("stable", "--check", ok=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
