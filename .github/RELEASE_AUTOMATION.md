# Trilium add-on release automation

The repository keeps the released Home Assistant app on `main`, the clean release candidate on `dev`, and a generated Home Assistant test repository on `dev-store`.

## Pipeline

1. `Update Trilium` runs every day and reads the latest stable GitHub release from `TriliumNext/Trilium`.
2. When a newer release exists it updates the pinned Docker image, bumps the date-based Home Assistant app version, updates the visible Trilium version in the store description, and prepends a changelog entry on an automation branch.
3. The updater explicitly dispatches `Validate add-on` for that exact update commit. The validation run must pass before `dev` can be changed.
4. When GitHub Actions is allowed to create pull requests, the updater creates an update PR against `dev` and automatically merges it after validation. If repository settings block Actions from creating PRs, the same validated commit is fast-forwarded to `dev` instead.
5. After promotion, the updater explicitly re-runs validation on `dev` and refreshes `dev-store`.
6. `dev-store` is generated from `dev` and is the installable Home Assistant test channel. It must never be merged back into `dev` or `main`.
7. A successful `dev` validation maintains a `dev -> main` release PR. Promotion to `main` remains the manual user-facing release gate unless `AUTO_RELEASE_TO_MAIN=true` is deliberately enabled.

## Dependency ownership

Trilium Docker image updates are owned exclusively by `Update Trilium`. Dependabot does not create Docker update PRs for `TriliumNext Notes`. Other Dependabot PRs target `dev`, not `main`.

## Secrets

`AUTOMATION_TOKEN` is optional. With it, the updater can create its normal update PR even when repository settings block PR creation by `GITHUB_TOKEN`. Without it, the updater uses the guarded validated fast-forward fallback.

## What CI can and cannot prove

The pipeline validates metadata, both supported architectures, startup and health, Home Assistant-style Ingress proxying, WebSockets, browser behavior, persistence, and database upgrades. The final promotion from `dev` to `main` remains the release decision.
