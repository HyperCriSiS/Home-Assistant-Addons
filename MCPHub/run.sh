#!/usr/bin/env bash
set -Eeuo pipefail

readonly OPTIONS_FILE="/data/options.json"
readonly MCPHUB_DATA_DIR="/data/mcphub"
readonly SECRET_DIR="/data/secrets"
readonly OPENAI_KEY_FILE="${SECRET_DIR}/openai_runtime_api_key"
readonly JWT_SECRET_FILE="${SECRET_DIR}/mcphub_jwt_secret"
readonly TUNNEL_AUTH_FILE="${SECRET_DIR}/mcphub_tunnel_authorization"

mcphub_pid=""
nginx_pid=""
tunnel_pid=""

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

shutdown_processes() {
    local status="${1:-0}"

    trap - TERM INT EXIT

    for pid in "${tunnel_pid}" "${nginx_pid}" "${mcphub_pid}"; do
        if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
            kill -TERM "${pid}" 2>/dev/null || true
        fi
    done

    for pid in "${tunnel_pid}" "${nginx_pid}" "${mcphub_pid}"; do
        if [[ -n "${pid}" ]]; then
            wait "${pid}" 2>/dev/null || true
        fi
    done

    exit "${status}"
}

trap 'shutdown_processes 143' TERM
trap 'shutdown_processes 130' INT

tunnel_enabled="$(option tunnel_enabled)"
openai_runtime_api_key="$(option openai_runtime_api_key)"
tunnel_id="$(option tunnel_id)"
tunnel_mcp_path="$(option tunnel_mcp_path)"
tunnel_log_level="$(option tunnel_log_level)"

mkdir -p \
    "${MCPHUB_DATA_DIR}" \
    "${SECRET_DIR}" \
    /data/home \
    /data/cache/npm \
    /data/cache/uv

chmod 0700 "${SECRET_DIR}"

/usr/local/bin/prepare_mcphub_config.py

export PORT="3000"
export BASE_PATH=""
export NODE_ENV="production"
export MCPHUB_SETTING_PATH="${MCPHUB_DATA_DIR}/mcp_settings.json"
export JWT_SECRET
JWT_SECRET="$(cat "${JWT_SECRET_FILE}")"

# Persist package caches used by dynamically installed npx and uvx MCP servers.
export HOME="/data/home"
export XDG_CACHE_HOME="/data/cache"
export NPM_CONFIG_CACHE="/data/cache/npm"
export UV_CACHE_DIR="/data/cache/uv"

log_info "Starting MCPHub 1.1.0 on internal loopback port 3000."
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

log_info "MCPHub is ready. Starting the Home Assistant Ingress adapter on port 8099."
nginx -g 'daemon off;' &
nginx_pid="$!"

if [[ "${tunnel_enabled}" == "true" ]]; then
    case "${tunnel_mcp_path}" in
        /mcp|/mcp/*)
            ;;
        *)
            log_error "tunnel_mcp_path must be /mcp or start with /mcp/."
            shutdown_processes 1
            ;;
    esac

    if [[ -z "${openai_runtime_api_key}" || -z "${tunnel_id}" ]]; then
        log_warn "The OpenAI tunnel is enabled, but the Runtime API Key or Tunnel ID is missing."
        log_warn "MCPHub will continue without the ChatGPT tunnel."
    elif [[ ! "${tunnel_id}" =~ ^tunnel_[A-Za-z0-9_-]+$ ]]; then
        log_error "The Tunnel ID must start with tunnel_ and contain only letters, numbers, underscores, or dashes."
        shutdown_processes 1
    else
        umask 077
        printf '%s' "${openai_runtime_api_key}" > "${OPENAI_KEY_FILE}"
        chmod 0600 "${OPENAI_KEY_FILE}"
        unset openai_runtime_api_key

        export CONTROL_PLANE_TUNNEL_ID="${tunnel_id}"
        export MCP_SERVER_URL="http://127.0.0.1:3000${tunnel_mcp_path}"
        export MCP_EXTRA_HEADERS="Authorization: file:${TUNNEL_AUTH_FILE}"
        export MCP_DISCOVERY_EXTRA_HEADERS="Authorization: file:${TUNNEL_AUTH_FILE}"
        export MCP_STARTUP_WAIT_TIMEOUT="30s"
        export MCP_MAX_CONCURRENT_REQUESTS="20"
        export HEALTH_LISTEN_ADDR="127.0.0.1:8080"
        export LOG_LEVEL="${tunnel_log_level}"
        export LOG_FORMAT="struct-text"
        export LOG_HTTP_RAW_UNSAFE="false"

        log_info "Starting the OpenAI Secure MCP Tunnel for ${tunnel_mcp_path}."
        /usr/local/bin/tunnel-client run \
            --control-plane.api-key="file:${OPENAI_KEY_FILE}" &
        tunnel_pid="$!"
    fi
fi

if [[ -n "${tunnel_pid}" ]]; then
    set +e
    wait -n "${mcphub_pid}" "${nginx_pid}" "${tunnel_pid}"
    status="$?"
    set -e
else
    set +e
    wait -n "${mcphub_pid}" "${nginx_pid}"
    status="$?"
    set -e
fi

if ! kill -0 "${mcphub_pid}" 2>/dev/null; then
    log_error "MCPHub exited unexpectedly."
elif ! kill -0 "${nginx_pid}" 2>/dev/null; then
    log_error "The Home Assistant Ingress adapter exited unexpectedly."
elif [[ -n "${tunnel_pid}" ]] && ! kill -0 "${tunnel_pid}" 2>/dev/null; then
    log_error "The OpenAI Secure MCP Tunnel exited unexpectedly."
fi

shutdown_processes "${status}"
