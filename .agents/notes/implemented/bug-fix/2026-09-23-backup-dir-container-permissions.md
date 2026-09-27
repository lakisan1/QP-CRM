# Agent Note: backup-dir-container-permissions

Status: implemented

## Problem

After merging Dev (backup-tab work) to main as release v1.1.0, the docker CI failed at 'Run pytest suite' while the identical suite passed in the local venv. The docker-only difference: BACKUP_DIR = /app/backups did not exist in the image and sat under the root-owned /app, so the appuser (non-root since Phase 0) got 'Permission denied' — both the new backup-tab tests and any real in-app quick backup would fail in the deployed container.

## Decision

The image now creates /app/backups in the same RUN as the other mutable dirs and chowns it to appuser (2bf299e): BACKUP_DIR (qp_crm/shared/config.py) = <BASE_DIR>/backups = /app/backups in the container; the Admin -> Backup tab writes quick-<ts>.db there and reads pre-deploy/pre-rollback snapshots; compose deployments may overlay it with the ./backups bind mount (deploy.sh snapshots) — the overlay must then be writable by uid 1000, matching the existing ./app_data contract. The failing CI run (e0df9c1, pytest step 'Permission denied') is explained and fixed; the superseded v1.1.0 tag was deleted remotely and re-anchored on 2bf299e (annotated), Dev and main both fast-forwarded to 2bf299e; CI run 35874181590: pytest success + image success (GHCR push happened).
## Alternatives considered

**Bind-mount ./backups in compose instead of an image dir** — deploy.sh snapshots already use the host folder, but a bind mount of an EMPTY host dir (gitignored) would shadow the image dir with a root-owned empty one; and the app's quick backups then depend on host dir permissions outside the image contract. The image dir + appuser ownership covers both cases; a compose bind mount overlay, when present, wins and must be host-writable for uid 1000 (documented in the Dockerfile comment).

**Run the container as root** — rejected outright: the non-root appuser boundary exists since Phase 0.

**Skip the in-image /app/backups and patch tests to skip in Docker** — rejected: it would hide a REAL production breakage (in-app quick backups would fail in the deployed container, not just in tests). The test failure was the product working as intended.
## Consequences

Bought: the docker CI gate validates the backup tab exactly like it validates everything else; in-app quick backups work in a bare container (no compose bind mount needed); the release went out green with the image pushed. Cost: one more image-layer directory; if an operator bind-mounts ./backups over it, the HOST dir must be writable by uid 1000 (same contract as ./app_data) — deploy.sh already runs docker as the host user, so this holds. NOT done: no startup assertion that BACKUP_DIR is writable (a mis-permissioned bind mount would fail at first backup attempt with a clear flash message, not a crash); CI on Dev still doesn't fire on push (on: push is main-only since the image job — Dev runs CI only via PR; deliberate, recorded here so nobody expects green checkmarks on Dev pushes).

