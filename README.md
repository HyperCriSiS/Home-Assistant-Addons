# Home Assistant Add-ons

Home Assistant add-ons maintained in this repository.

## Trilium Notes

The repository currently provides **Trilium Notes for Home Assistant**, based on
[TriliumNext/Trilium](https://github.com/TriliumNext/Trilium).

The add-on supports Home Assistant Ingress, persistent add-on storage, a Supervisor
watchdog, `amd64` and `aarch64`, and a restricted trusted reverse-proxy configuration
for Home Assistant Ingress.

See [TriliumNext Notes/README.md](TriliumNext%20Notes/README.md) for installation,
configuration, backups, networking, and troubleshooting.

## Automated validation and releases

Routine Trilium updates are handled by GitHub Actions:

1. A scheduled workflow checks the latest stable Trilium release every day.
2. When a new release is found, the workflow updates the pinned image, add-on version,
   and changelog on an automation branch and opens a pull request against `dev`.
3. The update is validated with linting, metadata checks, `amd64`/`aarch64` builds,
   HTTP health tests, Home Assistant-style reverse-proxy tests, WebSockets, Playwright
   browser E2E, persistence, and a database upgrade test from the version on `main`.
4. A successful automated update can be merged into `dev` automatically.
5. A validated `dev` state is promoted through a `dev -> main` release pull request.
   Automatic publication to `main` is intentionally opt-in.
6. An optional dedicated HAOS self-hosted runner can add a real Supervisor/Ingress
   integration gate before release.

The complete release automation, repository variables, secrets, and HAOS runner setup
are documented in [.github/RELEASE_AUTOMATION.md](.github/RELEASE_AUTOMATION.md).

## Support

For add-on-specific problems, open an issue in this repository. For application-level
Trilium issues, use the upstream Trilium project.
