#!/usr/bin/env bash
set -Eeuo pipefail

readonly OPTIONS_FILE="/data/options.json"
readonly MCPHUB_DATA_DIR="/data/mcphub"
readonly SECRET_DIR="/data/secrets"
readonly JWT_SECRET_FILE="${SECRET_DIR}/mcphub_jwt_secret"
readonly HA_INGRESS_PROXY_SECRET_FILE="${SECRET_DIR}/mcphub_ha_ingress_proxy_secret"

mcphub_pid=""
nginx_pid=""
tunnel_manager_pid=""
tunnel_control_pid=""

log_info() {
    printf '[INFO] %s\n' "$*"
}

log_warn() {
    printf '[WARN] %s\n' "$*" >&2
}

log_error() {
    printf '[ERROR] %s\n' "$*" >&2
}

option() {
    local key="$1"
    python3 - "${OPTIONS_FILE}" "${key}" <<'PY'
import json
import sys

path, key = sys.argv[1], sys.argv[2]
with open(path, "r", encoding="utf-8") as handle:
    data = json.load(handle)

for group in ("openai", "cloudflare", "home_assistant", "github", "logging"):
    nested = data.get(group)
    if isinstance(nested, dict):
        data.update(nested)
value = data.get(key, "")
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(value)
PY
}

valid_mcp_path() {
    local path="$1"
    [[ "${path}" =~ ^/mcp(/[A-Za-z0-9._\$-]+){0,2}$ ]] || return 1
    local segments segment
    IFS='/' read -r -a segments <<< "${path}"
    for segment in "${segments[@]:2}"; do
        [[ "${segment}" != "." && "${segment}" != ".." ]] || return 1
    done
    return 0
}

shutdown_processes() {
    local status="${1:-0}"

    trap - TERM INT EXIT

    for pid in         "${tunnel_control_pid}"         "${tunnel_manager_pid}"         "${nginx_pid}"         "${mcphub_pid}"; do
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            kill -TERM "${pid}" 2>/dev/null || true
        fi
    done

    for pid in         "${tunnel_control_pid}"         "${tunnel_manager_pid}"         "${nginx_pid}"         "${mcphub_pid}"; do
        if [[ -n "${pid}" ]]; then
            wait "${pid}" 2>/dev/null || true
        fi
    done

    exit "${status}"
}

trap 'shutdown_processes 143' TERM
trap 'shutdown_processes 130' INT


cloudflare_tunnel_enabled="$(option cloudflare_tunnel_enabled)"
cloudflare_tunnel_enabled="${cloudflare_tunnel_enabled:-false}"
cloudflare_mcp_path="$(option cloudflare_mcp_path)"
cloudflare_mcp_path="${cloudflare_mcp_path:-/mcp}"

home_assistant_mcp_enabled="$(option home_assistant_mcp_enabled)"
home_assistant_mcp_enabled="${home_assistant_mcp_enabled:-false}"
home_assistant_mcp_auth_mode="$(option home_assistant_mcp_auth_mode)"
home_assistant_mcp_auth_mode="${home_assistant_mcp_auth_mode:-restricted_user}"

mkdir -p     "${MCPHUB_DATA_DIR}"     "${SECRET_DIR}"     /data/home     /data/cache/npm     /data/cache/uv

chmod 0700 "${SECRET_DIR}"

if [[ "${cloudflare_tunnel_enabled}" == "true" ]] && ! valid_mcp_path "${cloudflare_mcp_path}"; then
    log_warn "Invalid Cloudflare MCP path; tunnel stays disabled while MCPHub starts."
    cloudflare_tunnel_enabled="false"
fi

/usr/local/bin/prepare_mcphub_config.py
/usr/local/bin/prepare_proxy_config.py

if [[ "${home_assistant_mcp_enabled}" == "true" ]]; then
    log_info "Managed Home Assistant MCP server enabled with ${home_assistant_mcp_auth_mode} authentication."
fi

export PORT="3000"
export BASE_PATH=""
export NODE_ENV="production"
export MCPHUB_SETTING_PATH="${MCPHUB_DATA_DIR}/mcp_settings.json"
export JWT_SECRET
JWT_SECRET="$(cat "${JWT_SECRET_FILE}")"
export HA_INGRESS_PROXY_SECRET
HA_INGRESS_PROXY_SECRET="$(cat "${HA_INGRESS_PROXY_SECRET_FILE}")"

# Persist package caches used by dynamically installed npx and uvx MCP servers.
export HOME="/data/home"
export XDG_CACHE_HOME="/data/cache"
export NPM_CONFIG_CACHE="/data/cache/npm"
export UV_CACHE_DIR="/data/cache/uv"

log_info "Starting MCPHub 1.1.5 on internal loopback port 3000."
if [[ -r /etc/mcphub-source-revision ]]; then
    log_info "Build source revision: $(cat /etc/mcphub-source-revision)"
fi
(
    cd /app
    /usr/local/bin/entrypoint.sh node dist/index.js
) &
mcphub_pid="$!"

ready=false
for _ in $(seq 1 120); do
    if ! kill -0 "${mcphub_pid}" 2>/dev/null; then
        wait "${mcphub_pid}" || true
        log_error "MCPHub exited during startup."
        exit 1
    fi

    if curl --silent --fail --max-time 1 http://127.0.0.1:3000/health >/dev/null 2>&1; then
        ready=true
        break
    fi

    sleep 0.5
done

if [[ "${ready}" != "true" ]]; then
    log_error "MCPHub did not become ready within 60 seconds."
    shutdown_processes 1
fi

if ! nginx -t; then
    log_error "Generated Nginx configuration is invalid."
    shutdown_processes 1
fi

log_info "MCPHub is ready. Starting the Home Assistant Ingress adapter on port 8099."
nginx -g 'daemon off;' &
nginx_pid="$!"

log_info "Starting isolated OpenAI Tunnel health and control manager."
/usr/local/bin/tunnel_manager.py &
tunnel_manager_pid="$!"

log_info "Starting isolated Cloudflare Tunnel controller and health dashboard."
/usr/local/bin/tunnel_control.py &
tunnel_control_pid="$!"

# Optional remote tunnels must never take MCPHub or its Ingress adapter down.
# Monitor their lifecycle independently; only core process failures stop the App.
while true; do
    if ! kill -0 "${mcphub_pid}" 2>/dev/null; then
        log_error "MCPHub exited unexpectedly."
        shutdown_processes 1
    fi
    if ! kill -0 "${nginx_pid}" 2>/dev/null; then
        log_error "The Home Assistant proxy adapter exited unexpectedly."
        shutdown_processes 1
    fi

    if [[ -n "${tunnel_manager_pid}" ]] && ! kill -0 "${tunnel_manager_pid}" 2>/dev/null; then
        wait "${tunnel_manager_pid}" || true
        log_warn "OpenAI Tunnel manager exited; restarting supervisor, MCPHub remains available."
        /usr/local/bin/tunnel_manager.py &
        tunnel_manager_pid="$!"
    fi
    if [[ -n "${tunnel_control_pid}" ]] && ! kill -0 "${tunnel_control_pid}" 2>/dev/null; then
        wait "${tunnel_control_pid}" 2>/dev/null || true
        log_warn "Cloudflare Tunnel controller exited; restarting independently."
        /usr/local/bin/tunnel_control.py &
        tunnel_control_pid="$!"
    fi
    sleep 2 &
    wait "$!" || true
done
