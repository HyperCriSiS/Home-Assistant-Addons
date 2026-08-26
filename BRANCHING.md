# Branching workflow

`main` is the single long-lived integration and release branch for this repository.

The existing `dev` branch is not required as a permanent integration layer. New work should branch from the current `main`, be reviewed as one logical pull request, merge back into `main`, and then be deleted.

Use short-lived branches such as `feature/*`, `fix/*`, `refactor/*`, `test/*`, `docs/*`, `chore/*` and `hotfix/*`. Use `release/<version>` only when a release genuinely needs temporary stabilization.

Individual Home Assistant add-ons belong in the repository directory/module structure, not in permanent branches.

The authoritative roadmap and release planning must live on `main`. Use Git tags for released versions instead of keeping permanent release branches.
