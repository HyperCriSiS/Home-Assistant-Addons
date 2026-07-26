# Changelog

## v2026.07.26

- Update Trilium Notes to v0.104.1.
- Migrate away from the obsolete `build.yaml` mechanism and pin the upstream image directly in the Dockerfile.
- Use Trilium's upstream startup command and health check instead of maintaining a custom wrapper.
- Configure the current Trilium environment variables for host, port, trusted reverse proxy, and log retention.
- Add automated validation, image build, container health smoke tests, and Dependabot updates.
- Deprecate the non-functional `log_level` and `https_only` options while retaining schema compatibility for existing installations.

## v2026.07.07

- Update to Trilium v0.103.0 (sync protocol version 39).

## v2025.11.30

- Update to v0.99.5.
- Change name to Trilium Notes.
- Fix startup parameter.

## v2025.09.22

- Fix startup and health check.

## v2025.09.17

- Update to v0.98.1.

## v2025.03.13

- Add timezone and log-level options.
- Add new logo with the correct name.
- Fix naming across files.

## v2025.03.12

- Initial release.
