#!/usr/bin/env python3
"""Generate local Nginx adapters without exposing MCPHub directly."""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


OPTIONS_FILE = Path("/data/options.json")
TEMPLATE_FILE = Path("/etc/nginx/mcphub.conf.template")
OUTPUT_FILE = Path("/etc/nginx/conf.d/mcphub.conf")

HA_INGRESS_PROXY_SECRET_FILE = Path("/data/secrets/mcphub_ha_ingress_proxy_secret")
CLOUDFLARE_INTERNAL_TOKEN_FILE = Path("/data/secrets/mcphub_cloudflare_token")
CLOUDFLARE_CLIENT_KEY_FILE = Path("/data/secrets/mcphub_cloudflare_client_key")
TAILSCALE_INTERNAL_TOKEN_FILE = Path("/data/secrets/mcphub_tailscale_funnel_token")
TAILSCALE_CLIENT_KEY_FILE = Path("/data/secrets/mcphub_tailscale_client_key")

MCP_PATH_PATTERN = re.compile(r"^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$")
HA_MCP_PATH_PATTERN = re.compile(r"^/api/mcp(?:/[A-Za-z0-9._~-]+)?$")
ACCESS_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._~-]{20,4096}$")
SYSTEM_CA_FILE = Path("/etc/ssl/certs/ca-certificates.crt")
CUSTOM_CA_ROOT = Path("/ssl")
# Only allow PEM files within the read-only Home Assistant SSL share.
CUSTOM_CA_PATTERN = re.compile(r"^/ssl/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.pem$")


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
    with OPTIONS_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError("options.json must contain a JSON object")

    return flatten_grouped_options(data)


def read_secret(path: Path) -> str:
    """Read one generated runtime secret."""
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"Secret file is empty: {path}")
    return value


def validate_home_assistant_mcp_url(value: str) -> str:
    """Validate and normalize a direct Home Assistant MCP endpoint."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("home_assistant_mcp_url must use http or https")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("home_assistant_mcp_url must contain only a host and port")
    if parsed.query or parsed.fragment:
        raise ValueError("home_assistant_mcp_url must not contain query or fragment data")
    if not HA_MCP_PATH_PATTERN.fullmatch(parsed.path):
        raise ValueError(
            "home_assistant_mcp_url path must be /api/mcp or /api/mcp/<api-id>"
        )

    try:
        port = parsed.port
    except ValueError as err:
        raise ValueError("home_assistant_mcp_url contains an invalid port") from err

    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host if port is None else f"{host}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def trusted_home_assistant_ca_file(configured: str) -> Path:
    """Select a verified CA bundle without falling back to insecure HTTPS."""
    if not configured:
        return SYSTEM_CA_FILE
    if not CUSTOM_CA_PATTERN.fullmatch(configured):
        raise ValueError("home_assistant_mcp_ca_file must be a PEM file below /ssl")
    try:
        ca_file = (CUSTOM_CA_ROOT / configured.removeprefix("/ssl/")).resolve(strict=True)
        ca_file.relative_to(CUSTOM_CA_ROOT.resolve())
        if not ca_file.is_file():
            raise ValueError("home_assistant_mcp_ca_file must be a regular file")
        ssl.create_default_context(cafile=str(ca_file))
    except (OSError, ValueError, ssl.SSLError) as err:
        raise ValueError("home_assistant_mcp_ca_file is invalid or unreadable") from err
    return ca_file


def unavailable_home_assistant_mcp_block() -> str:
    """Fail closed for invalid CA settings without taking down Ingress."""
    return """server {
    listen 127.0.0.1:8097;
    access_log off;
    location / { return 502; }
}"""


def home_assistant_mcp_server_block(options: dict) -> str:
    """Build a loopback-only bridge to Home Assistant's MCP endpoint."""
    if not bool(options.get("home_assistant_mcp_enabled", False)):
        return """server {
    listen 127.0.0.1:8097;
    access_log off;

    location / {
        return 404;
    }
}"""

    mode = str(
        options.get("home_assistant_mcp_auth_mode", "restricted_user")
    ).strip()

    if mode == "supervisor":
        token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
        upstream = "http://supervisor/core/api/mcp"
        mode_label = "Supervisor"
    elif mode == "restricted_user":
        token = str(options.get("home_assistant_mcp_user_token", "")).strip()
        upstream = validate_home_assistant_mcp_url(
            str(
                options.get(
                    "home_assistant_mcp_url",
                    "http://homeassistant:8123/api/mcp",
                )
            )
        )
        mode_label = "dedicated Home Assistant user"
    else:
        raise ValueError(
            "home_assistant_mcp_auth_mode must be restricted_user or supervisor"
        )

    if not ACCESS_TOKEN_PATTERN.fullmatch(token):
        raise ValueError(
            f"{mode_label} token is missing or contains unexpected characters"
        )

    # HTTPS must verify the CA and hostname; LAN HTTP needs no TLS settings.
    ssl_directives = ""
    if upstream.startswith("https://"):
        try:
            ca_file = trusted_home_assistant_ca_file(
                str(options.get("home_assistant_mcp_ca_file", "")).strip()
            )
        except ValueError as err:
            print(f"[WARN] Home Assistant MCP HTTPS unavailable: {err}", file=sys.stderr)
            return unavailable_home_assistant_mcp_block()
        ssl_directives = (
            "        proxy_ssl_server_name on;\n"
            "        proxy_ssl_verify on;\n"
            f"        proxy_ssl_trusted_certificate {ca_file};\n"
            "        proxy_ssl_verify_depth 5;"
        )

    return f"""server {{
    listen 127.0.0.1:8097;

    access_log /dev/stdout;
    error_log /dev/stderr warn;

    client_max_body_size 16m;

    location = /mcp {{
        proxy_pass {upstream};
        proxy_http_version 1.1;

        proxy_set_header Authorization "Bearer {token}";
        proxy_set_header Host $proxy_host;
        proxy_set_header X-Real-IP "";
        proxy_set_header X-Forwarded-For "";
        proxy_set_header X-Forwarded-Proto "";

{ssl_directives}

        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}

    location / {{
        return 404;
    }}
}}"""


def valid_mcp_path(path: str) -> bool:
    return (bool(MCP_PATH_PATTERN.fullmatch(path))
            and all(part not in (".", "..") for part in path.split("/")[2:]))


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

    if not valid_mcp_path(mcp_path):
        print("[WARN] Invalid Cloudflare path; origin denies all requests", file=sys.stderr)
        return """server {
    listen 127.0.0.1:8098;
    access_log off;
    location / { return 404; }
}"""

    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", client_token):
        print("[WARN] Invalid Cloudflare client key; origin denies all requests", file=sys.stderr)
        return """server {
    listen 127.0.0.1:8098;
    access_log off;
    location / { return 404; }
}"""

    location_pattern = re.escape(mcp_path)

    return f"""server {{
    listen 127.0.0.1:8098;

    access_log /dev/stdout;
    error_log /dev/stderr warn;

    client_max_body_size 16m;

    location ~ ^{location_pattern}$ {{
        if ($http_authorization != "Bearer {client_token}") {{
            return 401;
        }}

        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;

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


def tailscale_gateway_server_block(
    *, enabled: bool, mcp_path: str, client_token: str, internal_token: str
) -> str:
    """Serve exactly one MCP route. No Tailscale process and no HA identity.

    The Home Assistant Tailscale App uses host_network and its CLI only proxies
    localhost. The optional host mapping for container 3002 is OFF by default.
    """
    disabled = """server {
    listen 3002;
    access_log off;
    add_header X-MCPHub-Tailscale-Gateway "mcphub-mcp-only" always;
    location / { return 404; }
}"""
    if not enabled:
        return disabled
    if not valid_mcp_path(mcp_path):
        print("[WARN] Invalid Tailscale route; gateway denies all", file=sys.stderr)
        return disabled
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", client_token):
        print("[WARN] Invalid Tailscale client key; gateway denies all", file=sys.stderr)
        return disabled
    if not re.fullmatch(r"mts_[A-Za-z0-9_-]{32,256}", internal_token):
        print("[WARN] Invalid Tailscale internal key; gateway denies all", file=sys.stderr)
        return disabled

    return f"""server {{
    listen 3002;
    server_tokens off;
    access_log /dev/stdout;
    error_log /dev/stderr warn;
    client_max_body_size 16m;
    add_header X-MCPHub-Tailscale-Gateway "mcphub-mcp-only" always;

    # Internal-only authorization subrequest; cannot be called externally.
    location = /__mcphub_tailscale_gate {{
        internal;
        proxy_pass http://127.0.0.1:8093/api/tailscale/gate;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header Authorization "";
        proxy_set_header X-Remote-User-Id "";
    }}

    location ~ ^{re.escape(mcp_path)}$ {{
        if ($http_authorization != "Bearer {client_token}") {{
            return 401;
        }}
        auth_request /__mcphub_tailscale_gate;

        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Authorization "Bearer {internal_token}";

        # Public clients are never trusted Home Assistant Ingress identities.
        proxy_set_header X-MCPHub-HA-Proxy-Secret "";
        proxy_set_header X-Remote-User-Id "";
        proxy_set_header X-Remote-User-Name "";
        proxy_set_header X-Remote-User-Display-Name "";
        proxy_set_header X-Remote-User-Email "";
        proxy_set_header X-Remote-User-Groups "";
        proxy_set_header X-Forwarded-Prefix "";
        proxy_set_header Proxy-Authorization "";

        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }}

    location / {{ return 404; }}
}}"""


def main() -> None:
    options = load_options()
    template = TEMPLATE_FILE.read_text(encoding="utf-8")

    ha_ingress_proxy_secret = read_secret(HA_INGRESS_PROXY_SECRET_FILE)
    cloudflare_internal_token = read_secret(CLOUDFLARE_INTERNAL_TOKEN_FILE)
    tailscale_internal_token = read_secret(TAILSCALE_INTERNAL_TOKEN_FILE)

    home_assistant_block = home_assistant_mcp_server_block(options)
    cloudflare_block = cloudflare_server_block(
        enabled=bool(options.get("cloudflare_tunnel_enabled", False)),
        mcp_path=str(options.get("cloudflare_mcp_path", "/mcp")),
        client_token=read_secret(CLOUDFLARE_CLIENT_KEY_FILE),
        internal_token=cloudflare_internal_token,
    )

    tailscale_block = tailscale_gateway_server_block(
        enabled=bool(options.get("tailscale_funnel_enabled", False)),
        mcp_path=str(options.get("tailscale_mcp_path", "/mcp")),
        client_token=read_secret(TAILSCALE_CLIENT_KEY_FILE),
        internal_token=tailscale_internal_token,
    )

    rendered = (
        template.replace(
            "__HA_INGRESS_PROXY_SECRET__",
            ha_ingress_proxy_secret,
        )
        .replace(
            "__HOME_ASSISTANT_MCP_SERVER_BLOCK__",
            home_assistant_block,
        )
        .replace(
            "__CLOUDFLARE_SERVER_BLOCK__",
            cloudflare_block,
        )
        .replace(
            "__TAILSCALE_SERVER_BLOCK__",
            tailscale_block,
        )
    )

    # Atomic configuration swap for safe live rotation of the external client key.
    tmp = OUTPUT_FILE.with_suffix(".conf.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
        os.chmod(tmp, 0o600)
        os.replace(tmp, OUTPUT_FILE)
    finally:
        tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
