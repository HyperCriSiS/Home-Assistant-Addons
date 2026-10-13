# MCPHub documentation

## About

This add-on runs MCPHub as a central control plane for MCP servers inside Home Assistant.

MCPHub can discover, configure, start, stop, group, monitor, and route multiple MCP
servers while exposing them through stable MCP endpoints.

A managed Home Assistant MCP bridge is also available. It can connect MCPHub
back to Home Assistant's own MCP Server without storing the Home Assistant
credential in MCPHub.

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

## Home Assistant MCP Server

The wrapper registers its managed MCPHub server under
`home_assistant_mcp_server_name` (default: `ha-home-assistant`). When enabled,
MCPHub connects to a loopback-only Nginx
bridge on `127.0.0.1:8097`; that bridge forwards Streamable HTTP requests to
Home Assistant and injects the selected Home Assistant credential.

The Home Assistant **MCP Server** integration must already be configured. The
wrapper intentionally does not create Home Assistant users, authentication
entries, or config entries through undocumented internal APIs.

### Authentication mode: `restricted_user` (default)

Use this mode when MCP requests should run as a dedicated Home Assistant user.

1. Create a dedicated **non-admin** Home Assistant user.
2. Sign in as that user in a separate/private browser session.
3. Open that user's profile and create a Long-Lived Access Token.
4. Enable `home_assistant_mcp_enabled`.
5. Set `home_assistant_mcp_auth_mode` to `restricted_user`.
6. Paste the token into `home_assistant_mcp_user_token`.
7. Keep `home_assistant_mcp_url` at its default unless the internal Home
   Assistant HTTP endpoint differs.

The default URL is:

```text
http://homeassistant:8123/api/mcp
```

The direct URL is not tied to any particular LAN subnet. Any Home Assistant MCP
endpoint reachable from the App network can be used, including addresses in
`192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, IPv6, or a resolvable
local DNS hostname. Non-default ports and HTTPS are supported. For HTTPS
hostnames the proxy enables SNI.

Prefer a normal LAN IP or DNS name that resolves from containers. An mDNS-only
`*.local` hostname is not guaranteed to resolve in every Home Assistant App
network.

Home Assistant's built-in Assist MCP API can be used by non-admin users.
Other MCP APIs may require an administrator token depending on the API exposed
by the Home Assistant MCP Server integration.

### Authentication mode: `supervisor`

This mode requires no manually created user token. The wrapper forwards to:

```text
http://supervisor/core/api/mcp
```

and injects the `SUPERVISOR_TOKEN` supplied by Home Assistant.

> [!IMPORTANT]
> The `homeassistant_api: true` permission required for Supervisor mode is an
> App-manifest capability and cannot be toggled dynamically from App options.
> Therefore `restricted_user` controls the credential used by the managed MCP
> bridge but does not revoke the container's static Home Assistant API
> capability. True container-level least privilege would require a separate
> MCPHub App variant without that permission.

### Managed-server behavior

- The default MCPHub server name is `ha-home-assistant`; configure a distinct name
  with `home_assistant_mcp_server_name` using 1-64 letters, digits, dots,
  underscores, or hyphens, beginning with a letter or digit.
- Renaming or disabling removes the previous managed entry, including entries
  created by older versions of the App. Existing MCPHub groups or routes
  referencing the old name must be updated manually after a rename.
- Name conflicts with existing user-created servers are rejected rather than
  overwriting those servers.
- The Home Assistant token is injected by the local proxy and is not written to
  `mcp_settings.json`.
- The local bridge listens only on `127.0.0.1:8097`.

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

### Live tunnel controls and automatic recovery

The OpenAI tunnel is supervised separately from MCPHub. Open the MCPHub Web UI
through Home Assistant Ingress and append `/_mcphub_tunnel/` to its browser URL.
For example, if the Ingress page ends in `/api/hassio_ingress/<session>/`, open
`/api/hassio_ingress/<session>/_mcphub_tunnel/` on the same Home Assistant host.
The control page provides **Start**, **Stop**, and **Reload** without restarting
MCPHub itself. Access is restricted to the Home Assistant Ingress adapter.

- The App starts the tunnel automatically if `tunnel_enabled` is true.
- **Stop** pauses it for the running App session; the configured setting remains
  unchanged and takes effect after an App restart.
- **Reload** rereads the current App options, including the Runtime API Key,
  without exposing the credentials to the page.
- The manager checks `/healthz` and `/readyz` every five seconds. A running
  but temporarily unready client is allowed to recover on its own. If its
  process exits, its liveness fails for one minute, or its readiness stays
  unavailable for ten minutes, it retries after exponential backoff (maximum
  five minutes). An invalid/missing credential suspends retries until an
  operator corrects the configuration and presses **Reload**.
- Tunnel failure or restart does not stop MCPHub's Ingress dashboard or local
  MCP servers. OpenAI connection availability is distinct from MCPHub health.
- Changes to the MCP path may require an App restart to regenerate MCPHub's
  own bearer-key scope; live reload only changes the tunnel client itself.

The tunnel manager binds `127.0.0.1:8096`. The OpenAI client's native health
listener is `127.0.0.1:8080`. Neither address is exposed directly through the
Home Assistant host or the Cloudflare tunnel. The control page and JSON API
contain no API keys, Tunnel IDs, or user tokens.

## Cloudflare Tunnel

Cloudflare Tunnel provides a normal public HTTPS endpoint for remote MCP clients while
MCPHub itself remains private inside the Home Assistant App container.

The App uses `cloudflared` only for outbound tunnel connectivity. No router port
forwarding is required.

### Cloudflare setup

1. Create a remotely managed Cloudflare Tunnel in the Cloudflare dashboard.
2. Add a public hostname such as `mcp.example.com`.
3. Set the hostname service to:

   ```text
   http://127.0.0.1:8098
   ```

4. Copy the tunnel connector token from Cloudflare.
5. Create a separate random client key with 32-256 characters using only letters,
   numbers, underscores, or dashes.
6. Configure the Home Assistant App options below and restart MCPHub.
7. Configure the remote MCP client with the public URL plus the selected route, for
   example:

   ```text
   https://mcp.example.com/mcp/development
   ```

8. Configure the remote client to send:

   ```text
   Authorization: Bearer <your-client-key>
   ```

The Cloudflare hostname may route all HTTP paths to port 8098. The local adapter still
serves only the exact configured MCP route and returns 404 for every other path.

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

### `cloudflare_access_token`

Required when Cloudflare Tunnel is enabled.

This is a separate client key chosen by you. Remote MCP clients must send it in the
`Authorization` header. It is validated by the local proxy and is not registered as a
dashboard credential in MCPHub.

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

When enabled, the App registers the managed `ha-github-cli` stdio server in MCPHub.
The App image already bundles GitHub CLI (`gh` version `2.101.0`) for `amd64` and
`aarch64`. The release archive is downloaded and SHA-256 verified during the
Docker image build, not when the MCP server starts.

The `gh-cli-mcp-server==0.3.0` package and its pinned `mcp==1.30.0` Python SDK
are also installed at image-build time in `/opt/gh-cli-mcp/`. The helper launches
the preinstalled MCP server directly, without `uvx` resolution or runtime
package downloads.

Only the GitHub CLI configuration is persisted in `/data/tools/github-cli/config/`.
The `gh` binary and MCP server environment are part of the App image and are
updated with the image, rather than stored in `/data`.

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

The App intentionally does not publish a normal host port; use Home Assistant **Web UI**
instead of browsing directly to port 3000 or 8099.

### Cloudflare Tunnel does not start

Verify that:

- `cloudflare_tunnel_enabled` is enabled
- the Cloudflare connector token is present
- the client key matches the documented character requirements
- the public hostname service points to `http://127.0.0.1:8098`
- the remote client URL includes the exact configured `cloudflare_mcp_path`

### The remote client receives 401

Verify that the client sends:

`Authorization: Bearer <your-client-key>`

and that the value exactly matches `cloudflare_access_token`.

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

## Development changelog and stable promotion

The development store builds the MCPHub App from `dev-mcphub` and gives it an
independently increasing `-dev.N` version. These development revisions do not
create new source `CHANGELOG.md` headings: their changes must be documented
under the current App wrapper version in `MCPHub/CHANGELOG.md`.

When merging user-visible App changes into `dev-mcphub`, update the current
changelog entry with the actual new features, fixes, security changes, and any
migration caveats. The upstream-update script records the upstream image bump;
it cannot describe unrelated App wrapper changes made between upstream releases.

Before promoting `dev-mcphub` to `main`, compare the candidate with the
**currently released** MCPHub App on `main` and review all intervening
changelog entries. Ensure the next stable release notes cover the full change
set, including previously shipped development-only features, while retaining
existing release history. Passing CI and a correct changelog version header
alone do not establish that the notes are complete.
