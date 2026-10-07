# Changelog

## [v2026.10.07-2] - 2026-10-07

### Fixed

- Fixed `ha-github-cli` crashing because `gh-cli-mcp-server` 0.3.0 declares `mcp[cli]>=1.0.0` but still imports the MCP Python SDK 1.x `FastMCP` API, allowing an incompatible MCP 2.x runtime to be resolved.
- Pinned the compatibility runtime to MCP Python SDK 1.30.0.

### Changed

- `gh-cli-mcp-server` and its compatible MCP Python SDK are now installed into the App image at build time instead of being resolved dynamically by `uvx` when MCPHub starts the stdio server.
- CI now verifies both pinned Python package versions and performs a startup smoke test for the bundled GitHub CLI MCP server.

## [v2026.10.07-1] - 2026-10-07

### Fixed

- Fixed `ha-github-cli` failing immediately on startup because the runtime bootstrap used SHA-256 values that did not match the official GitHub CLI 2.101.0 release assets.
- GitHub CLI is now bundled and verified while the App image is built instead of being downloaded when the stdio MCP server starts.

### Changed

- GitHub CLI remains pinned to 2.101.0 and is updated together with tested MCPHub App releases, avoiding unreviewed runtime upgrades.

## [v2026.10.07] - 2026-10-07

### Added

- Optional GitHub CLI MCP integration controlled from Home Assistant App options.
- Persistent, architecture-aware installation of GitHub CLI 2.101.0 with pinned SHA-256 verification.
- Automatic MCPHub registration of the managed `ha-github-cli` stdio server using `gh-cli-mcp-server` 0.3.0.
- Protected GitHub token handoff through `/data/secrets/github_token` instead of storing the token in `mcp_settings.json`.

### Changed

- Disabling the GitHub CLI MCP option now removes only the App-managed `ha-github-cli` entry and leaves user-managed GitHub servers untouched.

## [v2026.10.05] - 2026-10-05

### Added

- Home Assistant Ingress single sign-on using Supervisor-provided user identity headers.
- Optional Cloudflare Tunnel support through bundled `cloudflared` 2026.9.3.
- Independent Cloudflare MCP route selection.
- Separate remote-client access key for the Cloudflare endpoint.
- Loopback-only Cloudflare origin on `127.0.0.1:8098`.
- Route-level filtering so Cloudflare exposes only the configured MCP endpoint.

### Changed

- Switched MCPHub wrapper releases to CalVer using `vYYYY.MM.DD`; same-day releases use `-1`, `-2`, `-3`, and so on.
- MCPHub dashboard/API authentication is no longer disabled globally.
- Home Assistant Ingress now maps the authenticated Home Assistant user into MCPHub instead of using one shared dashboard bearer identity.
- OpenAI and Cloudflare internal MCPHub keys are scoped to the configured route whenever possible.
- Documentation now recommends MCPHub groups to limit tool discovery per AI client.

### Security

- Home Assistant identity headers are trusted only together with a private per-installation proxy secret injected by the local Ingress adapter.
- Cloudflare explicitly strips Home Assistant identity and trust headers before proxying remote MCP traffic.
- A misconfigured external tunnel can no longer expose an unauthenticated MCPHub dashboard/API.
- The Cloudflare client key is validated by the local proxy and is never registered as a dashboard credential.
- The Cloudflare origin rejects all paths except the explicitly configured MCP route.
- Cloudflare connector tokens are passed to `cloudflared` through a protected token file instead of the process command line.

## [0.2.0] - 2026-10-05

### Changed

- Moved MCPHub into the shared HyperCriSiS Home Assistant add-on repository.
- Simplified the visible App name to **MCPHub**.
- Simplified the technical slug to `mcphub`.
- Removed the dependency on separately published wrapper images; Home Assistant now
  builds the add-on directly from this repository like the other local add-ons.

### Added

- MCPHub 1.1.0 as the central MCP gateway and control plane.
- Home Assistant Ingress integration for the MCPHub dashboard.
- Optional OpenAI Secure MCP Tunnel integration.
- Persistent MCPHub configuration and npm/uv package caches.
- Persistent internal bearer authentication between the tunnel client and MCPHub.
- English and German Home Assistant option translations.
- Dedicated MCPHub validation and HAOS integration workflows.

### Security

- MCPHub is restricted to the container loopback interface.
- No Docker socket, privileged mode, host networking, Supervisor API, or Home Assistant
  API access is granted.
- MCP transport bearer authentication remains enabled even though dashboard
  authentication is delegated to Home Assistant Ingress.
