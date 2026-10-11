# HyperCriSiS Add-ons

Home Assistant add-ons maintained by HyperCriSiS.

## Install repository

### Stable

[![Add stable repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Addons)

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons
```

### Development

A single generated development store combines the current Trilium and MCPHub release candidates:

[![Add development repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Addons%23dev-store)

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons#dev-store
```

Home Assistant shows it as **HyperCriSiS Add-ons (Dev)**. Trilium Notes comes from `dev-trilium`; MCPHub comes from `dev-mcphub`. This keeps releases independent while retaining one convenient test repository.

> [!WARNING]
> Development builds may contain incomplete or breaking changes. Keep backups before testing updates.

## MCPHub

**MCPHub** provides a central control plane for MCP servers inside Home Assistant.

See [MCPHub/README.md](MCPHub/README.md) for installation and [MCPHub/DOCS.md](MCPHub/DOCS.md) for configuration, security, and troubleshooting.

## Trilium Notes

This repository provides **Trilium Notes for Home Assistant**, based on [TriliumNext/Trilium](https://github.com/TriliumNext/Trilium).

The add-on supports Home Assistant Ingress, persistent add-on storage, a Supervisor watchdog, `amd64` and `aarch64`, and a restricted trusted reverse-proxy configuration for Home Assistant Ingress.

See [TriliumNext Notes/README.md](TriliumNext%20Notes/README.md) for installation, configuration, backups, networking, and troubleshooting.

## Development and releases

- Trilium development: `dev-trilium`
- MCPHub development: `dev-mcphub`
- Combined Home Assistant test repository: `dev-store`
- Stable releases: `main`

Each App is promoted independently to `main`, so a Trilium release cannot accidentally publish unreleased MCPHub changes and vice versa.

See [BRANCHING.md](BRANCHING.md) for the complete branch model.

## Support

For add-on-specific problems, open an issue in this repository. For application-level issues, use the corresponding upstream project.
