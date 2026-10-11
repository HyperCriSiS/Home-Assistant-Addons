# Trilium add-on release automation

The repository keeps the released Home Assistant app on `main`, the clean release candidate on `dev`, and a generated Home Assistant test repository on `dev-store`.

## Pipeline

1. `Update Trilium` runs every day and reads the latest stable GitHub release from `TriliumNext/Trilium`.
2. When a newer release exists it updates the pinned Docker image, bumps the date-based Home Assistant app version, updates the visible Trilium version in the store description, and prepends a changelog entry on an automation branch.
3. The updater explicitly dispatches `Validate add-on` for that exact update commit. The validation run must pass before `dev` can be changed.
4. When GitHub Actions is allowed to create pull requests, the updater creates an update PR against `dev` and automatically merges it after validation. If repository settings block Actions from creating PRs, the same validated commit is fast-forwarded to `dev` instead. The fallback refuses to run if `dev` changed while validation was in progress.
5. After promotion, the updater explicitly re-runs validation on `dev` and refreshes `dev-store`. This explicit dispatch is required because events produced with `GITHUB_TOKEN` do not recursively start workflows.
6. `dev-store` is generated from `dev` and changes only development metadata such as `(Dev)`, the `-dev.N` version suffix, and `stage: experimental`. It is the installable Home Assistant test channel and must never be merged back into `dev` or `main`.
7. A successful `dev` validation maintains a `dev -> main` release PR. Promotion to `main` remains the manual user-facing release gate unless `AUTO_RELEASE_TO_MAIN=true` is deliberately enabled.
8. If a dedicated Home Assistant OS runner is configured, `HAOS integration` becomes an additional release gate before promotion.

`Validate add-on` performs static validation, upstream image/architecture checks, native and cross-platform builds, functional HTTP tests, a Home Assistant-style reverse-proxy test, a WebSocket test, Playwright browser E2E, restart persistence, and an upgrade test from the version currently on `main`.

## Dependency ownership

Trilium Docker image updates are owned exclusively by `Update Trilium`. Dependabot must not create Docker update PRs for `TriliumNext Notes`, because those PRs would bypass the app-version, changelog, store-description, and integration-test update transaction.

Dependabot may still maintain other dependency classes, but its PRs target `dev` rather than the user-facing `main` branch.

## Repository variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTO_RELEASE_TO_MAIN` | `false` | When `true`, the validated `dev -> main` PR is put into GitHub auto-merge. Keep this disabled while releases require manual approval. |
| `HAOS_E2E_ENABLED` | `false` | Enables the dedicated HAOS release gate. |
| `HAOS_ADDONS_DIR` | unset | Path on the self-hosted runner that maps to the HAOS local add-ons directory. Required when HAOS E2E is enabled. |
| `HAOS_BASE_URL` | unset | Optional Home Assistant URL used to test the real Ingress endpoint. |
| `HA_CLI` | `ha` | Command used by the dedicated runner to control the HAOS test instance. |

When enabling `AUTO_RELEASE_TO_MAIN`, also enable GitHub's repository setting **Allow auto-merge** and protect `main` with the required validation checks.

## Secrets

- `AUTOMATION_TOKEN` is optional. If present, use a fine-grained token or GitHub App token with repository contents, Actions, and pull-request write access. It allows the updater to create and merge its normal update PR even when the repository blocks PR creation by `GITHUB_TOKEN`.
- Without `AUTOMATION_TOKEN`, the updater still validates the exact update branch and then uses the guarded fast-forward fallback to keep `dev` current automatically.
- `HAOS_TOKEN` is optional unless real Ingress is tested. It must be a token accepted by the dedicated Home Assistant test instance.

## Dedicated HAOS runner

The HAOS job is skipped unless `HAOS_E2E_ENABLED=true`, so a missing self-hosted runner never blocks normal CI.

The runner must have these labels:

- `self-hosted`
- `linux`
- `haos-addon-test`

It also needs a working `ha` CLI (or wrapper configured via `HA_CLI`), `rsync`, `curl`, Python 3, and a writable/mounted HAOS local add-ons directory exposed via `HAOS_ADDONS_DIR`.

Use a disposable/dedicated Home Assistant OS instance. Do not point this runner at a production Home Assistant installation.

## What CI can and cannot prove

The pipeline detects startup failures, broken architectures, proxy/rate-limit regressions, broken WebSockets, browser-load failures, basic note create/read persistence, database migration failures, and Home Assistant Supervisor failures when the optional HAOS gate is enabled. No automated suite can guarantee that every Trilium feature is bug-free, so major upstream architectural changes still deserve review before promoting `dev` to `main`.
