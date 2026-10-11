#!/usr/bin/env bash
set -Eeuo pipefail

readonly MCP_SERVER_VERSION="0.3.0"
readonly MCP_SERVER_BIN="/opt/gh-cli-mcp/bin/gh-cli-mcp-server"
readonly TOOL_ROOT="/data/tools/github-cli"
readonly TOKEN_FILE="/data/secrets/github_token"

log() {
    printf '[github-cli-mcp] %s\n' "$*" >&2
}

mkdir -p "${TOOL_ROOT}/config"

export GH_CONFIG_DIR="${TOOL_ROOT}/config"
export GH_PROMPT_DISABLED=1

if ! command -v gh >/dev/null 2>&1; then
    log "GitHub CLI is missing from the App image."
    exit 1
fi

if [[ ! -x "${MCP_SERVER_BIN}" ]]; then
    log "gh-cli-mcp-server is missing from the App image."
    exit 1
fi

if [[ -s "${TOKEN_FILE}" ]]; then
    export GH_TOKEN
    GH_TOKEN="$(cat "${TOKEN_FILE}")"
fi

log "Starting gh-cli-mcp-server ${MCP_SERVER_VERSION} with $(gh --version | head -n1)."
exec "${MCP_SERVER_BIN}"
