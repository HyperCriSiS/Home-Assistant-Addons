# Trilium add-on release automation

Trilium uses a dedicated release-candidate branch, `dev-trilium`. MCPHub uses `dev-mcphub`. Both feed the shared generated `dev-store`, while `main` remains the user-facing stable repository.

## Trilium pipeline

1. `Update Trilium` runs daily and reads the latest stable TriliumNext release.
2. A newer release is prepared on `automation/trilium-<version>`.
3. The exact candidate commit must pass the full Trilium validation workflow.
4. The validated candidate is merged or fast-forwarded into `dev-trilium`; red validation can never update `dev-trilium`.
5. The shared `dev-store` is rebuilt using Trilium from `dev-trilium` and MCPHub from `dev-mcphub`.
6. Home Assistant testing therefore sees both current candidates in one development repository.
7. User-facing Trilium release is exclusively `dev-trilium -> main`.
8. MCPHub has an independent `dev-mcphub -> main` release flow.

After a `main` release, the stable branch is merged back into both App development branches so each candidate branch stays based on the current production repository.

## Validation

Trilium CI validates metadata, amd64/aarch64 images, native and cross-platform builds, Home Assistant-style Ingress proxying, WebSockets, browser E2E, restart persistence, and database upgrades from the stable version currently on `main`.

## Dependency ownership

- Trilium Docker releases are owned by `Update Trilium`.
- MCPHub dependencies target `dev-mcphub`.
- Trilium browser-test npm dependencies target `dev-trilium`.
- Shared GitHub Actions dependency PRs target `main` because they are repository infrastructure rather than an App release.

## Branch protection

`dev-trilium`, `dev-mcphub`, and `dev-store` are permanent protected branches. Deletion and non-fast-forward updates are blocked. `main` keeps its stricter pull-request-only protection.

## Optional HAOS gate

If `HAOS_E2E_ENABLED=true`, Trilium and MCPHub each use their own dedicated HAOS integration workflow before release promotion.
