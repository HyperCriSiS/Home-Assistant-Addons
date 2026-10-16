# MCPHub documentation

## About

This add-on runs MCPHub as a central control plane for MCP servers inside Home Assistant.

MCPHub can discover, configure, start, stop, group, monitor, and route multiple MCP
servers while exposing them through stable MCP endpoints.

Two independent remote-access methods are available:

- **OpenAI Secure MCP Tunnel** for ChatGPT and supported OpenAI clients
- **Cloudflare Tunnel** for Claude, Cursor, VS Code, and other remote MCP clients

Both are optional and can be enabled at the same time.

## Installation

Add this repository to the Home Assistant App store:

`https://github.com/HyperCriSiS/Home-Assistant-Apps`

Install **MCPHub** and start it with the default configuration first. Both remote-access
methods are disabled by default so the dashboard can be verified independently.

## First start

1. Start **MCPHub**.
2. Open **Web UI** from the Home Assistant App page.
3. Use MCPHub's **Market**, **Registry**, or **Add Server** flow to configure MCP servers.
4. Create focused groups for the tools each external client actually needs.
5. Verify that the selected servers connect successfully.
6. Enable remote access only after MCPHub is working locally.

No additional MCPHub dashboard login is required. Home Assistant Ingress authenticates
the Home Assistant user. Supervisor-provided `X-Remote-User-Id`,
`X-Remote-User-Name`, and `X-Remote-User-Display-Name` headers are then mapped
into MCPHub's request user context.

The App accepts those identity headers only when the trusted local Ingress adapter also
supplies a private per-installation proxy secret. Remote tunnel traffic cannot set or
reuse this trust marker.

The Home Assistant panel is configured with `panel_admin: true`. Because only
Home Assistant administrators are intended to enter this Ingress panel, trusted Ingress
identities are mapped to MCPHub administrators. The CI metadata checks enforce that
`panel_admin` remains enabled while this mapping is in use.

## Limit which tools a client receives

MCPHub groups are the preferred way to avoid exposing every MCP server and tool to every
client.

Examples:

- `/mcp/development`
- `/mcp/home`
- `/mcp/web`

A client connected to a group endpoint only discovers tools from servers in that group.

Both OpenAI and Cloudflare have their own route option, so they can expose different
groups at the same time.

Smart Routing is also supported by MCPHub through `/mcp/$smart`, but it requires
additional PostgreSQL/pgvector and embedding-service setup. This Home Assistant wrapper
does not automatically enable that extra infrastructure.

## OpenAI Secure MCP Tunnel

### `tunnel_enabled`

Default: `false`

Enables the OpenAI Secure MCP Tunnel.

### `openai_runtime_api_key`

OpenAI Runtime API Key used by the Secure MCP Tunnel client.

### `tunnel_id`

The OpenAI Secure MCP Tunnel ID.

### `tunnel_mcp_path`

Default: `/mcp`

Selects the MCPHub route exposed to OpenAI.

Examples:

- `/mcp`
- `/mcp/development`
- `/mcp/$smart`
- `/mcp/$smart/development`

### `tunnel_log_level`

Default: `info`

Allowed values are `debug`, `info`, and `warn`.

Raw HTTP logging remains disabled so Authorization headers are not intentionally written
to the App log.

## Cloudflare Tunnel

Cloudflare Tunnel provides a normal public HTTPS endpoint for remote MCP clients while
MCPHub itself remains private inside the Home Assistant App container.

The App uses `cloudflared` only for outbound tunnel connectivity. No router port
forwarding is required.

### Einrichtung von Cloudflare und Client Key

1. Erstelle einen remotely managed Tunnel unter Cloudflare Dashboard → Networking → Tunnels. **Cloudflare Zero Trust und Zahlungsdaten werden nicht benötigt.**
2. Lege den öffentlichen Hostnamen (z. B. `mcp.example.com`) an und setze den Origin auf `http://127.0.0.1:8098`.
3. Trage das **Tunnel Connector Token** unter Home Assistant → MCPHub → Konfiguration als `cloudflare_tunnel_token` ein und starte die App neu.
4. Öffne die MCPHub Web UI in Home Assistant. Rechts unten führt **Netzwerk & Tunnel** zur Tunnel-Steuerung.
5. Kopiere den **automatisch generierten Client Key** und hinterlege ihn im MCP-Client als Header `Authorization: Bearer <Client Key>`.
6. Aktiviere den Cloudflare Tunnel über die integrierte Tunnel-Steuerung. Der konfigurierte MCP-Pfad ist beispielsweise `https://mcp.example.com/mcp/development`.

Der Client Key wird **nicht** bei Cloudflare hinterlegt. Er schützt den MCP-Endpunkt direkt am lokalen Proxy; andere Pfade antworten mit HTTP 404. Ein erneuerter Key macht den alten sofort ungültig, sobald die Proxy-Konfiguration erfolgreich neu geladen ist.

Bestehende manuelle Keys aus `cloudflare_access_token` werden beim Upgrade importiert, sofern die alte Option noch in der gespeicherten Home-Assistant-Konfiguration vorhanden ist. Ist sie bei der Migration nicht mehr verfügbar, wird ein neuer Schlüssel erstellt und die Clients müssen aktualisiert werden.

### Tunnel-Verwaltung in der Home-Assistant-Weboberfläche

Im Bereich **Netzwerk & Tunnel** kannst Du beide Tunnel live aktivieren, deaktivieren und neu verbinden und siehst Prozessstatus und Startfehler. Die Zugangsdaten und Pfade werden weiter in der Home-Assistant-App-Konfiguration verwaltet; **Änderungen dort benötigen einen Neustart der App**. Die Ein-/Aus-Zustände aus der Weboberfläche werden dauerhaft unter `/data/tunnel_control.json` gespeichert und haben Vorrang vor den ursprünglichen Startwerten. Externe Konnektivität muss zusätzlich im jeweiligen Anbieter-Dashboard geprüft werden: ein laufender Prozess garantiert noch keine funktionierende Verbindung.

Für die Verwaltung ist eine authentifizierte Home-Assistant-Adminsession erforderlich. Der Verwaltungsserver ist ausschließlich an `127.0.0.1:8097` gebunden und nur über den geschützten Ingress-Zugang erreichbar; er wird weder via Cloudflare noch im LAN veröffentlicht.

### LAN-Zugriff

Unter Home Assistant → MCPHub → **Netzwerk** den gewünschten **Host-Port** eintragen, beispielsweise `3000`, oder einen anderen freien Port wählen. **Keinen Port eintragen, um den LAN-Zugriff zu deaktivieren.** Intern wird Port `3001/tcp` der App weitergereicht, niemals der ungeschützte MCPHub-Port `3000`.

Der LAN-Proxy erlaubt nur den eingestellten `lan_mcp_path` (Standard `/mcp`), verlangt denselben Client Key wie Cloudflare und blockiert das Web-Dashboard sowie sämtliche anderen API-Pfade. LAN-Verbindungen erfolgen über **HTTP, ohne TLS**; der Bearer Key ist auf einem kompromittierten LAN mitlesbar. Nur in vertrauenswürdigen Netzwerken verwenden, ansonsten HTTPS/Tunnel vorziehen. **Keine Router-Portfreigabe einrichten.**

### `cloudflare_tunnel_enabled`

Default: `false`

Enables the bundled Cloudflare Tunnel client.

### `cloudflare_tunnel_token`

Connector token for the remotely managed Cloudflare Tunnel.

Treat this value as a secret. Anyone with the connector token can run a connector for
that tunnel.

### `cloudflare_mcp_path`

Default: `/mcp`

Exact MCPHub route exposed through the local Cloudflare adapter.

For least privilege, prefer a focused group such as:

`/mcp/development`

### Automatisch verwalteter `mcphub_client_key`

Wird beim ersten Start kryptografisch sicher erstellt und dauerhaft in `/data/secrets/mcphub_client_key` gespeichert. Der Home-Assistant-Admin kann ihn in der Tunnel-Steuerung kopieren und erneuern. Keine manuelle Pflichtkonfiguration.

## Dashboard and local proxy architecture

MCPHub is patched to bind to `127.0.0.1:3000` inside the App container.

Nginx provides two local adapters:

- `8099` — Home Assistant Ingress, reachable only from the Supervisor Ingress gateway
- `127.0.0.1:8098` — Cloudflare origin, reachable only from processes inside the App

MCPHub dashboard authentication is not globally disabled. Instead, authenticated Home
Assistant Ingress requests carry the Home Assistant user identity plus a private
per-installation trust marker generated by the App.

The Cloudflare adapter explicitly removes all Home Assistant identity and trust headers
before proxying to MCPHub. This avoids a dangerous failure mode where a remote client or
misconfigured tunnel could impersonate a Home Assistant user or expose an
unauthenticated MCPHub dashboard/API.

## Authentication model

Home Assistant dashboard access and remote MCP transport use separate authentication
paths:

- Home Assistant Ingress uses the authenticated Home Assistant user identity plus a
  private local proxy trust secret.
- OpenAI Secure MCP Tunnel uses its own internal MCPHub bearer key.
- Cloudflare Tunnel uses a separate route-scoped internal MCPHub bearer key plus the
  configured remote-client key.

The OpenAI and Cloudflare internal keys are automatically scoped to the configured MCP
route whenever possible. Home Assistant Ingress does not reuse either tunnel credential.

The public Cloudflare client key is intentionally separate from the private MCPHub key.
Even if the public key is presented directly to MCPHub, it is not accepted as a
dashboard credential.

## Persistence

MCPHub configuration is stored below:

`/data/mcphub/`

Generated runtime secrets are stored below:

`/data/secrets/`

Package caches are persisted for dynamically launched MCP servers:

- npm / npx: `/data/cache/npm`
- uv / uvx: `/data/cache/uv`

## Adding MCP servers

The standard MCPHub image includes Node.js, Python, npm/pnpm, uv/uvx, Git, and build
tools. Many stdio MCP servers can therefore be installed and launched directly by MCPHub.

Remote SSE and Streamable HTTP MCP servers can be configured by URL. OpenAPI endpoints
can also be wrapped by MCPHub where appropriate.

### GitHub MCP

GitHub is intentionally not hard-coded into this Home Assistant App.

Search MCPHub's Market or Registry for the GitHub MCP implementation you want to use,
review its current upstream authentication instructions, and configure the required
credential in MCPHub.

## Optional GitHub CLI MCP

The App can manage an additional universal GitHub CLI MCP server without requiring a
custom Docker image. It is disabled by default.

### `github_cli_mcp_enabled`

Default: `false`

When enabled, the App adds the managed `ha-github-cli` stdio server to MCPHub. On its
first launch, the helper downloads the pinned GitHub CLI release for the current CPU
architecture, verifies its SHA-256 checksum, and stores it below `/data/tools/github-cli/`.
The installation survives App/container recreation because `/data` is persistent.

The MCP server itself is launched through `uvx` as `gh-cli-mcp-server==0.3.0`. The
existing persistent uv cache is reused.

### `github_token`

Optional GitHub Personal Access Token used as `GH_TOKEN` by GitHub CLI. Authenticated
access is required for private repositories and write operations. The App writes this
value to `/data/secrets/github_token` with mode `0600`; it is not copied into
`mcp_settings.json`.

If the integration is enabled without a token, the server still starts, but GitHub CLI
is limited to operations that work without authentication.

Disabling the option removes only the App-managed `ha-github-cli` entry. GitHub MCP
servers created manually under other names are not modified.

## Docker-based MCP servers

This App intentionally does not expose the Home Assistant Docker socket and does not run
in privileged mode.

MCP servers that strictly require launching their own Docker containers are therefore
not supported through host Docker access in this version.

## Backups

The App uses Home Assistant cold backups. The persistent `/data` directory contains the
MCPHub configuration and generated secrets required to restore the instance consistently.

Treat backups as sensitive because they may contain MCP server credentials and tunnel
configuration.

## Troubleshooting

### MCPHub exits during startup

Check the App log for the first MCPHub error. Configuration parsing and upstream package
failures normally appear before the wrapper reports that MCPHub exited.

### The Web UI does not open

Check that MCPHub reached the ready state and that Nginx started afterward.

The MCPHub dashboard is only available through Home Assistant **Web UI**. An optional LAN host port exposes solely the authenticated MCP endpoint, never the dashboard.

### Cloudflare Tunnel does not start

Verify that:

- `cloudflare_tunnel_enabled` is enabled
- the Cloudflare connector token is present
- the generated client key is available via **Netzwerk & Tunnel**
- the public hostname service points to `http://127.0.0.1:8098`
- the remote client URL includes the exact configured `cloudflare_mcp_path`

### The remote client receives 401

Verify that the client sends:

`Authorization: Bearer <your-client-key>`

and that the value exactly matches the automatically generated Client Key copied from the Home Assistant interface.

### The remote client receives 404

Verify that its URL path exactly matches `cloudflare_mcp_path`. The Cloudflare adapter
intentionally rejects every other path.

### A server fails to start

Open the server entry in MCPHub and inspect its logs.

For stdio servers, verify the package name, executable, environment variables, and
network access.

### The OpenAI tunnel does not start

Verify that:

- `tunnel_enabled` is enabled
- the OpenAI Runtime API Key is present
- the Tunnel ID is correct
- the selected `tunnel_mcp_path` exists
- MCPHub itself is healthy
