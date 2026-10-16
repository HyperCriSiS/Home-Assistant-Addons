#!/usr/bin/env python3
"""MCPHub development and stable changelog from Git commit history.

The source changelog remains human-curated; development iteration details are
only generated in the combined dev-store. No source branch is modified by dev.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

APP = "MCPHub"
CHANGELOG = Path(APP) / "CHANGELOG.md"
HISTORY = Path(".dev-store-mcphub-changes.json")
STATE = Path(".dev-store-revisions.json")
RELATED = (
    "MCPHub",
    ".github/workflows/validate-mcphub.yml",
    ".github/workflows/haos-mcphub.yml",
    ".github/workflows/sync-dev-store.yml",
    ".github/workflows/promote.yml",
    ".github/scripts/haos-e2e-mcphub.sh",
    ".github/scripts/haos-qemu-mcphub.sh",
    ".github/workflows/haos-qemu-mcphub.yml",
    ".github/scripts/integration-test-mcphub.sh",
    ".github/scripts/update-mcphub-upstream.py",
    ".github/scripts/generate-mcphub-changelog.py",
)
BEGIN = "<!-- MCPHUB STABLE AUDIT BEGIN -->"
END = "<!-- MCPHUB STABLE AUDIT END -->"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def commits(previous: str, current: str) -> list[dict[str, str]]:
    output = git(
        "log", "--full-history", "--format=%H%x1f%s%x1e",
        f"{previous}..{current}", "--", *RELATED,
    )
    entries = []
    for entry in output.split("\x1e"):
        entry = entry.strip()
        if not entry:
            continue
        sha, sep, subject = entry.partition("\x1f")
        if not sep:
            raise ValueError("Unexpected git log entry")
        entries.append({"sha": sha.strip(), "subject": subject.strip()})
    return entries


def escape_md(value: str) -> str:
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")


def commit_notes(entries: list[dict[str, str]], repository: str) -> str:
    if not entries:
        return "- No MCPHub-related commits in this range.\n"
    lines = []
    for entry in entries:
        sha, subject = entry["sha"], escape_md(entry["subject"])
        lines.append(f"- [\u0060{sha[:7]}\u0060](https://github.com/{repository}/commit/{sha}) {subject}")
    return "\n".join(lines) + "\n"


def version_from_yaml(content: str) -> str:
    match = re.search(r'^version:\s*["\']?([^"\'\n]+)', content, re.M)
    if not match:
        raise ValueError("Missing version in config.yaml")
    return match.group(1).strip()


def stable_version() -> str:
    return version_from_yaml(git("show", "origin/main:MCPHub/config.yaml"))


def audit(base: str, head: str, repository: str, title: str) -> str:
    return (
        f"### {title}\n\n"
        f"Source: \u0060{base}\u0060 to \u0060{head}\u0060; all MCPHub-related commits "
        "are listed below. Human-written release notes follow.\n\n"
        "#### Commits\n\n" + commit_notes(commits(base, head), repository) + "\n"
    )


def dev(repository: str) -> None:
    state = json.loads(STATE.read_text(encoding="utf-8"))["mcphub"]
    revision = int(state["revision"])
    version = version_from_yaml(Path(APP, "config.yaml").read_text(encoding="utf-8"))
    expected = f"-dev.{revision}"
    if not version.endswith(expected):
        raise ValueError(f"Development version {version!r} does not match revision {revision}")
    source_sha = git("rev-parse", "origin/dev-mcphub")
    previous = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    if not isinstance(previous, list):
        raise ValueError("Development changelog history must be an array")
    if previous and previous[0]["revision"] > revision:
        raise ValueError("Development revision moved backwards; refusing to drop history")
    if not previous or previous[0]["revision"] < revision:
        prior_sha = previous[0]["source_sha"] if previous else None
        if prior_sha:
            git("merge-base", "--is-ancestor", prior_sha, source_sha)
        previous.insert(0, {
            "revision": revision,
            "version": version,
            "source_sha": source_sha,
            "baseline": not bool(prior_sha),
            "commits": commits(prior_sha, source_sha) if prior_sha else [],
        })
    HISTORY.write_text(json.dumps(previous, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Only show commits belonging to the current dev-store revision.
    # The JSON history is retained for calculating iteration boundaries, but
    # neither earlier builds nor the stable-release audit belong in this view.
    latest = previous[0]
    head = f"# Changelog\n\n## {version}\n\n### Commits in this Dev build\n\n"
    if latest["baseline"]:
        head += "- Initial development snapshot (no previous Dev build recorded).\n"
    else:
        head += commit_notes(latest["commits"], repository)
    CHANGELOG.write_text(head, encoding="utf-8")


def stable(repository: str, check: bool = False) -> None:
    source = CHANGELOG.read_text(encoding="utf-8")
    current = version_from_yaml(Path(APP, "config.yaml").read_text(encoding="utf-8"))
    expected = f"# Changelog\n\n## {current}\n\n"
    if not source.startswith(expected):
        raise ValueError("Stable candidate's first changelog header does not match its version")
    start = source.find(BEGIN)
    end = source.find(END)
    if start >= 0 or end >= 0:
        if start < 0 or end < start:
            raise ValueError("Inconsistent stable audit markers")
        source = source[:start] + source[end + len(END):].lstrip("\n")
    section = (
        BEGIN + "\n\n" + audit("origin/main", "origin/dev-mcphub", repository,
                                  f"Complete changes since stable {stable_version()}")
        + END + "\n\n"
    )
    generated = expected + section + source[len(expected):]
    if check:
        if generated != CHANGELOG.read_text(encoding="utf-8"):
            raise SystemExit("Stable candidate is missing the complete automated changelog; generate it before merging")
    else:
        CHANGELOG.write_text(generated, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("dev", "stable"))
    parser.add_argument("--repository", default="HyperCriSiS/Home-Assistant-Apps")
    parser.add_argument("--check", action="store_true", help="Fail if stable digest is missing/outdated")
    options = parser.parse_args()
    if options.mode == "dev":
        dev(options.repository)
    else:
        stable(options.repository, options.check)


if __name__ == "__main__":
    main()
