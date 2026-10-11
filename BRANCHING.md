# Branching workflow

This repository uses three long-lived branches with distinct responsibilities.

## `main`

`main` is the stable Home Assistant repository consumed by normal users:

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons
```

Only validated changes that are ready for release belong on `main`.

## `dev`

`dev` is the integration branch for changes that still need real Home Assistant testing.

Each add-on has its own validation workflow. Changes remain on `dev` until CI and
manual testing are complete, then they are promoted to `main`.

Do not add `#dev` directly to Home Assistant for routine testing. Use the generated
`dev-store` branch instead, because it has explicit development labels and generated
development versions.

## `dev-store`

`dev-store` is generated automatically from `dev` by
`.github/workflows/sync-dev-store.yml`.

It exists only to make development builds easy and unambiguous in Home Assistant:

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons#dev-store
```

The generator changes only Home Assistant store metadata:

- repository name → `HyperCriSiS Add-ons (Dev)`
- `MCPHub` → `MCPHub (Dev)`
- `Trilium Notes` → `Trilium Notes (Dev)`
- panel titles receive the same `(Dev)` suffix
- each App version receives a generated `-dev.<run>` suffix
- development entries are marked experimental where necessary

The source code itself remains identical to the current `dev` commit.

**Never edit `dev-store` manually and never merge it into `main`.** It is generated
output and is force-updated whenever `dev` changes.

## Feature work

Use short-lived branches such as `feature/*`, `fix/*`, `refactor/*`, `test/*`,
`docs/*`, `chore/*`, and `hotfix/*` when appropriate. Merge those changes into
`dev` for integration testing.

The normal release flow is:

```text
feature/fix branch
        ↓
       dev
        ↓
   dev-store
   (HA testing)
        ↓
       main
```

Git tags can be used for released versions. Individual Home Assistant Apps belong in
the repository directory/module structure rather than permanent per-App branches.
