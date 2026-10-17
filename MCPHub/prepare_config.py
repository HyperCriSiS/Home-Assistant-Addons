#!/usr/bin/env python3
"""Prepare persistent MCPHub configuration for Home Assistant."""

from __future__ import annotations

import json
import os
import re
import secrets
import sys
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
CLOUDFLARE_CLIENT_KEY_FILE = SECRET_DIR / "mcphub_cloudflare_client_key"
TAILSCALE_INTERNAL_TOKEN_FILE = SECRET_DIR / "mcphub_tailscale_funnel_token"
TAILSCALE_CLIENT_KEY_FILE = SECRET_DIR / "mcphub_tailscale_client_key"
GITHUB_TOKEN_FILE = SECRET_DIR / "github_token"

OPENAI_KEY_NAME = "Home Assistant OpenAI Tunnel"
INGRESS_KEY_NAME = "Home Assistant Ingress"
CLOUDFLARE_KEY_NAME = "Home Assistant Cloudflare Tunnel"
TAILSCALE_KEY_NAME = "Home Assistant Tailscale MCP Gateway"
GITHUB_CLI_SERVER_NAME = "ha-github-cli"
HOME_ASSISTANT_MCP_DEFAULT_NAME = "ha-home-assistant"
HOME_ASSISTANT_MCP_DESCRIPTION = (
    "Home Assistant MCP Server managed by the Home Assistant MCPHub App wrapper"
)
MANAGED_HOME_ASSISTANT_NAME_FILE = DATA_DIR / ".managed_home_assistant_mcp_name"
HOME_ASSISTANT_MCP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

MCP_PATH_PATTERN = re.compile(r"^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$")


def ensure_secret(path: Path, factory) -> str:
    """Create a secret once and keep it with restrictive file permissions."""
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            os.chmod(path, 0o600)
            return value

    value = factory()
    # Always write secrets with 0600 from creation; avoid world-readable windows.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(value)
    os.chmod(path, 0o600)
    return value


def flatten_grouped_options(data: dict) -> dict:
    """Read legacy flat and grouped options."""
    result = dict(data)
    for group in ("openai", "cloudflare", "tailscale", "home_assistant", "github", "logging"):
        section = data.get(group)
        if isinstance(section, dict):
            result.update(section)
    return result


def load_options() -> dict:
    """Load Home Assistant App options."""
    if not OPTIONS_FILE.exists():
        return {}

    with OPTIONS_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError("options.json must contain a JSON object")

    return flatten_grouped_options(data)


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


def valid_mcp_path(path: str) -> bool:
    return (bool(MCP_PATH_PATTERN.fullmatch(path))
            and all(part not in (".", "..") for part in path.split("/")[2:]))


def scope_for_path(path: str) -> tuple[str, list[str], list[str]]:
    """Return the narrowest MCPHub system-key scope that can serve a route."""
    if not valid_mcp_path(path):
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


def is_managed_home_assistant_server(server: object) -> bool:
    """Only entries with our exact managed proxy identity may be removed."""
    return (
        isinstance(server, dict)
        and server.get("url") == "http://127.0.0.1:8097/mcp"
        and server.get("description") == HOME_ASSISTANT_MCP_DESCRIPTION
    )


def previous_managed_home_assistant_name(mcp_servers: dict) -> str | None:
    """Find the previously managed entry, including pre-rename installations."""
    if MANAGED_HOME_ASSISTANT_NAME_FILE.exists():
        name = MANAGED_HOME_ASSISTANT_NAME_FILE.read_text(
            encoding="utf-8"
        ).strip()
        if not HOME_ASSISTANT_MCP_NAME_PATTERN.fullmatch(name):
            raise ValueError("Stored managed Home Assistant MCP name is invalid")
        return name if is_managed_home_assistant_server(mcp_servers.get(name)) else None

    legacy = mcp_servers.get(HOME_ASSISTANT_MCP_DEFAULT_NAME)
    if is_managed_home_assistant_server(legacy):
        return HOME_ASSISTANT_MCP_DEFAULT_NAME
    return None


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRET_DIR, 0o700)

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
    # Existing manually configured client keys must remain valid across an App upgrade.
    # New installs get a locally generated 384-bit secret; no Cloudflare Access account.
    legacy_client_key = str(options.get("cloudflare_access_token") or "").strip()
    if legacy_client_key and not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", legacy_client_key):
        print("[WARN] Invalid legacy Cloudflare client key; creating a new key", file=sys.stderr)
        legacy_client_key = ""
    ensure_secret(
        CLOUDFLARE_CLIENT_KEY_FILE,
        lambda: legacy_client_key or secrets.token_urlsafe(48),
    )
    cloudflare_internal_token = ensure_secret(
        CLOUDFLARE_INTERNAL_TOKEN_FILE,
        lambda: "mcf_" + secrets.token_urlsafe(48),
    )
    # Separate external and internal Tailscale keys; never share a Cloudflare key.
    ensure_secret(TAILSCALE_CLIENT_KEY_FILE, lambda: secrets.token_urlsafe(48))
    tailscale_internal_token = ensure_secret(
        TAILSCALE_INTERNAL_TOKEN_FILE,
        lambda: "mts_" + secrets.token_urlsafe(48),
    )

    OPENAI_AUTH_FILE.write_text(f"Bearer {openai_token}", encoding="utf-8")
    os.chmod(OPENAI_AUTH_FILE, 0o600)

    settings = load_settings()

    settings.setdefault("mcpServers", {})
    settings.setdefault("users", [])
    settings.setdefault("prompts", [])
    settings.setdefault("resources", [])

    system_config = settings.setdefault("systemConfig", {})
    routing = system_config.setdefault("routing", {})

    routing["skipAuth"] = False
    routing["enableBearerAuth"] = True
    routing["bearerAuthHeaderName"] = "Authorization"

    bearer_keys = settings.setdefault("bearerKeys", [])
    if not isinstance(bearer_keys, list):
        raise ValueError("bearerKeys must be a JSON list")

    bearer_keys[:] = [
        item for item in bearer_keys
        if item.get("name") != INGRESS_KEY_NAME
    ]

    for label, enabled_flag, path_option, key_name, token in (
        ("OpenAI", "tunnel_enabled", "tunnel_mcp_path", OPENAI_KEY_NAME, openai_token),
        ("Cloudflare", "cloudflare_tunnel_enabled", "cloudflare_mcp_path",
         CLOUDFLARE_KEY_NAME, cloudflare_internal_token),
        ("Tailscale", "tailscale_funnel_enabled", "tailscale_mcp_path",
         TAILSCALE_KEY_NAME, tailscale_internal_token),
    ):
        bearer_keys[:] = [item for item in bearer_keys if item.get("name") != key_name]
        if not bool(options.get(enabled_flag, False)):
            continue
        route = str(options.get(path_option, "/mcp"))
        try:
            access_type, groups, servers = scope_for_path(route)
        except ValueError:
            print(
                f"[WARN] {label} tunnel MCP path invalid; bearer key remains disabled",
                file=sys.stderr,
            )
            continue
        upsert_system_key(
            bearer_keys,
            name=key_name,
            token=token,
            access_type=access_type,
            allowed_groups=groups,
            allowed_servers=servers,
        )

    mcp_servers = settings["mcpServers"]
    if not isinstance(mcp_servers, dict):
        raise ValueError("mcpServers must be a JSON object")

    home_assistant_mcp_enabled = bool(
        options.get("home_assistant_mcp_enabled", False)
    )
    previous_name = previous_managed_home_assistant_name(mcp_servers)

    if home_assistant_mcp_enabled:
        name = str(
            options.get(
                "home_assistant_mcp_server_name",
                HOME_ASSISTANT_MCP_DEFAULT_NAME,
            )
        ).strip()
        if (
            not HOME_ASSISTANT_MCP_NAME_PATTERN.fullmatch(name)
            or name == GITHUB_CLI_SERVER_NAME
        ):
            raise ValueError(
                "home_assistant_mcp_server_name must be a unique 1-64 character "
                "name using letters, digits, dots, underscores, or hyphens "
                "(and must not equal ha-github-cli)"
            )
        if name in mcp_servers and name != previous_name:
            raise ValueError(
                f"Cannot use Home Assistant MCP server name {name!r}: "
                "an existing non-managed server uses this name"
            )
        if previous_name and previous_name != name:
            mcp_servers.pop(previous_name, None)

        mcp_servers[name] = {
            "type": "streamable-http",
            "url": "http://127.0.0.1:8097/mcp",
            "enabled": True,
            "enableKeepAlive": True,
            "keepAliveInterval": 5000,
            "owner": "admin",
            "description": HOME_ASSISTANT_MCP_DESCRIPTION,
        }
    elif previous_name:
        mcp_servers.pop(previous_name, None)

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
        # An empty option after an App schema migration must never destroy a
        # previously persisted credential. Explicit revocation is a separate action.
    else:
        mcp_servers.pop(GITHUB_CLI_SERVER_NAME, None)
        # Keep saved credentials across disable/enable and schema migrations.

    temporary = SETTINGS_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    os.chmod(temporary, 0o600)
    temporary.replace(SETTINGS_FILE)
    os.chmod(SETTINGS_FILE, 0o600)

    if home_assistant_mcp_enabled:
        name_tmp = MANAGED_HOME_ASSISTANT_NAME_FILE.with_suffix(".tmp")
        name_tmp.write_text(name + "\n", encoding="utf-8")
        os.chmod(name_tmp, 0o600)
        name_tmp.replace(MANAGED_HOME_ASSISTANT_NAME_FILE)
    else:
        MANAGED_HOME_ASSISTANT_NAME_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
