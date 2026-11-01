# Agent Note: admin-about-tab

Status: implemented

## Problem

The user asked for an About/info tab in the admin panel showing software information including the current version. Nothing in the app exposed a version: no APP_VERSION constant existed anywhere, and after an update there was no way to tell WHICH build was actually running (image tags live host-side in backups/last-deployed-tag, invisible to the container).

## Decision

New read-only GET /admin/about route (admin/routes/info.py), last link in the shared _nav.html (eight links now). Version chain: APP_VERSION constant in shared/config.py (single source of truth, currently "1.1.0") + APP_BUILD_COMMIT from env QP_BUILD_COMMIT — new Dockerfile ARG/ENV passed by ci.yml's build-push-action build-args as github.sha; bare-metal/dev runs show an honest "dev build" label. The running image tag comes from backups/last-deployed-tag, which deploy.sh writes host-side — exposed to the container by a NEW compose bind-mount ./backups:/app/backups (b80a2bd), which also makes Admin -> Backup quick backups survive recreates for the first time. Page cards: Version, Runtime (Python ver, SQLite WAL + size), Data at a glance (users/products/offers/contracts/contacts counts, missing table -> 0), Where things live (update-safe bind dirs), Links. CI needed ./backups pre-created uid 1000 on the runner before docker compose run, else docker creates it root-owned and appuser hits PermissionError (c9c2469). Along the way this unblocked main: CI had been red since Oct 2 because commit 8866896 (R-D3 advance-offset clause) changed the rent PDF without re-baselining rent_ugovor_zakup_golden.pdf; baseline regenerated inside the pinned image per QP_UPDATE_GOLDEN=1 procedure and text-diff-verified to contain exactly that clause change (3d73a4d). Tests: 7 new characterization tests in tests/characterization/test_about_tab.py; smoke ADMIN_SUBPAGES includes /admin/about and asserts all eight nav links. Suite 537 passed / 3 skipped; live local instance verifies APP_VERSION 1.1.0, build commit c9c2469, image tag sha-c9c2469..., /admin/about route present.
## Alternatives considered

**Read version from git tag at runtime** — rejected: the container has no .git (COPY excludes it), so the version would need a build-time file anyway; a constant in config.py is simpler and the release procedure already bumps it.

**Parse the image tag from docker inspect at request time** — rejected: requires docker socket access inside the container (security anti-pattern); deploy.sh already records the tag to a file, reading that file is free.

**Hardcode version in a template or dashboard card** — rejected: two sources of truth drift; About is the single place and config.py the single constant.

**Never re-baseline on host (kept)** — the golden test itself enforces this (skip outside /.dockerenv or cwd /app); the re-baseline was done inside a fresh pinned-image container with fonts-dejavu-core, and the text diff was verified to contain exactly the R-D3 clause before committing.
## Consequences

Bought: users can see at a glance which version/build runs where (support question "koju verziju imaš?" is now answered by a URL), and quick backups survive recreates (the compose mount fixed that too). Cost/obligations: (1) APP_VERSION must be bumped with every release — UPDATE.md/release procedure should mention it; (2) CI now needs backups/ pre-created uid 1000 before compose run — any new CI job running pytest must keep that step; (3) golden baselines are byte-pinned to fonts-dejavu-core — base-image font drift can break them again; the Oct 2 red main was exactly that class of miss (rent templates changed without re-baseline), now unblocked. NOT done: no auto-check "new version available" against GHCR (About shows what IS running, not what COULD run — could be a follow-up); About does not list DB migration state.

