ARG OPENAI_TUNNEL_VERSION=v0.0.15
ARG CLOUDFLARED_VERSION=2026.9.3
ARG BUILD_FROM=samanhappy/mcphub:1.1.0

FROM ghcr.io/openai/tunnel-client:${OPENAI_TUNNEL_VERSION} AS openai_tunnel
FROM cloudflare/cloudflared:${CLOUDFLARED_VERSION} AS cloudflare_tunnel
FROM ${BUILD_FROM}

ARG BUILD_VERSION
ARG BUILD_ARCH
ARG GH_VERSION=2.101.0

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.source="https://github.com/HyperCriSiS/Home-Assistant-Addons" \
    org.opencontainers.image.description="MCPHub with optional OpenAI and Cloudflare remote access for Home Assistant"

USER root

# Nginx provides the Home Assistant Ingress adapter and the restricted local
# origin used by Cloudflare Tunnel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl nginx \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default \
    && rm -f /etc/nginx/conf.d/default.conf

# Bundle a pinned GitHub CLI in the image instead of downloading it when the
# stdio MCP server starts. This keeps startup deterministic and lets Home
# Assistant App updates carry tested GitHub CLI updates.
RUN set -eux; \
    case "${BUILD_ARCH}" in \
        amd64) gh_arch="amd64"; gh_sha256="9bca2d1c16825f109907a23307628a2f0698fbf99662b73a5cf0b020293072b8" ;; \
        aarch64) gh_arch="arm64"; gh_sha256="b57e8063f18862647c9d22727c32e9da1b963f8bf9db648fe123a6975695640f" ;; \
        *) echo "Unsupported BUILD_ARCH for GitHub CLI: ${BUILD_ARCH}" >&2; exit 1 ;; \
    esac; \
    asset="gh_${GH_VERSION}_linux_${gh_arch}.tar.gz"; \
    tmp_dir="$(mktemp -d)"; \
    curl --fail --silent --show-error --location --retry 3 --retry-delay 2 \
        "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${asset}" \
        --output "${tmp_dir}/${asset}"; \
    printf '%s  %s\n' "${gh_sha256}" "${tmp_dir}/${asset}" | sha256sum --check --status -; \
    tar -xzf "${tmp_dir}/${asset}" -C "${tmp_dir}"; \
    install -m 0755 "${tmp_dir}/gh_${GH_VERSION}_linux_${gh_arch}/bin/gh" /usr/local/bin/gh; \
    rm -rf "${tmp_dir}"; \
    gh --version

# MCPHub 1.1.0 listens on all interfaces upstream. The pinned release is patched
# to bind its main server to loopback so only local adapters can reach it.
RUN python3 - <<'PY'
from pathlib import Path

path = Path("/app/dist/server.js")
text = path.read_text(encoding="utf-8")
old = "this.server = this.app.listen(this.port, () => {"
new = "this.server = this.app.listen(this.port, \"127.0.0.1\", () => {"

count = text.count(old)
if count != 1:
    raise SystemExit(f"Unexpected MCPHub server structure: listen call found {count} times")

path.write_text(text.replace(old, new), encoding="utf-8")
PY

COPY --from=openai_tunnel /usr/bin/tunnel-client /usr/local/bin/tunnel-client
COPY --from=cloudflare_tunnel /usr/local/bin/cloudflared /usr/local/bin/cloudflared

COPY patch_home_assistant_auth.py /usr/local/bin/patch_home_assistant_auth.py
RUN python3 /usr/local/bin/patch_home_assistant_auth.py \
    && rm /usr/local/bin/patch_home_assistant_auth.py

COPY ingress.conf /etc/nginx/mcphub.conf.template
COPY prepare_config.py /usr/local/bin/prepare_mcphub_config.py
COPY prepare_proxy_config.py /usr/local/bin/prepare_proxy_config.py
COPY github_cli_mcp.sh /usr/local/bin/github_cli_mcp.sh
COPY run.sh /run.sh

RUN chmod 0755 \
    /run.sh \
    /usr/local/bin/prepare_mcphub_config.py \
    /usr/local/bin/prepare_proxy_config.py \
    /usr/local/bin/github_cli_mcp.sh

ENTRYPOINT ["/run.sh"]
