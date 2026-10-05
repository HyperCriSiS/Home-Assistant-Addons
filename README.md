# HyperCriSiS Add-ons

Home Assistant add-ons maintained by HyperCriSiS.

## MCPHub

**MCPHub** provides a central control plane for MCP servers inside Home Assistant.

It includes a Home Assistant Ingress dashboard, persistent MCPHub configuration,
support for dynamically launched stdio MCP servers, and an optional OpenAI Secure
MCP Tunnel for connecting one unified MCP endpoint to ChatGPT without exposing
MCPHub directly to the public internet.

See [MCPHub/README.md](MCPHub/README.md) for installation and
[MCPHub/DOCS.md](MCPHub/DOCS.md) for configuration, security, and troubleshooting.

## Trilium Notes

This repository provides **Trilium Notes for Home Assistant**, based on
[TriliumNext/Trilium](https://github.com/TriliumNext/Trilium).

The add-on supports Home Assistant Ingress, persistent add-on storage, a Supervisor
watchdog, `amd64` and `aarch64`, and a restricted trusted reverse-proxy configuration
for Home Assistant Ingress.

See [TriliumNext Notes/README.md](TriliumNext%20Notes/README.md) for installation,
configuration, backups, networking, and troubleshooting.

## Development and releases

Development changes are committed to `dev`. Validation must pass before the repository
promotion workflow opens or updates the release pull request from `dev` to `main`.

Each add-on has its own application-specific validation workflow. Shared repository
linting still runs across all YAML and GitHub Actions files.

## Support

For add-on-specific problems, open an issue in this repository. For application-level
issues, use the corresponding upstream project.
