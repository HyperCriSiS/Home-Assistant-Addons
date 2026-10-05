# Changelog

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
