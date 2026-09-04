# QP-CRM — Docker operations (Phase 0)

Single-container deployment: the Flask multi-app stack (pricing / offer / rent /
admin / sale / settings, merged by `qp_crm/main.py` via DispatcherMiddleware and served
by gunicorn through `qp_crm/wsgi.py`) runs in one container on **port 5000**.

- Image: `qp-crm:phase1` — built from `./Dockerfile` (phase-1 adds the pytest
test layer; `qp-crm:phase0` remains the rollback tag)
- Container name: `qp-crm` — stack file: `docker-compose.yml`
- Secrets: `.env` (see `.env.example`)

## Prerequisites

- Docker Engine (Debian/Ubuntu package `docker.io`) and the Compose v2 plugin
  (`docker-compose-v2` on Ubuntu 24.04, or `docker-compose-plugin` from the
  Docker official repo). Check with:
  ```bash
  docker --version && docker compose version
  ```
- To run docker without sudo: `sudo usermod -aG docker $USER` (re-login once).

## First run

```bash
cp .env.example .env
# fill in all six keys, e.g. per entry:
#   python3 -c "import secrets; print(secrets.token_hex(32))"
docker compose up -d --build
```

Then open `http://<host>:5000/`. First boot imports WeasyPrint and creates the
SQLite schema, so the healthcheck has `start_period: 60s`; wait for
`docker compose ps` to show `healthy`.

Note: docker containers get their secret keys from `.env` (compose injects
them). Bare-metal runs (`./run_apps.sh`, `python -m qp_crm.main`) do not read
`.env` — they fall back to the in-code default keys.

## Updating

```bash
./deploy.sh               # git pull --ff-only → docker compose build → up -d → wait for health
SKIP_PULL=1 ./deploy.sh   # same, but skip the git pull
```

`deploy.sh` replaces the old `run_apps.sh` update flow (git pull + `pkill`
qp_crm.main`, audit finding M11): instead of killing processes it rebuilds the
image, recreates the container, then polls
`docker inspect --format '{{.State.Health.Status}}' qp-crm` for up to ~90 s and
prints the last 50 log lines if the container never turns healthy.

`run_apps.sh` still exists for bare-metal users (no Docker): it
creates the venv, installs requirements and runs `python -m qp_crm.main` directly.

## Volumes — what lives where

All three are host bind mounts, so data survives image rebuilds and
`docker compose down`:

| Host path      | Container path     | Contents |
|----------------|--------------------|----------|
| `./app_data`   | `/app/app_data`    | SQLite DBs (`app_data/pricing.db`, WAL mode) + product images |
| `./app_assets` | `/app/app_assets`  | Shared assets served at `/app_assets/<name>` (favicon, `logo_company.jpg`, `pdf_footer_image.png`, `RIG.png`, `defaults/`) |
| `./static/img` | `/app/static/img`  | Uploaded logo — the upload writes here at runtime; **without this mount the logo is lost on the next rebuild** |

Anything not under these mounts is part of the image and resets on rebuild.

## Backups

- Preferred: the admin UI's backup download (DB dump without stopping the app).
- Cold copy (safest):
  ```bash
  docker compose stop
  cp app_data/pricing.db /path/to/backup/          # include -wal/-shm files if present
  docker compose start
  ```
  Never copy `pricing.db` while the container is running — it is in WAL mode.

## Logs

```bash
docker logs qp-crm            # one-shot dump
docker compose logs -f app    # follow live
```

gunicorn/Flask output goes to the container's stdout (visible via docker logs).

## Running the test suite (Phase 1)

The pytest suite ships in the image and runs with one command:

```bash
docker compose build app            # only when code/tests/deps changed
docker compose run --rm app pytest
```

The suite is fully isolated from the live stack: it patches the data paths
into a throwaway `/tmp/qp-crm-tests` tree inside the container and never
touches the bind-mounted `app_data/pricing.db`. Details, golden-PDF
re-baselining and the characterization discipline live in `tests/README.md`.

## Quick reference

```bash
docker compose ps              # health status
docker compose config          # validate docker-compose.yml
docker compose down            # stop + remove container (data safe: bind mounts)
docker compose up -d --build   # manual rebuild + restart
```
