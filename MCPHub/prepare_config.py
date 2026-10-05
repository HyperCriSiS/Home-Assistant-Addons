#!/usr/bin/env python3
"""Prepare persistent MCPHub configuration for Home Assistant."""

from __future__ import annotations

import json
import os
import secrets
import uuid
from pathlib import Path


DATA_DIR = Path("/data/mcphub")
SECRET_DIR = Path("/data/secrets")
SETTINGS_FILE = DATA_DIR / "mcp_settings.json"
JWT_SECRET_FILE = SECRET_DIR / "mcphub_jwt_secret"
TUNNEL_TOKEN_FILE = SECRET_DIR / "mcphub_tunnel_token"
TUNNEL_AUTH_FILE = SECRET_DIR / "mcphub_tunnel_authorization"
INTERNAL_KEY_NAME = "Home Assistant OpenAI Tunnel"


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


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SECRET_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SECRET_DIR, 0o700)

    ensure_secret(JWT_SECRET_FILE, lambda: secrets.token_hex(32))
    tunnel_token = ensure_secret(
        TUNNEL_TOKEN_FILE,
        lambda: "mch_" + secrets.token_urlsafe(48),
    )

    # The tunnel client expects the complete static Authorization header value.
    TUNNEL_AUTH_FILE.write_text(f"Bearer {tunnel_token}", encoding="utf-8")
    os.chmod(TUNNEL_AUTH_FILE, 0o600)

    settings = load_settings()

    settings.setdefault("mcpServers", {})
    settings.setdefault("users", [])
    settings.setdefault("prompts", [])
    settings.setdefault("resources", [])

    system_config = settings.setdefault("systemConfig", {})
    routing = system_config.setdefault("routing", {})

    # Home Assistant Ingress protects the dashboard. MCP transport authentication
    # remains enabled independently through a dedicated bearer key.
    routing["skipAuth"] = True
    routing["enableBearerAuth"] = True
    routing["bearerAuthHeaderName"] = "Authorization"

    bearer_keys = settings.setdefault("bearerKeys", [])
    if not isinstance(bearer_keys, list):
        raise ValueError("bearerKeys must be a JSON list")

    internal_key = next(
        (item for item in bearer_keys if item.get("name") == INTERNAL_KEY_NAME),
        None,
    )

    if internal_key is None:
        bearer_keys.append(
            {
                "id": str(uuid.uuid4()),
                "name": INTERNAL_KEY_NAME,
                "token": tunnel_token,
                "enabled": True,
                "kind": "system",
                "accessType": "all",
                "allowedGroups": [],
                "allowedServers": [],
            }
        )
    else:
        # Reconcile the internal key with the persistent secret on every start.
        internal_key["token"] = tunnel_token
        internal_key["enabled"] = True
        internal_key["kind"] = "system"
        internal_key["accessType"] = "all"
        internal_key["allowedGroups"] = []
        internal_key["allowedServers"] = []

    temporary = SETTINGS_FILE.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    os.chmod(temporary, 0o600)
    temporary.replace(SETTINGS_FILE)
    os.chmod(SETTINGS_FILE, 0o600)


if __name__ == "__main__":
    main()
