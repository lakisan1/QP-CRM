#!/usr/bin/env bash
#
# QP-CRM update flow for Docker deployments (update system v2, pull-deploy).
#
# The image is built and pushed to GHCR by CI (.github/workflows/ci.yml,
# "image" job) AFTER the pytest suite passes — the remote server never
# builds. This script:
#
#   1) git pull --ff-only                (code = docs/scripts; the app runs
#                                         from the image, not this tree)
#   2) BACKUP the SQLite DB (WAL-safe) into backups/pre-deploy-<ts>.db
#                                         -- users, password hashes, offers,
#                                           contracts: nothing can be lost,
#                                           not even to a bad new image
#   3) record the running image tag      -> backups/last-deployed-tag
#                                         (rollback.sh reads this)
#   4) docker compose pull + up -d       (recreate from the new image;
#                                         bind mounts keep all mutable data)
#   5) wait for the healthcheck          (~90 s budget, fail fast + logs)
#
# Usage:
#   ./deploy.sh              # full flow
#   SKIP_PULL=1 ./deploy.sh  # skip step 1 (no git pull)
#   SKIP_BACKUP=1 ./deploy.sh # skip step 2 (NOT recommended)
#
# Local dev (build on this machine) is unchanged:
#   docker compose build && docker compose up -d --build
#
# Rollback after a bad update: ./rollback.sh

set -euo pipefail

# Always operate from the repo root (where docker-compose.yml lives).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE="docker compose"
BACKUP_DIR="backups"
HEALTH_CONTAINER="qp-crm"

# --- 1) Optional code pull ---------------------------------------------------
# --ff-only keeps deployments on a linear history; a failure (offline,
# diverged branch, detached HEAD) is non-fatal: warn and deploy as-is.
if [[ -z "${SKIP_PULL:-}" ]]; then
  echo "==> git pull --ff-only"
  if ! git pull --ff-only; then
    echo "WARNING: git pull --ff-only failed — continuing with the current working tree." >&2
    echo "         (offline? diverged history? use 'SKIP_PULL=1 ./deploy.sh' to skip this step)" >&2
  fi
else
  echo "==> SKIP_PULL=1 — skipping git pull"
fi

# --- 2) Pre-deploy backup (WAL-safe, runs INSIDE the running container) ------
# Uses sqlite3.backup() through the container's own python — the same
# WAL-safe snapshot mechanism as the admin /backup_db route. Runs only if a
# container is up; a first-ever deploy has nothing to back up yet.
mkdir -p "$BACKUP_DIR"
if docker inspect --format '{{.State.Running}}' "$HEALTH_CONTAINER" 2>/dev/null | grep -q true; then
  ts="$(date +%Y%m%d-%H%M%S)"
  backup_path="$BACKUP_DIR/pre-deploy-$ts.db"
  echo "==> pre-deploy backup: $backup_path (WAL-safe snapshot)"
  if docker exec "$HEALTH_CONTAINER" python -c "
import sqlite3
src = sqlite3.connect('/app/app_data/pricing.db')
dst = sqlite3.connect('/tmp/__predeploy.db')
src.backup(dst)
dst.close(); src.close()
" && docker cp "$HEALTH_CONTAINER:/tmp/__predeploy.db" "$backup_path" \
     && docker exec "$HEALTH_CONTAINER" rm -f /tmp/__predeploy.db \
     && chmod 600 "$backup_path"; then
    # Keep the 10 most recent pre-deploy backups — old ones rot anyway
    # (schema migrations in newer images can make them unrestorable).
    ls -1t "$BACKUP_DIR"/pre-deploy-*.db 2>/dev/null | tail -n +11 | xargs -r rm -f --
    echo "    backup ok ($(du -h "$backup_path" | cut -f1)); keeping the 10 most recent"
  else
    echo "ERROR: pre-deploy backup FAILED — aborting deploy (nothing was touched)." >&2
    echo "       Fix the backup first, or force with SKIP_BACKUP=1 ./deploy.sh (NOT recommended)." >&2
    exit 1
  fi
else
  echo "==> no running qp-crm container — skipping backup (first deploy?)"
fi

# --- 3) Record the running image tag (the rollback point) --------------------
# Written BEFORE the pull so rollback.sh always has the exact tag that was
# live until a moment ago. First deploy: latest is the only sensible target.
current_tag="latest"
if docker inspect --format '{{index .Config.Image}}' "$HEALTH_CONTAINER" 2>/dev/null | grep -q .; then
  running_image="$(docker inspect --format '{{index .Config.Image}}' "$HEALTH_CONTAINER")"
  current_tag="${running_image##*:}"
  [[ -z "$current_tag" || "$running_image" == "$current_tag" ]] && current_tag="latest"
fi
printf '%s\n' "$current_tag" > "$BACKUP_DIR/last-deployed-tag"
echo "==> rollback point recorded: $current_tag (backups/last-deployed-tag)"

# --- 4) Pull + recreate -------------------------------------------------------
# All mutable state lives in bind mounts (see docker-compose.yml), so a
# recreation never loses DBs, assets, or the uploaded logo.
echo "==> docker compose pull"
$COMPOSE pull app

echo "==> docker compose up -d"
$COMPOSE up -d

# --- 5) Wait for the healthcheck (~90 s budget) -------------------------------
echo "==> waiting for qp-crm healthcheck (budget: ~90s)"
ok=0
prev=""
status="unknown"
for i in $(seq 1 90); do
  status="$(docker inspect --format '{{.State.Health.Status}}' "$HEALTH_CONTAINER" 2>/dev/null || echo unknown)"
  if [[ "$status" != "$prev" ]]; then
    echo "    t+${i}s  health: $status"
    prev="$status"
  elif (( i % 15 == 0 )); then
    echo "    t+${i}s  health: $status (still waiting)"
  fi
  case "$status" in
    healthy)   ok=1; break ;;
    unhealthy) break ;;  # terminal state — fail fast, logs printed below
  esac
  sleep 1
done

# --- 6) Report -----------------------------------------------------------------
if [[ "$ok" -eq 1 ]]; then
  echo "==> qp-crm is healthy — current stack state:"
  $COMPOSE ps
  echo
  echo "    Deployed image: $($COMPOSE images app --format '{{.Repository}}:{{.Tag}}' 2>/dev/null || echo 'see: docker compose images')"
  echo "    Rollback if needed: ./rollback.sh"
else
  echo "ERROR: qp-crm did not become healthy in time (last status: ${status:-unknown})." >&2
  echo "---- last 50 log lines ----" >&2
  docker logs --tail 50 "$HEALTH_CONTAINER" >&2
  echo "---------------------------" >&2
  echo "Data is untouched (bind mounts + pre-deploy backup in $BACKUP_DIR/)." >&2
  echo "To go back to the previous image: ./rollback.sh" >&2
  exit 1
fi
