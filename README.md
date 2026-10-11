# HyperCriSiS Add-ons

Home Assistant add-ons maintained by HyperCriSiS.

## Install repository

### Stable

[![Add stable repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Addons)

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons
```

### Development

The development store is generated automatically from the validated `dev` branch and
is intended for testing before changes are promoted to `main`.

[![Add development repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Addons%23dev-store)

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons#dev-store
```

Home Assistant shows the development repository as **HyperCriSiS Add-ons (Dev)**.
Development Apps are named **MCPHub (Dev)** and **Trilium Notes (Dev)** and receive
an automatically generated development version on every sync.

> [!WARNING]
> Development builds may contain incomplete or breaking changes. Keep backups before
> testing updates and do not use the development store as your only production source.

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

Development changes are committed to `dev`. Every push to `dev` regenerates the
`dev-store` branch with clearly labeled Home Assistant metadata.

Validation must pass before changes are promoted from `dev` to `main`. The
`dev-store` branch is generated output and must never be edited manually or merged
into `main`.

Each add-on has its own application-specific validation workflow. Shared repository
linting still runs across all YAML and GitHub Actions files.

## Support

For add-on-specific problems, open an issue in this repository. For application-level
issues, use the corresponding upstream project.
