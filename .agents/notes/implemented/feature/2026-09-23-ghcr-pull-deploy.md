# Agent Note: ghcr-pull-deploy

Status: implemented

## Problem

Remote instances currently update by rebuilding the Docker image on the server (deploy.sh v1: git pull + docker compose build). That makes the update slow (pip install + system libs compile on every deploy), requires build capacity on the remote host, and ships a binary that is similar to — but not bit-identical with — what CI tested. There is also no automatic data snapshot before an update and no one-command rollback, so a bad update risks a slow manual recovery. Users/passwords live in app_data/pricing.db which bind mounts keep outside the image, so the update flow itself never loses them — but nothing guarded against an operator mistake mid-update.

## Decision

CI (.github/workflows/ci.yml) gains an `image` job, needs: pytest, gated to push-on-main, with permissions packages:write; it rebuilds the image (gha cache) and pushes ghcr.io/lakisan1/qp-crm with `latest` and `sha-<commit>` tags. PR runs never push. docker-compose.yml `image:` is now ghcr.io/lakisan1/qp-crm:latest with `build:` retained for local dev only. deploy.sh v2: git pull --ff-only (non-fatal) → pre-deploy backup `backups/pre-deploy-<ts>.db` via sqlite3.backup() executed inside the running container (docker exec + docker cp, chmod 600, 10 most recent kept) — a FAILED backup ABORTS the deploy with nothing touched (override: SKIP_BACKUP=1, discouraged) → records the running tag into backups/last-deployed-tag → `docker compose pull` + `up -d` → health-wait (~90s, same budget). rollback.sh: deploys the recorded tag (or an explicit `sha-<commit>` argument) via a generated override file backups/compose-rollback-override.yml (repo compose file never hand-edited), takes its own pre-rollback DB snapshot first, health-waits, and rewrites last-deployed-tag. Negative guarantees: scripts never touch app_data/, app_assets/, static/img/ beyond reading pricing.db for the snapshot; no data is ever committed to git; schema down-migrations are NOT handled (older image against newer schema relies on the idempotent/additive init sequence — pre-rollback snapshot is the data escape hatch).
## Alternatives considered

**Build-on-server (keep old deploy.sh)** — remote would `git pull` + `docker compose build` directly. Lost: user explicitly wants no compile on the server (speed, weak instances, identical binary to the CI-tested one); kept only as the documented local-dev path (`docker compose build`, `up -d --build`).

**Hybrid auto-fallback (pull, else build)** — more script branches for a state that won't exist once CI pushes on every push to main; rejected as complexity without a near-term user.

**Offsite backup push (S3/rclone)** — the pre-deploy snapshot protects against the failure it must (bad update); disaster-recovery redundancy is a separate concern left out of scope.

**Backup via admin `generate_full_backup_zip()`** — the Flask helper requires a healthy app to serve a request; deploy-time backup must work precisely when the app may be broken, so the scripts snapshot the DB file directly instead.
## Consequences

Bought: remote update is one command with a guaranteed undo point; the image on prod is bit-identical to the CI-tested one; data loss from a bad update now requires two independent failures (bind mounts AND the pre-deploy snapshot). Cost: deployments need GHCR reachability (offline deploys fall back to local build only manually); GHCR image is private-by-default on GitHub — the remote host needs a one-time `docker login ghcr.io` (PAT with read:packages) until the package is set public; rollback container stays pinned via backups/compose-rollback-override.yml until the next deploy.sh. NOT done: no image pruning (`docker image prune` is the user's occasional job), no auto-update cron (updates stay explicit ./deploy.sh), DB schema down-migrations are not handled — rollback trusts the app's additive/idempotent init sequence and pre-rollback snapshot for the data side.

