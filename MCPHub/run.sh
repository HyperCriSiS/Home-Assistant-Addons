#!/usr/bin/env bash
set -Eeuo pipefail

readonly OPTIONS_FILE="/data/options.json"
readonly MCPHUB_DATA_DIR="/data/mcphub"
readonly SECRET_DIR="/data/secrets"
readonly JWT_SECRET_FILE="${SECRET_DIR}/mcphub_jwt_secret"
readonly HA_INGRESS_PROXY_SECRET_FILE="${SECRET_DIR}/mcphub_ha_ingress_proxy_secret"

mcphub_pid=""
nginx_pid=""
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
    [[ "${path}" =~ ^/mcp(/[A-Za-z0-9._\$-]+){0,2}$ ]]
}

shutdown_processes() {
    local status="${1:-0}"

    trap - TERM INT EXIT

    for pid in         "${tunnel_control_pid}"         "${nginx_pid}"         "${mcphub_pid}"; do
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            kill -TERM "${pid}" 2>/dev/null || true
        fi
    done

    for pid in         "${tunnel_control_pid}"         "${nginx_pid}"         "${mcphub_pid}"; do
        if [[ -n "${pid}" ]]; then
            wait "${pid}" 2>/dev/null || true
        fi
    done

    exit "${status}"
}

trap 'shutdown_processes 143' TERM
trap 'shutdown_processes 130' INT


mkdir -p     "${MCPHUB_DATA_DIR}"     "${SECRET_DIR}"     /data/home     /data/cache/npm     /data/cache/uv

chmod 0700 "${SECRET_DIR}"

if [[ -n "$(option tunnel_mcp_path)" ]] && ! valid_mcp_path "$(option tunnel_mcp_path)"; then
    log_error "tunnel_mcp_path must be /mcp or contain at most two safe path segments."
    exit 1
fi

if [[ -n "$(option cloudflare_mcp_path)" ]] && ! valid_mcp_path "$(option cloudflare_mcp_path)"; then
    log_error "cloudflare_mcp_path must be /mcp or contain at most two safe path segments."
    exit 1
fi

/usr/local/bin/prepare_mcphub_config.py
/usr/local/bin/prepare_proxy_config.py

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

log_info "Starting MCPHub 1.1.1 on internal loopback port 3000."
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

log_info "Starting ingress-only network and tunnel control."
/usr/local/bin/tunnel_control.py &
tunnel_control_pid="$!"

pids=("${mcphub_pid}" "${nginx_pid}")
pids+=("${tunnel_control_pid}")

set +e
wait -n "${pids[@]}"
status="$?"
set -e

if ! kill -0 "${mcphub_pid}" 2>/dev/null; then
    log_error "MCPHub exited unexpectedly."
elif ! kill -0 "${nginx_pid}" 2>/dev/null; then
    log_error "The Home Assistant proxy adapter exited unexpectedly."
elif ! kill -0 "${tunnel_control_pid}" 2>/dev/null; then
    log_error "Tunnel control service exited unexpectedly."
fi

shutdown_processes "${status}"