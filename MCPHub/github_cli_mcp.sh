#!/usr/bin/env bash
set -Eeuo pipefail

readonly MCP_SERVER_VERSION="0.3.0"
readonly TOOL_ROOT="/data/tools/github-cli"
readonly TOKEN_FILE="/data/secrets/github_token"

log() {
    printf '[github-cli-mcp] %s\n' "$*" >&2
}

mkdir -p "${TOOL_ROOT}/config" /data/cache/uv

export GH_CONFIG_DIR="${TOOL_ROOT}/config"
export GH_PROMPT_DISABLED=1
export UV_CACHE_DIR="${UV_CACHE_DIR:-/data/cache/uv}"

if ! command -v gh >/dev/null 2>&1; then
    log "GitHub CLI is missing from the App image."
    exit 1
fi

if [[ -s "${TOKEN_FILE}" ]]; then
    export GH_TOKEN
    GH_TOKEN="$(cat "${TOKEN_FILE}")"
fi

log "Starting gh-cli-mcp-server ${MCP_SERVER_VERSION} with $(gh --version | head -n1)."
exec uvx --from "gh-cli-mcp-server==${MCP_SERVER_VERSION}" gh-cli-mcp-server
