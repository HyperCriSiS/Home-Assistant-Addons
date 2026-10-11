#!/usr/bin/env python3
"""Prepare a reviewed MCPHub upstream-version bump for the Home Assistant wrapper."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def replace_exact(
    path: str,
    old: str,
    new: str,
    expected: int | None = None,
) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if expected is not None and count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrences of {old!r}, found {count}"
        )
    if count == 0:
        raise SystemExit(f"{path}: did not find {old!r}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def read_current_upstream() -> str:
    text = (ROOT / "MCPHub/build.yaml").read_text(encoding="utf-8")
    versions = set(re.findall(r"samanhappy/mcphub:(\d+\.\d+\.\d+)", text))
    if len(versions) != 1:
        raise SystemExit(
            f"Expected one packaged MCPHub version, found {sorted(versions)}"
        )
    return versions.pop()


def bump_wrapper_version(today: date) -> tuple[str, str]:
    path = ROOT / "MCPHub/config.yaml"
    text = path.read_text(encoding="utf-8")
    pattern = (
        r'^version:\s*"?(v(\d{4})\.(\d{2})\.(\d{2})'
        r'(?:-([1-9]\d*))?)"?\s*$'
    )
    match = re.search(pattern, text, re.MULTILINE)
    if not match:
        raise SystemExit("Unable to parse MCPHub wrapper version")

    old = match.group(1)
    current_date = date(
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
    )
    suffix = int(match.group(5) or "0")

    if today > current_date:
        new = f"v{today:%Y.%m.%d}"
    else:
        new = f"v{current_date:%Y.%m.%d}-{suffix + 1}"

    updated = text[: match.start(1)] + new + text[match.end(1) :]
    path.write_text(updated, encoding="utf-8")
    return old, new


def prepend_changelog(
    version: str,
    upstream_old: str,
    upstream_new: str,
    release_url: str,
    today: date,
) -> None:
    path = ROOT / "MCPHub/CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    heading = "# Changelog\n\n"
    if not text.startswith(heading):
        raise SystemExit("Unexpected MCPHub changelog header")

    entry = (
        f"## [{version}] - {today.isoformat()}\n\n"
        "### Changed\n\n"
        f"- Updated bundled MCPHub from {upstream_old} to {upstream_new}. "
        f"Upstream release: {release_url}\n\n"
    )
    path.write_text(
        heading + entry + text[len(heading) :],
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--version",
        required=True,
        help="Stable upstream version without leading v",
    )
    parser.add_argument("--release-url", required=True)
    parser.add_argument(
        "--date",
        help="UTC date YYYY-MM-DD; defaults to today",
    )
    args = parser.parse_args()

    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        raise SystemExit(f"Invalid MCPHub version: {args.version}")

    today = date.fromisoformat(args.date) if args.date else date.today()
    current = read_current_upstream()
    if current == args.version:
        print(f"MCPHub {args.version} is already packaged")
        return

    replace_exact(
        "MCPHub/build.yaml",
        f"samanhappy/mcphub:{current}",
        f"samanhappy/mcphub:{args.version}",
        2,
    )
    replace_exact(
        "MCPHub/Dockerfile",
        f"samanhappy/mcphub:{current}",
        f"samanhappy/mcphub:{args.version}",
        1,
    )
    replace_exact(
        "MCPHub/Dockerfile",
        f"# MCPHub {current} listens",
        f"# MCPHub {args.version} listens",
        1,
    )
    replace_exact(
        "MCPHub/run.sh",
        f"Starting MCPHub {current} on",
        f"Starting MCPHub {args.version} on",
        1,
    )
    replace_exact(
        "MCPHub/ingress.conf",
        f'\\\"version\\\":\\\"{current}\\\"',
        f'\\\"version\\\":\\\"{args.version}\\\"',
        1,
    )
    replace_exact(
        "MCPHub/NOTICE.md",
        f"Version currently packaged: {current}",
        f"Version currently packaged: {args.version}",
        1,
    )
    replace_exact(
        "MCPHub/patch_home_assistant_auth.py",
        f"MCPHub {current}",
        f"MCPHub {args.version}",
        2,
    )
    replace_exact(
        ".github/workflows/validate-mcphub.yml",
        f"samanhappy/mcphub:{current}",
        f"samanhappy/mcphub:{args.version}",
        2,
    )

    _, wrapper = bump_wrapper_version(today)
    prepend_changelog(
        wrapper,
        current,
        args.version,
        args.release_url,
        today,
    )
    print(
        f"Prepared MCPHub {current} -> {args.version} "
        f"as wrapper {wrapper}"
    )


if __name__ == "__main__":
    main()
