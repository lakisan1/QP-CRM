#!/usr/bin/env bash
#
# QP-CRM update flow for Docker deployments (P0-T6, audit M11).
# Replaces the old run_apps.sh update path (git pull + pkill + nohup):
# instead of killing bare processes we rebuild the image, recreate the
# container, and wait for the healthcheck to flip to 'healthy'.
#
# Usage:
#   ./deploy.sh              # optional git pull + rebuild + up + health wait
#   SKIP_PULL=1 ./deploy.sh  # same, but skip the git pull step
#
# Bare-metal users keep using run_apps.sh — it stays untouched.

set -euo pipefail

# Always operate from the repo root (where docker-compose.yml lives).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- 1) Optional code pull -------------------------------------------------
# --ff-only keeps deployments on a linear history; a failure (offline,
# diverged branch, detached HEAD) is non-fatal: warn and deploy the working
# tree as-is.
if [[ -z "${SKIP_PULL:-}" ]]; then
  echo "==> git pull --ff-only"
  if ! git pull --ff-only; then
    echo "WARNING: git pull --ff-only failed — continuing with the current working tree." >&2
    echo "         (offline? diverged history? use 'SKIP_PULL=1 ./deploy.sh' to skip this step)" >&2
  fi
else
  echo "==> SKIP_PULL=1 — skipping git pull"
fi

# --- 2) Rebuild + recreate -------------------------------------------------
# All mutable state lives in bind mounts (see docker-compose.yml), so a
# rebuild never loses DBs, assets, or the uploaded logo.
echo "==> docker compose build"
docker compose build

echo "==> docker compose up -d"
docker compose up -d

# --- 3) Wait for the healthcheck (~90 s budget) -----------------------------
echo "==> waiting for qp-crm healthcheck (budget: ~90s)"
ok=0
prev=""
for i in $(seq 1 90); do
  status="$(docker inspect --format '{{.State.Health.Status}}' qp-crm 2>/dev/null || echo unknown)"
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

# --- 4) Report --------------------------------------------------------------
if [[ "$ok" -eq 1 ]]; then
  echo "==> qp-crm is healthy — current stack state:"
  docker compose ps
else
  echo "ERROR: qp-crm did not become healthy in time (last status: ${status:-unknown})." >&2
  echo "---- last 50 log lines ----" >&2
  docker logs --tail 50 qp-crm >&2
  echo "---------------------------" >&2
  exit 1
fi
