<div align="center">

<img src="https://raw.githubusercontent.com/HyperCriSiS/Home-Assistant-Apps/dev-mcphub/MCPHub/logo.svg" alt="MCPHub" width="320">

# MCPHub

**Manage multiple MCP servers from one central dashboard inside Home Assistant.**

[![Validate MCPHub](https://github.com/HyperCriSiS/Home-Assistant-Apps/actions/workflows/validate-mcphub.yml/badge.svg?branch=main)](https://github.com/HyperCriSiS/Home-Assistant-Apps/actions/workflows/validate-mcphub.yml)
![Architecture amd64](https://img.shields.io/badge/amd64-supported-success)
![Architecture aarch64](https://img.shields.io/badge/aarch64-supported-success)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-App-41BDF5?logo=homeassistant&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-blue)

</div>

MCPHub runs [MCPHub](https://github.com/samanhappy/mcphub) as a Home Assistant App and provides a central control plane for Model Context Protocol servers.

It supports MCPHub Market / Registry discovery, local stdio servers, remote MCP servers, persistent configuration and package caches, Home Assistant Ingress, and an optional OpenAI Secure MCP Tunnel for connecting MCPHub to ChatGPT without exposing MCPHub directly to the public internet.

> [!IMPORTANT]
> Home Assistant Apps require **Home Assistant OS** or a **Supervised** installation. Older Home Assistant versions may still use the term **Add-ons** instead of **Apps**.

## Installation

### Stable

[![Add stable repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Apps)

If the button opens the App store without showing the repository dialog, add it manually:

```text
https://github.com/HyperCriSiS/Home-Assistant-Apps
```

Existing users who added the former `Home-Assistant-Addons` repository should keep that repository entry. Do not add both old and new URLs to the same Home Assistant instance: they are treated as separate repository IDs.

Then search for **MCPHub**, install it, start it with the default configuration, and open **Web UI**.

### Development testing

To test the current `dev-mcphub` candidate before it is promoted to `main`, add the shared generated
development store:

[![Add development repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Apps%23dev-store)

```text
https://github.com/HyperCriSiS/Home-Assistant-Apps#dev-store
```

The development App is shown as **MCPHub (Dev)** under
**HyperCriSiS Apps (Dev)**, so it can be distinguished from the stable App at a glance.

> [!WARNING]
> Development builds may contain incomplete or breaking changes. Use the stable repository
> for normal production use.

## Features

- Central MCP server management through MCPHub
- MCPHub Market / Registry discovery
- Local stdio MCP servers
- Remote SSE and Streamable HTTP MCP servers
- Persistent MCPHub configuration
- Persistent npm / npx and uv / uvx package caches
- Home Assistant Ingress dashboard
- Optional managed Home Assistant MCP Server bridge
- Bundled GitHub CLI (`gh`) for `amd64` / `aarch64` with an optional managed GitHub CLI MCP server
- Optional OpenAI Secure MCP Tunnel for ChatGPT / OpenAI clients
- Optional Cloudflare Tunnel for Claude, Cursor, VS Code, and other remote MCP clients
- No public MCPHub port required
- No Home Assistant Docker socket access
- No privileged mode
- No host networking
- No Supervisor API permission
- Home Assistant cold-backup support
- `amd64` and `aarch64` support

## Home Assistant MCP Server

The App can optionally add Home Assistant's own MCP Server to MCPHub as the
managed server **ha-home-assistant** by default. The server name is configurable
through `home_assistant_mcp_server_name` in the App options. The Home Assistant
**MCP Server** integration must already be configured.

Two authentication modes are available:

- **supervisor** â zero-token setup. The App uses the Supervisor-provided Core
  API token and the internal Home Assistant API proxy.
- **restricted_user** â the default and recommended mode when MCP requests
  should run as a dedicated non-admin Home Assistant user. Sign in as that user,
  create a Long-Lived Access Token from the user's profile, and enter the token
  in the App configuration.

The managed server talks only to a loopback proxy inside the MCPHub App.
Home Assistant credentials are injected by that proxy and are never written
into MCPHub's `mcp_settings.json`.

> [!IMPORTANT]
> Supporting the automatic Supervisor mode requires the static
> `homeassistant_api: true` App permission. Selecting `restricted_user`
> changes the credential actually used for MCP requests, but it does not remove
> that static container capability. A truly permission-isolated variant would
> require a separate App package without `homeassistant_api`.

For a dedicated user, the default MCP URL is
`http://homeassistant:8123/api/mcp`. The URL is fully configurable and is not
tied to the Home Assistant Ingress address. You can use a reachable LAN address
or local DNS name, for example `http://192.168.1.20:8123/api/mcp`,
`http://10.0.0.20:8123/api/mcp`, `http://172.20.1.20:8123/api/mcp`, an IPv6
address, or an HTTPS hostname.

The App validates the URL but does not restrict it to a particular private
subnet. For local DNS names, make sure the name resolves from the Home Assistant
App network; mDNS-only names such as `*.local` may not resolve inside every
container environment. Home Assistant may require an administrator token for
MCP APIs other than the built-in Assist API.

## Remote access

MCPHub supports two independent remote-access paths. Both are optional and can be enabled at the same time.

### ChatGPT through OpenAI Secure MCP Tunnel

The optional tunnel lets ChatGPT reach MCPHub without publishing MCPHub to the internet.

The connection is outbound-only from the App:

```text
ChatGPT
   â
   â¼
OpenAI Secure MCP Tunnel
   â²
   â outbound HTTPS
   â
Home Assistant
âââ MCPHub
    âââ 127.0.0.1:3000
```

No router port forwarding, public reverse proxy, public MCPHub URL, or Cloudflare Tunnel is required for this setup.

Get the **Runtime API Key** from [OpenAI API keys](https://platform.openai.com/settings/organization/api-keys)
(select **Restricted** with **Tunnels: Read + Use**).
Find the separate **Tunnel ID** in [OpenAI Tunnel settings](https://platform.openai.com/settings/organization/tunnels).
It starts with `tunnel_`. Do not use the API key's Tracking ID.

See [DOCS.md](DOCS.md) for the complete OpenAI tunnel configuration.

### Generic remote MCP through Cloudflare Tunnel

Cloudflare Tunnel exposes one explicitly selected MCPHub route through a normal HTTPS hostname. This is useful for Claude, Cursor, VS Code, and other clients that support remote Streamable HTTP MCP.

The App runs a loopback-only Cloudflare origin on `127.0.0.1:8098`. That adapter exposes exactly the configured `cloudflare_mcp_path`; all other paths return 404. Remote clients must also provide the configured client key.

For the smallest tool surface, create a focused MCPHub group and expose only that group:

```text
/mcp/development
/mcp/home
/mcp/web
```

This prevents clients from discovering every server and tool in MCPHub at once.

See [DOCS.md](DOCS.md) for the Cloudflare setup.

## Security model

MCPHub itself binds only to the App container loopback interface.

The fixed `172.30.32.2` allow rule on the Ingress listener is the Home
Assistant-documented Supervisor Ingress source inside the managed App network;
it is not a user-specific LAN address. User LAN addressing is relevant only for
the optional direct Home Assistant MCP URL in `restricted_user` mode.

The dashboard is exposed through a dedicated Home Assistant Ingress adapter. The App does not publish MCPHub directly on the Home Assistant host network.

Home Assistant Ingress provides single sign-on for the dashboard. The Supervisor-provided Home Assistant user identity is mapped into MCPHub only when the request also carries a private per-installation proxy trust secret injected by the local Ingress adapter.

MCP transport authentication remains independent from Home Assistant Ingress. OpenAI and Cloudflare each use their own route-scoped internal credentials. The public Cloudflare client key is validated by the local adapter and is never registered as a dashboard credential in MCPHub.

Secrets, MCPHub configuration, and package caches are stored in the persistent App data directory and are included in Home Assistant cold backups.

> [!WARNING]
> Backups can contain MCP server credentials and generated secrets. Treat Home Assistant backups as sensitive data.

## Configuration

The Home Assistant App configuration contains Home Assistant MCP and remote-access options:

| Option | Default | Description |
| --- | --- | --- |
| `home_assistant_mcp_enabled` | `false` | Adds the managed Home Assistant MCP Server to MCPHub |
| `home_assistant_mcp_server_name` | `ha-home-assistant` | Unique MCPHub server name; renaming migrates the managed entry |
| `home_assistant_mcp_auth_mode` | `restricted_user` | Uses either the Supervisor token or a dedicated user token |
| `home_assistant_mcp_user_token` | empty | Dedicated Home Assistant user's Long-Lived Access Token |
| `home_assistant_mcp_url` | `http://homeassistant:8123/api/mcp` | Direct MCP endpoint used by `restricted_user` mode |
| `github_cli_mcp_enabled` | `false` | Adds the bundled GitHub CLI MCP server to MCPHub |
| `github_token` | empty | Optional GitHub token supplied as `GH_TOKEN` to the CLI |
| `tunnel_enabled` | `false` | Enables the OpenAI Secure MCP Tunnel |
| `openai_runtime_api_key` | empty | Runtime API Key used by the tunnel client |
| `tunnel_id` | empty | Tunnel ID (`tunnel_...`) from [OpenAI Tunnel settings](https://platform.openai.com/settings/organization/tunnels); not the API key Tracking ID |
| `tunnel_mcp_path` | `/mcp` | MCPHub route exposed through the tunnel |
| `tunnel_log_level` | `info` | OpenAI tunnel log verbosity |
| `cloudflare_tunnel_enabled` | `false` | Enables Cloudflare Tunnel |
| `cloudflare_tunnel_token` | empty | Connector token for a remotely managed Cloudflare Tunnel |
| `cloudflare_mcp_path` | `/mcp` | Exact MCPHub route exposed through Cloudflare |
| `cloudflare_access_token` | empty | Client key required from remote MCP clients |

MCP server configuration itself is managed from the MCPHub Web UI. Changing
`home_assistant_mcp_server_name` removes the old managed entry; update any
MCPHub groups or client routes that referred to its previous name.

For detailed configuration, security notes, persistence paths, backups, and troubleshooting, see:

**[Full MCPHub App documentation â](DOCS.md)**

## Versioning

MCPHub wrapper releases use calendar versioning:

```text
vYYYY.MM.DD
```

If more than one release is published on the same day, subsequent releases append a
numeric suffix:

```text
v2026.10.05
v2026.10.05-1
v2026.10.05-2
```

Development-store builds keep the same release base and add a temporary
`-dev.<build>` suffix.

## Updating

Home Assistant detects new App versions from this repository.

Before updating:

1. Review [CHANGELOG.md](CHANGELOG.md).
2. Create a Home Assistant backup if the update contains major changes.
3. Update MCPHub from the App page.

## Support

For issues with this Home Assistant wrapper, open an issue in:

[HyperCriSiS/Home-Assistant-Apps](https://github.com/HyperCriSiS/Home-Assistant-Apps/issues)

For MCPHub application issues, use the upstream project:

[samanhappy/mcphub](https://github.com/samanhappy/mcphub)

For OpenAI Secure MCP Tunnel issues, use:

[openai/tunnel-client](https://github.com/openai/tunnel-client)

## Licenses

The Home Assistant wrapper is released under the [MIT License](LICENSE).

Third-party components retain their own licenses. See [NOTICE.md](NOTICE.md) for details.
