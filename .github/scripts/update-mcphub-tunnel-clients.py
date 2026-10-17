#!/usr/bin/env python3
"""Strict update and merge gates for the two bundled MCPHub tunnel binaries.

Invoked only by the trusted main-branch GitHub Actions workflow. Never execute
this helper from a pull request checkout in a privileged job.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import quote

OPENAI = re.compile(r"v[0-9]+[.][0-9]+[.][0-9]+")
CLOUDFLARE = re.compile(r"[0-9]{4}[.][0-9]+[.][0-9]+")
BRANCH = re.compile(
    r"automation/mcphub-tunnel-clients-(v[0-9]+_[0-9]+_[0-9]+)-([0-9]{4}_[0-9]+_[0-9]+)"
)
TITLE = "chore(mcphub): update OpenAI and Cloudflare tunnel clients"
ALLOWED_FILES = {"MCPHub/Dockerfile", "MCPHub/CHANGELOG.md"}


def gh(*arguments: str) -> str:
    return subprocess.check_output(["gh", *arguments], text=True).strip()


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], text=True)


def pins(dockerfile: str) -> tuple[str, str]:
    def value(variable: str, expected: re.Pattern[str]) -> str:
        occurrences = re.findall(rf"^ARG {variable}=(\S+)$", dockerfile, re.M)
        if len(occurrences) != 1 or not expected.fullmatch(occurrences[0]):
            raise ValueError(f"Missing or invalid {variable} Dockerfile pin")
        return occurrences[0]

    return value("OPENAI_TUNNEL_VERSION", OPENAI), value("CLOUDFLARED_VERSION", CLOUDFLARE)


def as_tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(x) for x in value.removeprefix("v").split("."))


def branch_for(openai: str, cloudflare: str) -> str:
    if not OPENAI.fullmatch(openai) or not CLOUDFLARE.fullmatch(cloudflare):
        raise ValueError("Only official stable three-part release tags are supported")
    return (
        "automation/mcphub-tunnel-clients-"
        + openai.replace(".", "_") + "-" + cloudflare.replace(".", "_")
    )


def prepare(dockerfile: str, changelog: str, openai: str, cloudflare: str) -> tuple[str, str, bool]:
    if not OPENAI.fullmatch(openai) or not CLOUDFLARE.fullmatch(cloudflare):
        raise ValueError("Rejecting unrecognized, prerelease or floating tunnel image tags")
    current_openai, current_cloudflare = pins(dockerfile)
    if as_tuple(openai) < as_tuple(current_openai) or as_tuple(cloudflare) < as_tuple(current_cloudflare):
        raise ValueError("Refusing tunnel-client version downgrade")

    changes = []
    if openai != current_openai:
        changes.append(f"OpenAI tunnel-client {current_openai} to {openai}")
    if cloudflare != current_cloudflare:
        changes.append(f"cloudflared {current_cloudflare} to {cloudflare}")
    if not changes:
        return dockerfile, changelog, False

    updated = dockerfile.replace(
        f"ARG OPENAI_TUNNEL_VERSION={current_openai}",
        f"ARG OPENAI_TUNNEL_VERSION={openai}",
        1,
    ).replace(
        f"ARG CLOUDFLARED_VERSION={current_cloudflare}",
        f"ARG CLOUDFLARED_VERSION={cloudflare}",
        1,
    )
    if not re.match(r"^# Changelog\n\n## v[0-9]{4}[.][0-9]{2}[.][0-9]{2}(?:-[1-9][0-9]*)?\n", changelog):
        raise ValueError("Unexpected MCPHub source changelog header")
    first_break = changelog.find("\n", len("# Changelog\n\n"))
    note = "- Updated bundled tunnel binaries: " + "; ".join(changes) + ".\n"
    new_changelog = changelog[:first_break + 1] + "\n" + note + changelog[first_break + 1:]
    return updated, new_changelog, True


def api(endpoint: str):
    return json.loads(gh("api", endpoint))


def verify_candidate(repository: str, branch: str, sha: str, openai: str, cloudflare: str) -> int:
    if branch != branch_for(openai, cloudflare):
        raise ValueError("Automation branch/tag mismatch")
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Unrecognized candidate SHA")
    if not BRANCH.fullmatch(branch):
        raise ValueError("Unrecognized automation branch")
    prs = api(f"repos/{repository}/pulls?state=open&base=dev-mcphub&per_page=100")
    matching = [pr for pr in prs if pr.get("head", {}).get("ref") == branch]
    if len(matching) != 1:
        raise ValueError("Expected exactly one open tunnel update pull request")
    pr = matching[0]
    if not (
        pr.get("draft") is False
        and pr.get("title") == TITLE
        and pr.get("head", {}).get("repo", {}).get("full_name") == repository
        and pr.get("base", {}).get("ref") == "dev-mcphub"
        and pr.get("head", {}).get("sha") == sha
        and pr.get("state") == "open"
    ):
        raise ValueError("PR target, identity, branch or HEAD mismatch")
    number = pr["number"]
    files = api(f"repos/{repository}/pulls/{number}/files?per_page=100")
    if (
        len(files) != len(ALLOWED_FILES)
        or {f.get("filename") for f in files} != ALLOWED_FILES
        or any(f.get("status") != "modified" for f in files)
    ):
        raise ValueError("PR modifies unexpected or missing files")

    # Verify every byte of the generated update against the current dev base.
    # A successful build alone is not permission to merge unrelated code.
    git("fetch", "--no-tags", "origin", "dev-mcphub", branch)
    current_docker = git("show", "origin/dev-mcphub:MCPHub/Dockerfile")
    current_notes = git("show", "origin/dev-mcphub:MCPHub/CHANGELOG.md")
    desired_docker, desired_notes, changed = prepare(
        current_docker, current_notes, openai, cloudflare
    )
    if not changed:
        raise ValueError("Tunnel update is already on dev-mcphub")
    candidate_docker = git("show", f"{sha}:MCPHub/Dockerfile")
    candidate_notes = git("show", f"{sha}:MCPHub/CHANGELOG.md")
    if candidate_docker != desired_docker or candidate_notes != desired_notes:
        raise ValueError("Candidate content differs from trusted version updater")
    git("merge-base", "--is-ancestor", "origin/dev-mcphub", sha)
    return number


def wait_for_ci(repository: str, branch: str, sha: str, attempts: int = 168) -> None:
    url = (
        f"repos/{repository}/actions/workflows/validate-mcphub.yml/runs?"
        f"event=workflow_dispatch&branch={quote(branch, safe='')}&per_page=100"
    )
    for attempt in range(attempts):
        response = api(url)
        runs = response.get("workflow_runs", [])
        matches = [
            r for r in runs if (
                r.get("head_sha") == sha
                and r.get("head_branch") == branch
                and r.get("event") == "workflow_dispatch"
                and r.get("actor", {}).get("login") == "github-actions[bot]"
                and r.get("head_repository", {}).get("full_name") == repository
            )
        ]
        if matches:
            selected = max(matches, key=lambda r: r.get("created_at", ""))
            if selected.get("status") == "completed":
                if selected.get("conclusion") != "success":
                    raise ValueError(f"Tunnel update CI failed: {selected.get('conclusion')}")
                return
        if attempt < attempts - 1:
            time.sleep(15)
    raise TimeoutError("No successful same-SHA validation of tunnel update")


def verify_and_merge(repository: str, branch: str, sha: str, openai: str, cloudflare: str):
    number = verify_candidate(repository, branch, sha, openai, cloudflare)
    wait_for_ci(repository, branch, sha)
    # Recheck base, candidate contents and SHA immediately before merging.
    if verify_candidate(repository, branch, sha, openai, cloudflare) != number:
        raise ValueError("Update PR changed during validation")
    gh("pr", "merge", str(number), "--repo", repository, "--squash",
       "--delete-branch", "--match-head-commit", sha)
    # GITHUB_TOKEN commits do not recursively trigger push workflows.
    gh("workflow", "run", "sync-dev-store.yml", "--repo", repository, "--ref", "main")
    gh("workflow", "run", "validate-mcphub.yml", "--repo", repository, "--ref", "dev-mcphub")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "merge"))
    parser.add_argument("--openai", required=True)
    parser.add_argument("--cloudflare", required=True)
    parser.add_argument("--branch")
    parser.add_argument("--sha")
    args = parser.parse_args()
    if args.mode == "prepare":
        docker_path, notes_path = Path("MCPHub/Dockerfile"), Path("MCPHub/CHANGELOG.md")
        docker, notes, updated = prepare(
            docker_path.read_text(encoding="utf-8"),
            notes_path.read_text(encoding="utf-8"),
            args.openai, args.cloudflare,
        )
        if updated:
            docker_path.write_text(docker, encoding="utf-8")
            notes_path.write_text(notes, encoding="utf-8")
        print("update=true" if updated else "update=false")
    else:
        verify_and_merge(
            os.environ["GITHUB_REPOSITORY"], args.branch, args.sha,
            args.openai, args.cloudflare,
        )


if __name__ == "__main__":
    main()
