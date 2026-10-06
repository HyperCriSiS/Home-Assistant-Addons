#!/usr/bin/env bash
set -Eeuo pipefail

readonly GH_VERSION="2.101.0"
readonly MCP_SERVER_VERSION="0.3.0"
readonly TOOL_ROOT="/data/tools/github-cli"
readonly INSTALL_ROOT="${TOOL_ROOT}/gh/${GH_VERSION}"
readonly GH_BIN="${INSTALL_ROOT}/bin/gh"
readonly TOKEN_FILE="/data/secrets/github_token"

log() {
    printf '[github-cli-mcp] %s\n' "$*" >&2
}

install_gh() {
    local arch asset checksum tmp extracted

    case "$(uname -m)" in
        x86_64|amd64)
            arch="amd64"
            checksum="a401287272a4cc22716a0e48422bbf779428234e3603b5b9dece6af946eb0811"
            ;;
        aarch64|arm64)
            arch="arm64"
            checksum="5fc5c19cf775582a054d2ff38df13dd1df0356864a904a1e81df8fb02227dfa6"
            ;;
        *)
            log "Unsupported architecture: $(uname -m)"
            exit 1
            ;;
    esac

    asset="gh_${GH_VERSION}_linux_${arch}.tar.gz"
    tmp="$(mktemp -d)"
    trap 'rm -rf "${tmp}"' RETURN

    log "Installing GitHub CLI ${GH_VERSION} for ${arch}."
    curl --fail --silent --show-error --location \
        --retry 3 --retry-delay 2 \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${asset}" \
        --output "${tmp}/${asset}"

    printf '%s  %s\n' "${checksum}" "${tmp}/${asset}" | sha256sum --check --status -

    tar -xzf "${tmp}/${asset}" -C "${tmp}"
    extracted="${tmp}/gh_${GH_VERSION}_linux_${arch}/bin/gh"

    mkdir -p "${INSTALL_ROOT}/bin"
    install -m 0755 "${extracted}" "${GH_BIN}"
    log "GitHub CLI ${GH_VERSION} installed successfully."
}

mkdir -p "${TOOL_ROOT}/config" /data/cache/uv

if [[ ! -x "${GH_BIN}" ]]; then
    install_gh
fi

export PATH="${INSTALL_ROOT}/bin:${PATH}"
export GH_CONFIG_DIR="${TOOL_ROOT}/config"
export GH_PROMPT_DISABLED=1
export UV_CACHE_DIR="${UV_CACHE_DIR:-/data/cache/uv}"

if [[ -s "${TOKEN_FILE}" ]]; then
    export GH_TOKEN
    GH_TOKEN="$(cat "${TOKEN_FILE}")"
fi

log "Starting gh-cli-mcp-server ${MCP_SERVER_VERSION} with $(${GH_BIN} --version | head -n1)."
exec uvx --from "gh-cli-mcp-server==${MCP_SERVER_VERSION}" gh-cli-mcp-server
