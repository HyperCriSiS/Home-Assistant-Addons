#!/usr/bin/env python3
"""Generate local Nginx adapters without exposing MCPHub directly."""

from __future__ import annotations

import json
import re
from pathlib import Path


OPTIONS_FILE = Path("/data/options.json")
TEMPLATE_FILE = Path("/etc/nginx/mcphub.conf.template")
OUTPUT_FILE = Path("/etc/nginx/conf.d/mcphub.conf")

HA_INGRESS_PROXY_SECRET_FILE = Path("/data/secrets/mcphub_ha_ingress_proxy_secret")
CLOUDFLARE_INTERNAL_TOKEN_FILE = Path("/data/secrets/mcphub_cloudflare_token")

MCP_PATH_PATTERN = re.compile(r"^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$")
ACCESS_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{32,256}$")


def load_options() -> dict:
    """Load Home Assistant App options."""
    with OPTIONS_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError("options.json must contain a JSON object")

    return data


def read_secret(path: Path) -> str:
    """Read one generated runtime secret."""
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Secret file is empty: {path}")
    return value


def cloudflare_server_block(
    *,
    enabled: bool,
    mcp_path: str,
    client_token: str,
    internal_token: str,
) -> str:
    """Build the loopback-only Cloudflare origin with an exact MCP route."""
    if not enabled:
        return """server {
    listen 127.0.0.1:8098;
    access_log off;

    location / {
        return 404;
    }
}"""

    if not MCP_PATH_PATTERN.fullmatch(mcp_path):
        raise ValueError(
            "cloudflare_mcp_path must be /mcp or contain at most two safe path segments"
        )

    if not ACCESS_TOKEN_PATTERN.fullmatch(client_token):
        raise ValueError(
            "cloudflare_access_token must contain 32-256 letters, numbers, underscores, or dashes"
        )

    # Escape '$' so Nginx treats Smart Routing paths literally, not as variables.
    location_pattern = re.escape(mcp_path)

    return f"""server {{
    listen 127.0.0.1:8098;

    access_log /dev/stdout;
    error_log /dev/stderr warn;

    client_max_body_size 16m;

    # Only the configured MCP route is reachable through Cloudflare.
    location ~ ^{location_pattern}$ {{
        if ($http_authorization != "Bearer {client_token}") {{
            return 401;
        }}

        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;

        # The public client token is validated here and is never registered in
        # MCPHub. MCPHub receives a separate private, route-scoped key instead.
        proxy_set_header Authorization "Bearer {internal_token}";
        proxy_set_header X-MCPHub-HA-Proxy-Secret "";
        proxy_set_header X-Remote-User-Id "";
        proxy_set_header X-Remote-User-Name "";
        proxy_set_header X-Remote-User-Display-Name "";

        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}

    location / {{
        return 404;
    }}
}}"""


def main() -> None:
    options = load_options()
    template = TEMPLATE_FILE.read_text(encoding="utf-8")

    ha_ingress_proxy_secret = read_secret(HA_INGRESS_PROXY_SECRET_FILE)
    cloudflare_internal_token = read_secret(CLOUDFLARE_INTERNAL_TOKEN_FILE)

    cloudflare_block = cloudflare_server_block(
        enabled=bool(options.get("cloudflare_tunnel_enabled", False)),
        mcp_path=str(options.get("cloudflare_mcp_path", "/mcp")),
        client_token=str(options.get("cloudflare_access_token", "")),
        internal_token=cloudflare_internal_token,
    )

    rendered = template.replace(
        "__HA_INGRESS_PROXY_SECRET__",
        ha_ingress_proxy_secret,
    ).replace(
        "__CLOUDFLARE_SERVER_BLOCK__",
        cloudflare_block,
    )

    OUTPUT_FILE.write_text(rendered, encoding="utf-8")
    OUTPUT_FILE.chmod(0o600)


if __name__ == "__main__":
    main()
