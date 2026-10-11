# Changelog

## v2026.10.11

### Changed

- Updated Trilium from v0.105.0 to v0.106.0.

## v2026.09.21

### Fixed

- Fixed Home Assistant Ingress requests triggering `ERR_ERL_UNEXPECTED_X_FORWARDED_FOR`.
- Restricted trusted reverse-proxy handling to the Home Assistant Ingress proxy at `172.30.32.2`.

### Security

- Removed permissive reverse-proxy trust so forwarded client addresses cannot be accepted from arbitrary sources.

## v2026.09.07

### Changed

- Updated Trilium to v0.105.0.
- Trilium's ARM64 image now uses Debian 13 and requires a host with sufficiently recent `libseccomp` support.

## v2026.07.26

### Added

- Added a Home Assistant TCP watchdog for automatic service supervision.

### Changed

- Updated Trilium to v0.104.1.
- Switched to Trilium's upstream startup command and health check.
- Updated the Trilium environment configuration for host, port, trusted reverse proxy, and log retention.
- Deprecated the non-functional `log_level` and `https_only` options while retaining compatibility with existing installations.

## v2026.07.07

### Changed

- Updated Trilium to v0.103.0.

## v2025.11.30

### Changed

- Updated Trilium to v0.99.5.
- Renamed the Home Assistant App to Trilium Notes.

### Fixed

- Fixed the Trilium startup parameters.

## v2025.09.22

### Fixed

- Fixed Trilium startup and health-check handling.

## v2025.09.17

### Changed

- Updated Trilium to v0.98.1.

## v2025.03.13

### Added

- Added timezone and log-level configuration options.

### Changed

- Updated the Trilium Notes branding and logo.

### Fixed

- Fixed inconsistent Trilium naming across the Home Assistant App files.

## v2025.03.12

### Added

- Initial Home Assistant App release.
