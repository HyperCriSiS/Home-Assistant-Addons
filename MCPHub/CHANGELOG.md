# Changelog

## v2026.10.17-1

- Simplify LAN port configuration label; blank host port still disables direct LAN access.
- Automatically generate and persist Cloudflare remote MCP client key, migrating existing keys.
- Add copy and confirmed rotation to protected Ingress tunnel management; retain independent tunnel lifecycle and health.
- Update cloudflared to 2026.10.1, OpenAI tunnel client to v0.0.16; keep MCPHub upstream 1.1.5.
- Prepare a separate, Ingress-only tunnel dashboard with one card each for OpenAI, Cloudflare, and Tailscale Funnel; remove the injected control from upstream MCPHub's header.
- Add optional Tailscale MCP-only gateway (host port off by default), independent scoped keys, local gateway Start/Stop and rotation; the existing Tailscale Add-on continues to own Funnel.
- Reject unsafe dot-segment MCP routes across all tunnel gateways and preserve the original Dev Store title and README.


## v2026.10.16

### Changed

- Updated MCPHub from 1.1.3 to 1.1.5.

## v2026.10.12-1

### Added

- Grouped Home Assistant App settings into OpenAI, Cloudflare, Home Assistant MCP, GitHub CLI, and logging sections, with updated English and German translations.
- Linked directly to OpenAI Runtime API key and Tunnel ID setup from the configuration guidance.
- Added a supervisor for the OpenAI Secure MCP Tunnel with liveness and readiness checks, automatic restart after prolonged failures, and backoff between retries.
- Added an Ingress-only OpenAI tunnel control page with connection status and Start, Stop, and Reload actions, without restarting MCPHub.
- Added configurable names for the managed Home Assistant MCP server, including safe rename and name-collision handling.

### Changed

- Updated MCPHub from 1.1.1 to 1.1.3.
- Showed the bundled MCPHub upstream version in the Home Assistant App description.
- Allowed reachable LAN IPv4/IPv6 addresses, custom ports, and HTTPS hostnames with SNI for the managed Home Assistant MCP bridge.
- Updated the MCPHub SVG wordmark and README logo positioning for consistent centering across browsers.

### Fixed

- Generated a separate development changelog from Git commits and retained previous Dev entries and human-written notes.
- Prepared comprehensive Stable notes from every MCPHub change since the previous `main` release and added a pre-merge completeness check.

- Verify Home Assistant MCP HTTPS certificates and hostnames, retaining certificate-free LAN HTTP and supporting trusted private CA files.
- Isolate invalid or disabled OpenAI and Cloudflare tunnel settings so MCPHub and Ingress remain available.
- Execute URL security assertions in CI and rebuild and verify the exact tested HAOS image revision.

- Prevented optional OpenAI and Cloudflare tunnel failures, and an invalid OpenAI Tunnel ID, from shutting down MCPHub and Home Assistant Ingress.
- Preserved an existing GitHub CLI token when its option is empty or the managed integration is disabled.
- Kept runtime option readers compatible with both legacy flat and new grouped settings.

### Security

- Restricted OpenAI tunnel controls to the local Ingress adapter; tunnel credentials are not exposed by its status endpoint.

### Upgrade notes

- Home Assistant may not migrate saved App options when the option structure changes to groups. Check the OpenAI, Cloudflare, Home Assistant, and GitHub settings after upgrading; re-enter missing values before enabling affected integrations.

## v2026.10.12

### Added

- Added an optional managed Home Assistant MCP Server bridge.
- Added selectable Home Assistant MCP authentication using either the automatic Supervisor token or a dedicated Home Assistant user token.
- Added a Home Assistant Supervisor watchdog for the MCPHub Ingress health endpoint.

### Security

- The managed Home Assistant MCP bridge is loopback-only and never exposes the Home Assistant token through MCPHub settings.
- Dedicated-user mode can use a non-admin Home Assistant account for a narrower runtime identity.

## v2026.10.07-4

### Changed

- Updated MCPHub from 1.1.0 to 1.1.1.
- Moved the OpenAI Tunnel log-level option to the end of the Home Assistant App configuration.

### Fixed

- Fixed Home Assistant Ingress SSO falling back to MCPHub's local login when optional Supervisor user-name headers are unavailable.

## v2026.10.07-3

### Fixed

- Fixed Home Assistant Ingress-created MCP servers being stored with a synthetic Home Assistant username instead of the MCPHub `admin` owner.
- Existing affected servers can be repaired by saving them again through Home Assistant Ingress.

## v2026.10.07-2

### Fixed

- Fixed `ha-github-cli` startup failures caused by an incompatible MCP Python SDK version.
- Pinned the compatible MCP Python SDK runtime to 1.30.0.

### Changed

- Bundled `gh-cli-mcp-server` and its compatible MCP Python SDK in the App image instead of resolving them when the server starts.

## v2026.10.07-1

### Fixed

- Fixed `ha-github-cli` failing to start because the GitHub CLI runtime bootstrap used invalid release-asset checksums.

### Changed

- Bundled GitHub CLI 2.101.0 in the App image instead of downloading it at runtime.

## v2026.10.07

### Added

- Added an optional managed GitHub CLI MCP server named `ha-github-cli`.
- Added GitHub token handling through `/data/secrets/github_token` instead of storing the token in MCPHub settings.

### Changed

- Disabling the GitHub CLI MCP option removes only the App-managed `ha-github-cli` server and leaves user-managed GitHub servers untouched.

## v2026.10.05

### Added

- Added Home Assistant Ingress single sign-on.
- Added optional Cloudflare Tunnel support with a dedicated MCP route and remote-client access key.

### Changed

- Switched MCPHub App releases to CalVer using `vYYYY.MM.DD`, with same-day releases using numeric suffixes.
- Kept MCPHub dashboard and API authentication enabled while mapping authenticated Home Assistant users through Ingress.
- Scoped internal OpenAI and Cloudflare access keys to the configured MCP route where possible.

### Security

- Home Assistant identity headers are accepted only together with the private per-installation Ingress proxy secret.
- Cloudflare removes Home Assistant identity headers and exposes only the configured MCP route.
- Cloudflare connector tokens are passed through a protected token file instead of the process command line.

## v0.2.0

### Added

- Added MCPHub 1.1.0 as the central MCP gateway and control plane.
- Added Home Assistant Ingress support.
- Added optional OpenAI Secure MCP Tunnel support.
- Added persistent MCPHub configuration and package caches.
- Added English and German Home Assistant option translations.

### Changed

- Moved MCPHub into the shared HyperCriSiS Home Assistant Apps repository.
- Simplified the visible App name to MCPHub and the technical slug to `mcphub`.
- Switched to building the Home Assistant App directly from this repository.

### Security

- MCPHub runs without the Docker socket, privileged mode, host networking, Supervisor API access, or Home Assistant API access.
- MCP transport bearer authentication remains enabled when dashboard authentication is delegated to Home Assistant Ingress.
