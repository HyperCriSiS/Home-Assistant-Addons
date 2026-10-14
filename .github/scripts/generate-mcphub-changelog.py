#!/usr/bin/env python3
"""Exhaustive MCPHub development and stable changelog from Git history.

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


def files_changed(previous: str, current: str) -> list[str]:
    result = git("diff", "--no-renames", "--name-status", previous, current, "--", *RELATED)
    return [line for line in result.splitlines() if line.strip()]


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


def file_notes(changes: list[str]) -> str:
    if not changes:
        return "- No MCPHub-related file changes in this range.\n"
    notes = []
    for line in changes:
        status, _, filename = line.partition("\t")
        if not filename:
            raise ValueError(f"Unexpected Git name-status line: {line!r}")
        notes.append(f"- {status}: \u0060{escape_md(filename)}\u0060")
    return "\n".join(notes) + "\n"


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
        "and changed files are listed below. Human-written release notes follow.\n\n"
        "#### Commits\n\n" + commit_notes(commits(base, head), repository) +
        "\n#### Changed files\n\n" + file_notes(files_changed(base, head)) + "\n"
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
            "files": files_changed(prior_sha, source_sha) if prior_sha else [],
        })
    HISTORY.write_text(json.dumps(previous, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Read only the curated source, never a generated dev-store changelog.
    source = subprocess.check_output(
        ["git", "show", "origin/dev-mcphub:MCPHub/CHANGELOG.md"], text=True
    )
    prefix = "# Changelog\n\n"
    if not source.startswith(prefix):
        raise ValueError("Unexpected source changelog header")
    stable = stable_version()
    latest = previous[0]
    head = (
        f"# Changelog\n\n## {version}\n\n"
        "Development build. This section is generated from the actual Git history; "
        "individual iteration changes are preserved below.\n\n"
        f"### Complete changes since stable {stable}\n\n"
        + audit("origin/main", "origin/dev-mcphub", repository,
                "MCPHub changes awaiting stable release")
        + "### This iteration\n\n"
    )
    if latest["baseline"]:
        head += ("- Baseline at the start of automatic per-iteration tracking. "
                 "Earlier development changes are itemized in the cumulative comparison above.\n\n")
    else:
        head += "#### Commits\n\n" + commit_notes(latest["commits"], repository)
        head += "\n#### Changed files\n\n" + file_notes(latest["files"]) + "\n"
    for old in previous[1:]:
        head += f"## {old['version']}\n\n"
        if old["baseline"]:
            head += "- Tracking baseline; see the cumulative history in the latest development entry.\n\n"
        else:
            head += "### Changes in this iteration\n\n"
            head += "#### Commits\n\n" + commit_notes(old["commits"], repository)
            head += "\n#### Changed files\n\n" + file_notes(old["files"]) + "\n"
    CHANGELOG.write_text(head + source[len(prefix):], encoding="utf-8")


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