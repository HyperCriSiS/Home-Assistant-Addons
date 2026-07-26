![Trilium Notes logo](https://github.com/user-attachments/assets/7b39fd05-4c0d-46f3-8283-117e2093f3e3)

# Trilium Notes for Home Assistant

This Home Assistant add-on runs [Trilium Notes](https://github.com/TriliumNext/Trilium), a hierarchical note-taking application for building a personal knowledge base. It supports rich text and Markdown, encryption, synchronization, scripting, and extensive organization features.

## Installation

1. Add this repository to Home Assistant:

   [![Open your Home Assistant instance and show the add add-on repository dialog with this repository pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHyperCriSiS%2FHome-Assistant-Addons)

2. Install **Trilium Notes** from the add-on store.
3. Start the add-on and open its web interface through Home Assistant Ingress.
4. Complete Trilium's initial setup and choose a strong password.

## Configuration

| Option | Description | Default |
| --- | --- | --- |
| `timezone` | IANA timezone used by the container | `Europe/Berlin` |
| `log_retention_days` | Number of days Trilium keeps log files | `90` |

The legacy `log_level` and `https_only` options are retained only for upgrade compatibility and are no longer used. TLS is terminated by Home Assistant Ingress or an external reverse proxy.

## Data and backups

Persistent data is stored in `/home/node/trilium-data` and mapped to the Home Assistant add-on data volume. Home Assistant backups include this directory. Trilium can also create its own backups under **Options → Backup**.

Before upgrading, create a current Home Assistant backup. Database migrations are performed by Trilium during startup and downgrading across database schema versions may not be supported.

## Network access

Ingress is enabled by default. Port `8080` is also exposed for optional direct access. Trilium is configured to trust the Home Assistant reverse proxy so forwarded client information and secure cookies work correctly.

## Troubleshooting

- Review the add-on logs under **Settings → Add-ons → Trilium Notes → Logs**.
- If the interface does not load after an update, restart the add-on and clear the browser cache.
- If startup fails after an upgrade, restore the pre-upgrade backup and attach the complete log when opening an issue.

## Support

For add-on-specific issues, use the [issue tracker](https://github.com/HyperCriSiS/Home-Assistant-Addons/issues). For Trilium application issues, use the [upstream project](https://github.com/TriliumNext/Trilium/issues).

## License

This add-on is licensed under the MIT License. Trilium Notes is licensed under the GNU Affero General Public License v3.0.
