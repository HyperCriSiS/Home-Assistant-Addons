#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADDON_DIR = ROOT / "TriliumNext Notes"


def next_addon_version(current: str) -> str:
    base = f"v{dt.datetime.now(dt.timezone.utc):%Y.%m.%d}"
    if current == base:
        return f"{base}.1"
    match = re.fullmatch(re.escape(base) + r"\.(\d+)", current)
    if match:
        return f"{base}.{int(match.group(1)) + 1}"
    return base


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", required=True)
    args = parser.parse_args()

    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", args.upstream):
        raise SystemExit(f"Refusing unexpected upstream tag: {args.upstream}")

    dockerfile_path = ADDON_DIR / "Dockerfile"
    config_path = ADDON_DIR / "config.yaml"
    changelog_path = ADDON_DIR / "CHANGELOG.md"

    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    current_upstream_match = re.search(
        r"^FROM docker\.io/triliumnext/trilium:(v[^\s]+)$",
        dockerfile,
        re.MULTILINE,
    )
    if not current_upstream_match:
        raise SystemExit("Could not find the pinned Trilium image in Dockerfile")
    current_upstream = current_upstream_match.group(1)
    if current_upstream == args.upstream:
        print(f"Already on {args.upstream}")
        return

    dockerfile = dockerfile.replace(
        f"docker.io/triliumnext/trilium:{current_upstream}",
        f"docker.io/triliumnext/trilium:{args.upstream}",
        1,
    )
    dockerfile_path.write_text(dockerfile, encoding="utf-8")

    config = config_path.read_text(encoding="utf-8")
    version_match = re.search(r'^version:\s*"([^"]+)"$', config, re.MULTILINE)
    if not version_match:
        raise SystemExit("Could not find add-on version in config.yaml")
    current_addon_version = version_match.group(1)
    new_addon_version = next_addon_version(current_addon_version)
    config = config.replace(
        f'version: "{current_addon_version}"',
        f'version: "{new_addon_version}"',
        1,
    )
    config_path.write_text(config, encoding="utf-8")

    changelog = changelog_path.read_text(encoding="utf-8")
    release_url = f"https://github.com/TriliumNext/Trilium/releases/tag/{args.upstream}"
    entry = (
        f"## {new_addon_version}\n\n"
        f"- Update Trilium Notes from {current_upstream} to {args.upstream}.\n"
        f"- Upstream release notes: {release_url}\n"
        "- Automated CI verifies Home Assistant metadata, amd64/aarch64 builds, "
        "Ingress proxying, WebSockets, browser behavior, persistence, and database upgrades.\n\n"
    )
    marker = "# Changelog\n\n"
    if not changelog.startswith(marker):
        raise SystemExit("Unexpected CHANGELOG.md format")
    changelog_path.write_text(marker + entry + changelog[len(marker):], encoding="utf-8")

    print(f"Updated Trilium {current_upstream} -> {args.upstream}")
    print(f"Updated add-on {current_addon_version} -> {new_addon_version}")


if __name__ == "__main__":
    main()
