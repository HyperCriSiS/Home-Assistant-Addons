# MCPHub documentation

## About

This add-on runs MCPHub as a central control plane for MCP servers inside Home Assistant.

MCPHub can discover, configure, start, stop, group, monitor, and route multiple MCP
servers while exposing them through stable MCP endpoints.

The optional OpenAI Secure MCP Tunnel connects one selected MCPHub route to ChatGPT
without opening a router port or publishing MCPHub to the public internet.

## Installation

Add this repository to the Home Assistant App store:

`https://github.com/HyperCriSiS/Home-Assistant-Addons`

Install **MCPHub** and start it with the default configuration first. The OpenAI tunnel
is disabled by default so the dashboard can be verified independently.

## First start

1. Start **MCPHub**.
2. Open **Web UI** from the Home Assistant App page.
3. Use MCPHub's **Market**, **Registry**, or **Add Server** flow to configure MCP servers.
4. Verify that the selected servers connect successfully.
5. Enable the OpenAI tunnel only after MCPHub is working locally.

No additional MCPHub dashboard login is required. Home Assistant Ingress already
authenticates access to the dashboard.

## App configuration

### `tunnel_enabled`

Default: `false`

Enables the OpenAI Secure MCP Tunnel. MCPHub works normally while this option is disabled.

### `openai_runtime_api_key`

OpenAI Runtime API Key used by the Secure MCP Tunnel client.

Use a dedicated runtime key with only the permissions required for the tunnel. Do not
reuse unrelated administrator credentials.

### `tunnel_id`

The OpenAI Secure MCP Tunnel ID.

### `tunnel_mcp_path`

Default: `/mcp`

Selects the MCPHub route exposed through the tunnel.

Common routes include:

- `/mcp` — all enabled and permitted servers
- `/mcp/<group>` — one MCPHub group
- `/mcp/<server>` — one server
- `/mcp/$smart` — MCPHub Smart Routing

### `tunnel_log_level`

Default: `info`

Allowed values are `debug`, `info`, and `warn`.

Raw HTTP logging remains disabled so Authorization headers are not intentionally written
to the App log.

## Dashboard and Ingress

MCPHub is patched to bind to `127.0.0.1:3000` inside the App container.

A dedicated Nginx adapter listens on the Home Assistant Ingress port and accepts traffic
only from the Home Assistant Ingress gateway.

This design keeps MCPHub off the Home Assistant host network while still providing the
normal **Web UI** button and sidebar panel.

## Authentication model

Dashboard authentication and MCP transport authentication are deliberately separate.

### Dashboard

MCPHub dashboard authentication is skipped because Home Assistant Ingress authenticates
the Home Assistant user before forwarding the request.

### MCP transport

Bearer authentication remains enabled for MCP endpoints.

On first start, the App creates a long random bearer token and stores it in the persistent
App data directory. It is registered in MCPHub as:

`Home Assistant OpenAI Tunnel`

The OpenAI tunnel client uses this token only for the local connection from the tunnel
process to MCPHub.

Do not permanently delete this key from MCPHub. If it is deleted, the App recreates it
on the next restart.

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

## Docker-based MCP servers

This App intentionally does not expose the Home Assistant Docker socket and does not run
in privileged mode.

MCP servers that strictly require launching their own Docker containers are therefore
not supported through host Docker access in this version.

## Backups

The App uses Home Assistant cold backups. The persistent `/data` directory contains the
MCPHub configuration and generated secrets required to restore the instance consistently.

Treat backups as sensitive because they may contain MCP server credentials.

## Troubleshooting

### MCPHub exits during startup

Check the App log for the first MCPHub error. Configuration parsing and upstream package
failures normally appear before the wrapper reports that MCPHub exited.

### The Web UI does not open

Check that MCPHub reached the ready state and that Nginx started afterward.

The App intentionally does not publish a normal host port; use Home Assistant **Web UI**
instead of trying to browse directly to port 3000 or 8099.

### A server fails to start

Open the server entry in MCPHub and inspect its logs.

For stdio servers, verify the package name, executable, environment variables, and
network access.

### The ChatGPT tunnel does not start

Verify that:

- `tunnel_enabled` is enabled
- the OpenAI Runtime API Key is present
- the Tunnel ID is correct
- the selected `tunnel_mcp_path` exists
- MCPHub itself is healthy
