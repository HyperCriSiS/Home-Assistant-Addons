#!/usr/bin/env python3
"""MCPHub's Tailscale Funnel *origin*, not a Tailscale daemon/controller.

The existing Home Assistant Tailscale App owns Funnel. This component gates
only the explicitly configured MCP-only HTTP origin.
"""
from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

MCP_ROUTE = re.compile(r"^/mcp(?:/[A-Za-z0-9._$-]+){0,2}$")
TS_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+\.ts\.net$")
GATE_STATE = Path("/data/secrets/mcphub_tailscale_gateway_state")
MARKER = "mcphub-mcp-only"
ORIGIN = "http://127.0.0.1:3002"


def valid_mcp_route(route: str) -> bool:
    return (bool(MCP_ROUTE.fullmatch(route))
            and all(part not in (".", "..") for part in route.split("/")[2:]))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_public_url(value: str, route: str) -> str:
    """Do not probe arbitrary URLs or send credentials to a remote endpoint."""
    if not value:
        return ""
    if len(value) > 240:
        raise ValueError("Funnel URL is too long")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or
            parsed.netloc != parsed.hostname or not TS_HOST.fullmatch(parsed.hostname)
            or parsed.path != route or parsed.query or parsed.fragment):
        raise ValueError("Funnel URL must be https://<node>.<tailnet>.ts.net" + route)
    return value


def is_origin_response(path: str) -> bool:
    """Local, unauthenticated probe: 401 + our marker, never a public MCP key."""
    try:
        with urlopen(Request(ORIGIN + path, headers={"Cache-Control": "no-store"}), timeout=2):
            return False
    except HTTPError as error:
        return error.code == 401 and error.headers.get("X-MCPHub-Tailscale-Gateway") == MARKER
    except (URLError, TimeoutError, OSError, ValueError):
        return False


def probe_https(url: str) -> bool:
    """Verified HTTPS check, with no auth and no redirects.

    Note: a check initiated from Home Assistant is NOT proof that a public
    internet client can reach Funnel (tailnet routes may bypass the relay).
    """
    opener = build_opener(NoRedirect())
    try:
        with opener.open(Request(url, headers={"Cache-Control": "no-store"}), timeout=4):
            return False
    except HTTPError as error:
        return error.code == 401 and error.headers.get("X-MCPHub-Tailscale-Gateway") == MARKER
    except (URLError, TimeoutError, OSError, ValueError):
        return False


class TailscaleGateway:
    def __init__(self, get_options, state_file=None):
        self.lock = threading.RLock()
        self.get_options = get_options
        self.state_file = state_file if state_file is not None else GATE_STATE
        self.public_check = None
        self.public_checked = 0.0
        self._load_initial_state()

    def _load_initial_state(self):
        try:
            content = self.state_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            # First installation: an enabled HA option starts its private gate.
            self.running = bool(self.get_options().get("tailscale_funnel_enabled"))
        except OSError:
            self.running = False
        else:
            self.running = content == "running"

    def _configured(self):
        opts = self.get_options()
        route = str(opts.get("tailscale_mcp_path") or "/mcp")
        enabled = opts.get("tailscale_funnel_enabled") is True
        url = str(opts.get("tailscale_funnel_url") or "").strip()
        return enabled, route, url

    def _persist(self, state: str):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_file.parent, 0o700)
        temp = self.state_file.with_suffix(".tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(state)
            os.chmod(temp, 0o600)
            temp.replace(self.state_file)
        finally:
            temp.unlink(missing_ok=True)

    def authorized(self):
        with self.lock:
            try:
                enabled, route, _url = self._configured()
                return enabled and bool(MCP_ROUTE.fullmatch(route)) and self.running
            except (ValueError, OSError, TypeError):
                return False

    def command(self, action):
        if action not in ("start", "stop"):
            raise ValueError("Only local MCP gateway start/stop is supported")
        with self.lock:
            enabled, route, _url = self._configured()
            if action == "start" and (not enabled or not valid_mcp_route(route)):
                raise ValueError("Enable a valid Tailscale MCP origin in Home Assistant first")
            self._persist("running" if action == "start" else "stopped")
            self.running = action == "start"
            self.public_check = None
            self.public_checked = 0.0
        return self.status()

    def status(self):
        with self.lock:
            try:
                enabled, route, url = self._configured()
            except (ValueError, OSError, TypeError):
                enabled, route, url = False, "/mcp", ""
            valid_route = bool(MCP_ROUTE.fullmatch(route))
            requested = self.running and enabled and valid_route
            gateway_ready = bool(requested and is_origin_response(route))
            if not enabled:
                state = "stopped"
                note = "MCP-Zugang in der App-Konfiguration deaktiviert."
            elif not valid_route:
                state = "error"
                note = "Ungültige MCP-Route in der App-Konfiguration."
            elif not self.running:
                state = "stopped"
                note = "Lokaler MCP-Zugang angehalten; Funnel selbst wird nicht gesteuert."
            elif not gateway_ready:
                state = "degraded"
                note = "Lokaler Gateway-Port nicht bereit. Add-on- und Proxy-Konfiguration prüfen."
            else:
                state = "gateway_ready"
                note = "MCP-Gateway im Container bereit. Host-Port und Funnel nicht bestätigt."
            try:
                validate_public_url(url, route)
                url_valid = True
            except ValueError:
                url_valid = False
            return {
                "state": state,
                "configured": enabled,
                "requested": requested,
                "gateway_ready": gateway_ready,
                "transport_ready": False,
                "route": route,
                "gateway_target": ORIGIN,
                "public_url": url if url_valid else "",
                "public_url_invalid": bool(url and not url_valid),
                "public_check": self.public_check,
                "public_checked_age_seconds":
                    round(time.monotonic() - self.public_checked) if self.public_checked else None,
                "last_error": note,
                "control_type": "local-gateway",
                "funnel_control": "manual",
            }

    def check_https(self):
        with self.lock:
            enabled, route, url = self._configured()
            if not enabled:
                raise ValueError("Tailscale MCP origin is disabled")
            url = validate_public_url(url, route)
            if not url:
                raise ValueError("Configure the Funnel URL in Home Assistant first")
        result = probe_https(url)
        with self.lock:
            self.public_check = "gateway_answered" if result else "not_verified"
            self.public_checked = time.monotonic()
            return {
                "result": self.public_check,
                "note": ("HTTPS reached the expected MCP gateway without credentials."
                         if result else "No verified response from the expected MCP gateway."),
                "public_internet_proven": False,
            }
