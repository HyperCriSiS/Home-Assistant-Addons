# Branching workflow

This repository uses separate long-lived development branches per Home Assistant App.

## `main`

`main` is the stable Home Assistant repository consumed by normal users. Only validated changes that are ready for release belong here.

## `dev-trilium`

Long-lived release-candidate branch for **Trilium Notes only**. Trilium changes are validated and tested here before promotion to `main`.

## `dev-mcphub`

Long-lived release-candidate branch for **MCPHub only**. MCPHub changes are validated and tested here before promotion to `main`.

Both development branches periodically merge the latest `main` so they inherit already released changes from the other App without inheriting the other App's unreleased work.

## `dev-store`

`dev-store` is a generated Home Assistant testing repository. It is composed from:

- `TriliumNext Notes/` from `dev-trilium`
- `MCPHub/` from `dev-mcphub`
- shared repository content from `main`

Home Assistant development repository URL:

```text
https://github.com/HyperCriSiS/Home-Assistant-Addons#dev-store
```

The generator adds `(Dev)`, `-dev.<run>`, and `stage: experimental` metadata so test installations are clearly distinguishable.

**Never edit `dev-store` manually and never merge it into `main`.**

## Release flows

```text
Trilium work -> dev-trilium -> dev-store -> HA test -> main
MCPHub work  -> dev-mcphub  -> dev-store -> HA test -> main
```

A Trilium release PR is always `dev-trilium -> main`. An MCPHub release PR is always `dev-mcphub -> main`. This prevents one App's unreleased work from being published with the other App.

Use short-lived `feature/*`, `fix/*`, `refactor/*`, `test/*`, `docs/*`, `chore/*`, and `hotfix/*` branches where useful, targeting the corresponding App development branch.
