<div align="center">

<img src="logo.png" alt="MCPHub" width="320">

# MCPHub

**Manage multiple MCP servers from one central dashboard inside Home Assistant.**

[![Validate MCPHub](https://github.com/HyperCriSiS/Home-Assistant-Addons/actions/workflows/validate-mcphub.yml/badge.svg?branch=main)](https://github.com/HyperCriSiS/Home-Assistant-Addons/actions/workflows/validate-mcphub.yml)
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

[![Add stable repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Addons)

If the button opens the App store without showing the repository dialog, add it manually:

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons
```

Then search for **MCPHub**, install it, start it with the default configuration, and open **Web UI**.

### Development testing

To test the current `dev` branch before it is promoted to `main`, add the generated
development store:

[![Add development repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Addons%23dev-store)

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons#dev-store
```

The development App is shown as **MCPHub (Dev)** under
**HyperCriSiS Add-ons (Dev)**, so it can be distinguished from the stable App at a glance.

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
- Optional OpenAI Secure MCP Tunnel
- No public MCPHub port required
- No Home Assistant Docker socket access
- No privileged mode
- No host networking
- No Supervisor API permission
- No Home Assistant API permission
- Home Assistant cold-backup support
- `amd64` and `aarch64` support

## ChatGPT through OpenAI Secure MCP Tunnel

The optional tunnel lets ChatGPT reach MCPHub without publishing MCPHub to the internet.

The connection is outbound-only from the App:

```text
ChatGPT
   │
   ▼
OpenAI Secure MCP Tunnel
   ▲
   │ outbound HTTPS
   │
Home Assistant
└── MCPHub
    └── 127.0.0.1:3000
```

No router port forwarding, public reverse proxy, public MCPHub URL, or Cloudflare Tunnel is required for this setup.

Enable the tunnel only after creating an OpenAI Secure MCP Tunnel and obtaining its Runtime API Key and Tunnel ID.

See [DOCS.md](DOCS.md) for the complete tunnel configuration.

## Security model

MCPHub itself binds only to the App container loopback interface.

The dashboard is exposed through a dedicated Home Assistant Ingress adapter. The App does not publish MCPHub directly on the Home Assistant host network.

MCP transport authentication remains enabled independently from Home Assistant Ingress. A dedicated persistent bearer token is generated for the local connection between the OpenAI tunnel client and MCPHub.

Secrets, MCPHub configuration, and package caches are stored in the persistent App data directory and are included in Home Assistant cold backups.

> [!WARNING]
> Backups can contain MCP server credentials and generated secrets. Treat Home Assistant backups as sensitive data.

## Configuration

The Home Assistant App configuration contains only tunnel-related options:

| Option | Default | Description |
| --- | --- | --- |
| `tunnel_enabled` | `false` | Enables the OpenAI Secure MCP Tunnel |
| `openai_runtime_api_key` | empty | Runtime API Key used by the tunnel client |
| `tunnel_id` | empty | OpenAI Secure MCP Tunnel ID |
| `tunnel_mcp_path` | `/mcp` | MCPHub route exposed through the tunnel |
| `tunnel_log_level` | `info` | Tunnel log verbosity |

MCP server configuration itself is managed from the MCPHub Web UI.

For detailed configuration, security notes, persistence paths, backups, and troubleshooting, see:

**[Full MCPHub App documentation →](DOCS.md)**

## Updating

Home Assistant detects new App versions from this repository.

Before updating:

1. Review [CHANGELOG.md](CHANGELOG.md).
2. Create a Home Assistant backup if the update contains major changes.
3. Update MCPHub from the App page.

## Support

For issues with this Home Assistant wrapper, open an issue in:

[HyperCriSiS/Home-Assistant-Addons](https://github.com/HyperCriSiS/Home-Assistant-Addons/issues)

For MCPHub application issues, use the upstream project:

[samanhappy/mcphub](https://github.com/samanhappy/mcphub)

For OpenAI Secure MCP Tunnel issues, use:

[openai/tunnel-client](https://github.com/openai/tunnel-client)

## Licenses

The Home Assistant wrapper is released under the [MIT License](LICENSE).

Third-party components retain their own licenses. See [NOTICE.md](NOTICE.md) for details.
