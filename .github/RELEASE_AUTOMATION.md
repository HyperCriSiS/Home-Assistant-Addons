# Trilium add-on release automation

The repository is designed so routine Trilium updates can be proposed, tested, and promoted without manually opening the application.

## Pipeline

1. `Update Trilium` runs every day and reads the latest stable GitHub release from `TriliumNext/Trilium`.
2. When a newer release exists it updates the pinned Docker image, bumps the date-based Home Assistant add-on version, prepends a changelog entry, and opens a PR against `dev`.
3. The updater explicitly dispatches `Validate add-on` for the update branch. A green run can be squash-merged into `dev` automatically.
4. `Validate add-on` performs static validation, upstream image/architecture checks, native and cross-platform builds, functional HTTP tests, an exact Home Assistant-style reverse-proxy test, a WebSocket test, Playwright browser E2E, restart persistence, and an upgrade test from the version currently on `main`.
5. A successful `dev` validation maintains a `dev -> main` release PR. Promotion to `main` is deliberately opt-in.
6. If a dedicated Home Assistant OS runner is configured, `HAOS integration` becomes an additional release gate before promotion.

## Repository variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTO_MERGE_TO_DEV` | `true` | Automatically squash a bot-created Trilium update PR into `dev` after full validation. Set to `false` to keep bot PRs open. |
| `AUTO_RELEASE_TO_MAIN` | `false` | When `true`, the validated `dev -> main` PR is put into GitHub auto-merge. Keep this disabled until the pipeline has proven reliable for several releases. |
| `HAOS_E2E_ENABLED` | `false` | Enables the dedicated HAOS release gate. |
| `HAOS_ADDONS_DIR` | unset | Path on the self-hosted runner that maps to the HAOS local add-ons directory. Required when HAOS E2E is enabled. |
| `HAOS_BASE_URL` | unset | Optional Home Assistant URL used to test the real Ingress endpoint, for example `http://homeassistant.local:8123`. |
| `HA_CLI` | `ha` | Command used by the dedicated runner to control the HAOS test instance. It may also be a wrapper script that remotely invokes the Home Assistant CLI. |

When enabling `AUTO_RELEASE_TO_MAIN`, also enable GitHub's repository setting **Allow auto-merge** and protect `main` with the required validation checks.

## Secrets

- `AUTOMATION_TOKEN` is optional. If present, use a fine-grained token or GitHub App token with repository contents, Actions and pull-request write access. Otherwise workflows use `GITHUB_TOKEN` and explicitly dispatch validation because events created by `GITHUB_TOKEN` do not recursively start normal workflows.
- `HAOS_TOKEN` is optional unless real Ingress is tested. It must be a token accepted by the dedicated Home Assistant test instance.

## Dedicated HAOS runner

The HAOS job is skipped unless `HAOS_E2E_ENABLED=true`, so a missing self-hosted runner never blocks normal CI.

The runner must have these labels:

- `self-hosted`
- `linux`
- `haos-addon-test`

It also needs:

- a working `ha` CLI (or a wrapper configured via `HA_CLI`),
- `rsync`, `curl`, and Python 3,
- a writable/mounted HAOS local add-ons directory exposed via `HAOS_ADDONS_DIR`.

The job copies the current `TriliumNext Notes` directory into the HAOS local add-ons directory, reloads Supervisor app metadata, installs/starts or restarts `local_trilium`, checks its state and logs, and optionally calls the real Ingress URL.

Use a disposable/dedicated Home Assistant OS instance. Do not point this runner at a production Home Assistant installation.

## What CI can and cannot prove

The pipeline detects startup failures, broken architectures, proxy/rate-limit regressions, broken WebSockets, browser-load failures, basic note create/read persistence, database migration failures, and Home Assistant Supervisor failures when the optional HAOS gate is enabled. No automated suite can mathematically guarantee that every Trilium feature is bug-free, so upstream release notes and failed automation PRs still deserve review when a release makes major architectural changes.
