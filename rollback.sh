#!/usr/bin/env bash
#
# QP-CRM rollback: return to the image that was running before the last
# deploy.sh (update system v2).
#
# How it works:
#   * deploy.sh records the tag of the running image into
#     backups/last-deployed-tag BEFORE it pulls the new one.
#   * CI pushes every build as an immutable sha-<commit> tag on GHCR, so the
#     recorded tag always resolves to the exact tested build (never a moving
#     "latest").
#   * This script re-pins the compose file's tag to that recorded tag,
#     recreates the container, and waits for the healthcheck. Data (bind
#     mounts: app_data/, app_assets/, static/img/) is never touched — a
#     rollback only swaps application code.
#
# Usage:
#   ./rollback.sh                 # back to the last-deployed tag
#   ./rollback.sh sha-abc1234     # back to an explicit tag (e.g. older SHA)
#
# NOTE on DB migrations: if the newer image migrated the SQLite schema
# forward, running an older image against it is generally fine (the app's
# init sequence is idempotent / additive), but data written since then stays.
# The pre-deploy backups in backups/ (pre-deploy-<ts>.db) cover the data side.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE="docker compose"
BACKUP_DIR="backups"
TAG_FILE="$BACKUP_DIR/last-deployed-tag"
HEALTH_CONTAINER="qp-crm"
IMAGE_BASE="ghcr.io/lakisan1/qp-crm"

# --- resolve target tag -------------------------------------------------------
if [[ $# -ge 1 && -n "${1:-}" ]]; then
  target_tag="$1"
else
  if [[ ! -f "$TAG_FILE" ]]; then
    echo "ERROR: $TAG_FILE not found — no deploy.sh has ever run here." >&2
    echo "       Roll back to an explicit tag instead: ./rollback.sh sha-<commit>" >&2
    exit 1
  fi
  target_tag="$(cat "$TAG_FILE")"
fi

current_image="$(docker inspect --format '{{index .Config.Image}}' "$HEALTH_CONTAINER" 2>/dev/null || echo '')"
current_tag="${current_image##*:}"
if [[ -n "$current_tag" && "$current_tag" == "$target_tag" ]]; then
  echo "==> container already runs tag '$target_tag' — nothing to roll back."
  exit 0
fi

echo "==> rollback: $IMAGE_BASE:$target_tag"
echo "    (current: ${current_image:-<none>})"

# --- sanity: the target image must exist (locally or on GHCR) ----------------
if ! docker image inspect "$IMAGE_BASE:$target_tag" >/dev/null 2>&1; then
  echo "==> target image not local — pulling $IMAGE_BASE:$target_tag"
  $COMPOSE pull app || true
  if ! docker image inspect "$IMAGE_BASE:$target_tag" >/dev/null 2>&1; then
    echo "ERROR: image $IMAGE_BASE:$target_tag not available (compose pull pulls 'latest', not this tag)." >&2
    echo "       Fetch it explicitly:  docker pull $IMAGE_BASE:$target_tag" >&2
    exit 1
  fi
fi

# --- safety backup of the CURRENT db state before going back in time ---------
mkdir -p "$BACKUP_DIR"
if docker inspect --format '{{.State.Running}}' "$HEALTH_CONTAINER" 2>/dev/null | grep -q true; then
  ts="$(date +%Y%m%d-%H%M%S)"
  backup_path="$BACKUP_DIR/pre-rollback-$ts.db"
  echo "==> pre-rollback backup: $backup_path"
  if docker exec "$HEALTH_CONTAINER" python -c "
import sqlite3
src = sqlite3.connect('/app/app_data/pricing.db')
dst = sqlite3.connect('/tmp/__prerollback.db')
src.backup(dst)
dst.close(); src.close()
" && docker cp "$HEALTH_CONTAINER:/tmp/__prerollback.db" "$backup_path" \
       && docker exec "$HEALTH_CONTAINER" rm -f /tmp/__prerollback.db \
       && chmod 600 "$backup_path"; then
    ls -1t "$BACKUP_DIR"/pre-rollback-*.db 2>/dev/null | tail -n +11 | xargs -r rm -f --
    echo "    backup ok"
  else
    echo "ERROR: pre-rollback backup FAILED — aborting (nothing was touched)." >&2
    exit 1
  fi
fi

# --- recreate on the target tag ----------------------------------------------
# Pin the tag without editing docker-compose.yml by hand: an env-style
# override via a temporary compose override file keeps the repo file clean.
override="$BACKUP_DIR/compose-rollback-override.yml"
cat > "$override" <<EOF
services:
  app:
    image: $IMAGE_BASE:$target_tag
EOF

echo "==> recreating container on tag '$target_tag'"
$COMPOSE -f docker-compose.yml -f "$override" up -d

# --- health wait (same budget as deploy.sh) -----------------------------------
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
    unhealthy) break ;;
  esac
  sleep 1
done

if [[ "$ok" -eq 1 ]]; then
  # Persist the rollback as the new "last deployed" point: a second rollback
  # goes back further only via an explicit tag argument.
  printf '%s\n' "$target_tag" > "$TAG_FILE"
  echo "==> qp-crm is healthy on tag '$target_tag'."
  $COMPOSE ps
  echo
  echo "    NOTE: this container is pinned to '$target_tag' via $override."
  echo "    The next ./deploy.sh pulls 'latest' again — run it when the fix ships."
else
  echo "ERROR: qp-crm did not become healthy in time (last status: ${status:-unknown})." >&2
  echo "---- last 50 log lines ----" >&2
  docker logs --tail 50 "$HEALTH_CONTAINER" >&2
  echo "---------------------------" >&2
  exit 1
fi
