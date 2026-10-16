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

    def test_trusted_merge_dispatch(self):
        payload = {
            "ref": "refs/heads/main",
            "repository": {"full_name": REPO},
            "inputs": {"upstream_version": "1.2.3", "head_sha": SHA},
        }
        self.assertEqual(
            MODULE.validate_dispatch_request(payload, REPO), ("1.2.3", SHA)
        )
        self.assertIsNone(
            MODULE.validate_dispatch_request({**payload, "ref": "refs/heads/dev-mcphub"}, REPO)
        )
        for bad in ("../../1.2.3", "1.2.3-extra", ""):
            with self.assertRaises(ValueError):
                MODULE.validate_dispatch_request(
                    {**payload, "inputs": {**payload["inputs"], "upstream_version": bad}},
                    REPO,
                )

    def test_dispatch_ci_must_match_sha_and_bot(self):
        from unittest.mock import patch
        branch = "automation/mcphub-1.2.3"
        valid = {
            "head_sha": SHA, "head_branch": branch,
            "event": "workflow_dispatch",
            "actor": {"login": "github-actions[bot]"},
            "head_repository": {"full_name": REPO},
            "status": "completed", "conclusion": "success",
            "created_at": "2026-10-16T18:00:00Z",
        }
        with patch.object(MODULE, "get_json", return_value={"workflow_runs": [valid]}):
            MODULE.wait_for_validated_dispatch(REPO, branch, SHA)
        failed = {**valid, "conclusion": "failure"}
        with patch.object(MODULE, "get_json", return_value={"workflow_runs": [failed]}):
            with self.assertRaisesRegex(ValueError, "validation failed"):
                MODULE.wait_for_validated_dispatch(REPO, branch, SHA)
        with patch.object(MODULE, "get_json", return_value={"workflow_runs": [{**valid, "head_sha": "b" * 40}]}):
            with patch.object(MODULE.time, "sleep") as sleep:
                # One poll only: a different commit must never count as green.
                with self.assertRaises(TimeoutError):
                    MODULE.wait_for_validated_dispatch(REPO, branch, SHA, attempts=1)
                sleep.assert_not_called()

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
