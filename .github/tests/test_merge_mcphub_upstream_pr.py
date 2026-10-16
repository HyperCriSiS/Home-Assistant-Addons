"""Unit tests for privileged MCPHub upstream auto-merge gates."""

import importlib.util
import unittest
from pathlib import Path

P = Path(__file__).resolve().parents[1] / "scripts/merge_mcphub_upstream_pr.py"
SPEC = importlib.util.spec_from_file_location("merge_mcphub_upstream_pr", P)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
REPO = "HyperCriSiS/Home-Assistant-Apps"
SHA = "a" * 40


def event(**overrides):
    data = {
        "workflow_run": {
            "conclusion": "success",
            "event": "pull_request",
            "head_repository": {"full_name": REPO},
            "actor": {"login": "github-actions[bot]"},
            "head_branch": "automation/mcphub-1.2.3",
            "head_sha": SHA,
        }
    }
    data["workflow_run"].update(overrides)
    return data


def candidate(**overrides):
    data = {
        "number": 123,
        "state": "open",
        "draft": False,
        "title": "chore(mcphub): update upstream to 1.2.3",
        "user": {"login": "github-actions[bot]"},
        "base": {"ref": "dev-mcphub"},
        "head": {"repo": {"full_name": REPO}, "sha": SHA},
    }
    data.update(overrides)
    return data


class AutomationGateTests(unittest.TestCase):
    def test_trusted_success_accepted(self):
        self.assertEqual(MODULE.validate_run(event(), REPO), ("1.2.3", SHA))

    def test_trusted_dispatch_success_accepted(self):
        self.assertEqual(
            MODULE.validate_run(event(event="workflow_dispatch"), REPO),
            ("1.2.3", SHA),
        )

    def test_other_events_are_skipped(self):
        for overrides in (
            {"conclusion": "failure"},
            {"event": "push"},
            {"head_repository": {"full_name": "stranger/fork"}},
            {"actor": {"login": "someone"}},
            {"head_branch": "fix/mcphub-1.2.3"},
            {"head_branch": "automation/mcphub-1.2.3/evil"},
            {"head_sha": "bad"},
        ):
            with self.subTest(overrides=overrides):
                self.assertIsNone(MODULE.validate_run(event(**overrides), REPO))

    def test_candidate_identity(self):
        MODULE.validate_candidate(candidate(), REPO, "1.2.3", SHA)
        for changes in (
            {"state": "closed"},
            {"draft": True},
            {"title": "chore(mcphub): something else"},
            {"user": {"login": "someone"}},
            {"base": {"ref": "main"}},
            {"head": {"repo": {"full_name": "stranger/fork"}, "sha": SHA}},
            {"head": {"repo": {"full_name": REPO}, "sha": "b" * 40}},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    MODULE.validate_candidate(candidate(**changes), REPO, "1.2.3", SHA)

    def test_expected_file_list(self):
        files = [
            {"filename": path, "status": "modified"}
            for path in sorted(MODULE.ALLOWED_FILES)
        ]
        original = MODULE.get_json
        try:
            MODULE.get_json = lambda _endpoint: files
            MODULE.validate_files(REPO, 123)
            for bad_files in (
                files + [{"filename": ".github/workflows/evil.yml", "status": "added"}],
                files[:-1],
                [*files[:-1], {"filename": files[-1]["filename"], "status": "renamed"}],
            ):
                MODULE.get_json = lambda _endpoint, result=bad_files: result
                with self.assertRaises(ValueError):
                    MODULE.validate_files(REPO, 123)
        finally:
            MODULE.get_json = original


if __name__ == "__main__":
    unittest.main()