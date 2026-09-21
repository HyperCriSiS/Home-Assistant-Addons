#!/usr/bin/env python3
from __future__ import annotations

import os
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADDON_DIR = ROOT / "TriliumNext Notes"


def fail(message: str) -> None:
    raise SystemExit(message)


def main() -> None:
    config = yaml.safe_load((ADDON_DIR / "config.yaml").read_text(encoding="utf-8"))
    dockerfile = (ADDON_DIR / "Dockerfile").read_text(encoding="utf-8")
    changelog = (ADDON_DIR / "CHANGELOG.md").read_text(encoding="utf-8")

    if set(config.get("arch", [])) != {"amd64", "aarch64"}:
        fail(f"Unexpected architectures: {config.get('arch')!r}")

    if config.get("ingress") is not True or config.get("ingress_port") != 8080:
        fail("Ingress must stay enabled on port 8080")

    if config.get("watchdog") != "tcp://[HOST]:[PORT:8080]":
        fail("The Home Assistant TCP watchdog must stay enabled on port 8080")

    data_maps = [entry for entry in config.get("map", []) if isinstance(entry, dict)]
    expected_map = {
        "type": "data",
        "read_only": False,
        "path": "/home/node/trilium-data",
    }
    if expected_map not in data_maps:
        fail("Persistent Home Assistant data mapping is missing or changed")

    environment = config.get("environment", {})
    trusted_proxy = environment.get("TRILIUM_NETWORK_TRUSTEDREVERSEPROXY")
    if trusted_proxy != "172.30.32.2":
        fail(
            "TRILIUM_NETWORK_TRUSTEDREVERSEPROXY must trust only the Home Assistant "
            "Ingress proxy at 172.30.32.2"
        )

    if environment.get("TRILIUM_DATA_DIR") != "/home/node/trilium-data":
        fail("TRILIUM_DATA_DIR must match the persistent Home Assistant data mapping")

    version = str(config["version"])
    if not changelog.startswith(f"# Changelog\n\n## {version}\n"):
        fail("The first changelog entry must match config.yaml version")

    match = re.search(
        r"^FROM docker\.io/triliumnext/trilium:(v[^\s]+)$",
        dockerfile,
        re.MULTILINE,
    )
    if not match:
        fail("Dockerfile must pin a versioned Trilium image")

    upstream_version = match.group(1)
    if upstream_version in {"latest", "nightly"}:
        fail("Dockerfile must never use a floating Trilium tag")

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"addon_version={version}\n")
            handle.write(f"upstream_version={upstream_version}\n")

    print(f"Add-on version: {version}")
    print(f"Upstream version: {upstream_version}")
    print("Metadata validation passed")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, TypeError, yaml.YAMLError) as err:
        print(f"Metadata validation failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err
