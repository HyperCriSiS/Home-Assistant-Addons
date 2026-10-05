# Changelog

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
