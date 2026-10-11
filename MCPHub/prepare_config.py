#!/usr/bin/env python3
"""Prepare persistent MCPHub configuration for Home Assistant."""

from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from pathlib import Path


DATA_DIR = Path("/data/mcphub")
SECRET_DIR = Path("/data/secrets")
OPTIONS_FILE = Path("/data/options.json")
SETTINGS_FILE = DATA_DIR / "mcp_settings.json"

JWT_SECRET_FILE = SECRET_DIR / "mcphub_jwt_secret"
OPENAI_TOKEN_FILE = SECRET_DIR / "mcphub_tunnel_token"
OPENAI_AUTH_FILE = SECRET_DIR / "mcphub_tunnel_authorization"
HA_INGRESS_PROXY_SECRET_FILE = SECRET_DIR / "mcphub_ha_ingress_proxy_secret"
LEGACY_INGRESS_TOKEN_FILE = SECRET_DIR / "mcphub_ingress_token"
CLOUDFLARE_INTERNAL_TOKEN_FILE = SECRET_DIR / "mcphub_cloudflare_token"
GITHUB_TOKEN_FILE = SECRET_DIR / "github_token"

OPENAI_KEY_NAME = "Home Assistant OpenAI Tunnel"
INGRESS_KEY_NAME = "Home Assistant Ingress"
CLOUDFLARE_KEY_NAME = "Home Assistant Cloudflare Tunnel"
GITHUB_CLI_SERVER_NAME = "ha-github-cli"

MCP_PATH_PATTERN = re.compile(r"^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$")


def ensure_secret(path: Path, factory) -> str:
    """Create a secret once and keep it with restrictive file permissions."""
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value

    value = factory()
    path.write_text(value, encoding="utf-8")
    os.chmod(path, 0o600)
    return value


def load_options() -> dict:
    """Load Home Assistant App options."""
    if not OPTIONS_FILE.exists():
        return {}

    with OPTIONS_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError("options.json must contain a JSON object")

    return data


def load_settings() -> dict:
    """Load existing MCPHub settings or create a minimal settings structure."""
    if not SETTINGS_FILE.exists():
        return {
            "mcpServers": {},
            "users": [],
            "systemConfig": {},
            "bearerKeys": [],
            "prompts": [],
            "resources": [],
        }

    with SETTINGS_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError("mcp_settings.json must contain a JSON object")

    return data


def scope_for_path(path: str) -> tuple[str, list[str], list[str]]:
    """Return the narrowest MCPHub system-key scope that can serve a route."""
    if not MCP_PATH_PATTERN.fullmatch(path):
        raise ValueError(
            "MCP route must be /mcp or contain at most two safe path segments"
        )

    if path in {"/mcp", "/mcp/$smart"}:
        return "all", [], []

    if path.startswith("/mcp/$smart/"):
        group = path.removeprefix("/mcp/$smart/")
        return "groups", [group], []

    target = path.removeprefix("/mcp/")
    return "custom", [target], [target]


def upsert_system_key(
    bearer_keys: list[dict],
    *,
    name: str,
    token: str,
    access_type: str,
    allowed_groups: list[str],
    allowed_servers: list[str],
) -> None:
    """Create or reconcile one operator-managed MCPHub bearer key."""
    item = next(
        (entry for entry in bearer_keys if entry.get("name") == name),
        None,
    )

    values = {
        "name": name,
        "token": token,
        "enabled": True,
        "kind": "system",
        "accessType": access_type,
        "allowedGroups": allowed_groups,
        "allowedServers": allowed_servers,
    }

    if item is None:
        bearer_keys.append({"id": str(uuid.uuid4()), **values})
        return

    item.update(values)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRET_DIR, 0o700)

    # The old shared Ingress bearer credential is no longer used after HA SSO.
    if LEGACY_INGRESS_TOKEN_FILE.exists():
        LEGACY_INGRESS_TOKEN_FILE.unlink()

    options = load_options()

    ensure_secret(JWT_SECRET_FILE, lambda: secrets.token_hex(32))
    openai_token = ensure_secret(
        OPENAI_TOKEN_FILE,
        lambda: "mch_" + secrets.token_urlsafe(48),
    )
    ensure_secret(
        HA_INGRESS_PROXY_SECRET_FILE,
        lambda: "mha_" + secrets.token_urlsafe(48),
    )
    cloudflare_internal_token = ensure_secret(
        CLOUDFLARE_INTERNAL_TOKEN_FILE,
        lambda: "mcf_" + secrets.token_urlsafe(48),
    )

    # OpenAI tunnel-client accepts a complete static Authorization value by file.
    OPENAI_AUTH_FILE.write_text(f"Bearer {openai_token}", encoding="utf-8")
    os.chmod(OPENAI_AUTH_FILE, 0o600)

    settings = load_settings()

    settings.setdefault("mcpServers", {})
    settings.setdefault("users", [])
    settings.setdefault("prompts", [])
    settings.setdefault("resources", [])

    system_config = settings.setdefault("systemConfig", {})
    routing = system_config.setdefault("routing", {})

    # Dashboard/API access is no longer unauthenticated. Home Assistant Ingress
    # receives a dedicated internal key through the local Nginx adapter.
    routing["skipAuth"] = False
    routing["enableBearerAuth"] = True
    routing["bearerAuthHeaderName"] = "Authorization"

    bearer_keys = settings.setdefault("bearerKeys", [])
    if not isinstance(bearer_keys, list):
        raise ValueError("bearerKeys must be a JSON list")

    # Home Assistant Ingress authenticates dashboard users through Supervisor-provided
    # identity headers. Remove the legacy shared Ingress bearer key if it exists.
    bearer_keys[:] = [
        item for item in bearer_keys
        if item.get("name") != INGRESS_KEY_NAME
    ]

    openai_path = str(options.get("tunnel_mcp_path", "/mcp"))
    openai_scope = scope_for_path(openai_path)
    upsert_system_key(
        bearer_keys,
        name=OPENAI_KEY_NAME,
        token=openai_token,
        access_type=openai_scope[0],
        allowed_groups=openai_scope[1],
        allowed_servers=openai_scope[2],
    )

    cloudflare_path = str(options.get("cloudflare_mcp_path", "/mcp"))
    cloudflare_scope = scope_for_path(cloudflare_path)
    upsert_system_key(
        bearer_keys,
        name=CLOUDFLARE_KEY_NAME,
        token=cloudflare_internal_token,
        access_type=cloudflare_scope[0],
        allowed_groups=cloudflare_scope[1],
        allowed_servers=cloudflare_scope[2],
    )

    mcp_servers = settings["mcpServers"]
    if not isinstance(mcp_servers, dict):
        raise ValueError("mcpServers must be a JSON object")

    github_cli_enabled = bool(options.get("github_cli_mcp_enabled", False))
    github_token = str(options.get("github_token", "")).strip()
    if github_cli_enabled:
        mcp_servers[GITHUB_CLI_SERVER_NAME] = {
            "command": "/usr/local/bin/github_cli_mcp.sh",
            "args": [],
        }
        if github_token:
            GITHUB_TOKEN_FILE.write_text(github_token, encoding="utf-8")
            os.chmod(GITHUB_TOKEN_FILE, 0o600)
        elif GITHUB_TOKEN_FILE.exists():
            GITHUB_TOKEN_FILE.unlink()
    else:
        # This key is reserved for the Home Assistant managed integration.
        # User-created GitHub MCP servers under other names are untouched.
        mcp_servers.pop(GITHUB_CLI_SERVER_NAME, None)
        if GITHUB_TOKEN_FILE.exists():
            GITHUB_TOKEN_FILE.unlink()

    temporary = SETTINGS_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    os.chmod(temporary, 0o600)
    temporary.replace(SETTINGS_FILE)
    os.chmod(SETTINGS_FILE, 0o600)


if __name__ == "__main__":
    main()
