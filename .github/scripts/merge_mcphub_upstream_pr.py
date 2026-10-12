#!/usr/bin/env python3
"""Merge only verified, CI-green MCPHub upstream update PRs into dev-mcphub.

This script must run from the repository default branch in a privileged
workflow_run job, NEVER from a pull request checkout.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

BRANCH_RE = re.compile(r"^automation/mcphub-(\d+\.\d+\.\d+)$")
ALLOWED_FILES = frozenset(
    {
        "MCPHub/CHANGELOG.md",
        "MCPHub/Dockerfile",
        "MCPHub/NOTICE.md",
        "MCPHub/build.yaml",
        "MCPHub/config.yaml",
        "MCPHub/ingress.conf",
        "MCPHub/patch_home_assistant_auth.py",
        "MCPHub/run.sh",
    }
)


def gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def get_json(endpoint: str) -> object:
    return json.loads(gh("api", endpoint))


def validate_run(event: dict, repository: str) -> tuple[str, str] | None:
    run = event.get("workflow_run", {})
    if (
        run.get("conclusion") != "success"
        or run.get("event") != "pull_request"
        or run.get("head_repository", {}).get("full_name") != repository
        or run.get("actor", {}).get("login") != "github-actions[bot]"
    ):
        print("Not a successful first-party automated PR validation; skipping")
        return None

    branch = run.get("head_branch", "")
    match = BRANCH_RE.fullmatch(branch)
    sha = run.get("head_sha", "")
    if not match or not re.fullmatch(r"[0-9a-f]{40}", sha):
        print("Not a versioned MCPHub automation branch; skipping")
        return None
    return match.group(1), sha


def find_candidate(repository: str, branch: str) -> dict | None:
    # Pagination avoids accidental dependency on the first 30 open PRs.
    for page in range(1, 11):
        prs = get_json(
            f"repos/{repository}/pulls?state=open&base=dev-mcphub&per_page=100&page={page}"
        )
        if not isinstance(prs, list):
            raise ValueError("Unexpected GitHub pull requests response")
        matches = [pr for pr in prs if pr.get("head", {}).get("ref") == branch]
        if len(matches) > 1:
            raise ValueError("More than one matching upstream PR")
        if matches:
            return matches[0]
        if len(prs) < 100:
            return None
    raise ValueError("Too many open PRs to verify reliably")


def validate_candidate(pr: dict, repository: str, version: str, sha: str) -> None:
    expected_title = f"chore(mcphub): update upstream to {version}"
    if not (
        pr.get("state") == "open"
        and pr.get("draft") is False
        and pr.get("title") == expected_title
        and pr.get("user", {}).get("login") == "github-actions[bot]"
        and pr.get("base", {}).get("ref") == "dev-mcphub"
        and pr.get("head", {}).get("repo", {}).get("full_name") == repository
        and pr.get("head", {}).get("sha") == sha
    ):
        raise ValueError("Upstream PR identity, title, target or SHA mismatch")


def validate_files(repository: str, number: int) -> None:
    files = get_json(f"repos/{repository}/pulls/{number}/files?per_page=100")
    if not isinstance(files, list):
        raise ValueError("Unexpected GitHub PR files response")
    paths = {item.get("filename") for item in files}
    if (
        len(files) != len(ALLOWED_FILES)
        or paths != ALLOWED_FILES
        or any(item.get("status") != "modified" for item in files)
    ):
        raise ValueError(
            f"Upstream PR has unexpected files: {sorted(str(x) for x in paths)}"
        )


def main() -> None:
    repository = os.environ["GITHUB_REPOSITORY"]
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    eligible = validate_run(event, repository)
    if eligible is None:
        return

    version, sha = eligible
    branch = f"automation/mcphub-{version}"
    pr = find_candidate(repository, branch)
    if pr is None:
        print(f"No open upstream PR for {branch}; already merged or closed")
        return

    validate_candidate(pr, repository, version, sha)
    number = pr["number"]
    validate_files(repository, number)

    # Even if the status check completed before this job started, --match-head-commit
    # prevents merging new or untested commits pushed to the PR in the meantime.
    print(f"Merging validated MCPHub upstream update PR #{number} ({sha})")
    gh(
        "pr", "merge", str(number), "--repo", repository,
        "--squash", "--delete-branch", "--match-head-commit", sha,
    )

    # workflow_run can merge using GITHUB_TOKEN. Such pushes do not start other
    # push workflows, so explicitly dispatch the dev store sync and validation.
    gh("workflow", "run", "sync-dev-store.yml", "--repo", repository, "--ref", "main")
    gh("workflow", "run", "validate-mcphub.yml", "--repo", repository, "--ref", "dev-mcphub")
    print(f"Merged PR #{number} to dev-mcphub and dispatched development checks")


if __name__ == "__main__":
    main()
