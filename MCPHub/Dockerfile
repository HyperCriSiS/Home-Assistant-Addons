ARG OPENAI_TUNNEL_VERSION=v0.0.15
ARG BUILD_FROM=samanhappy/mcphub:1.1.0

FROM ghcr.io/openai/tunnel-client:${OPENAI_TUNNEL_VERSION} AS openai_tunnel
FROM ${BUILD_FROM}

ARG BUILD_VERSION
ARG BUILD_ARCH

LABEL \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    org.opencontainers.image.source="https://github.com/HyperCriSiS/Home-Assistant-Addons" \
    org.opencontainers.image.description="MCPHub with an optional OpenAI Secure MCP Tunnel for Home Assistant"

USER root

# Nginx is used only as the Home Assistant Ingress adapter.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

# MCPHub 1.1.0 listens on all interfaces upstream. The pinned release is patched
# to bind its main server to loopback so only the Ingress adapter is reachable.
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

COPY ingress.conf /etc/nginx/conf.d/mcphub-ingress.conf
COPY prepare_config.py /usr/local/bin/prepare_mcphub_config.py
COPY run.sh /run.sh

RUN chmod 0755 /run.sh /usr/local/bin/prepare_mcphub_config.py

ENTRYPOINT ["/run.sh"]
