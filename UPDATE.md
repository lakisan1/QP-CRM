# 🔄 Updating — QP-CRM (Docker)

An update swaps **only the code** (the image). Your data — users, passwords,
offers, contracts, images — lives in server folders (`app_data/`,
`app_assets/`, `static/img/`) and is **never touched**.

---

## Mode 1 — Manual (one command) ✅ recommended

In the folder containing `docker-compose.yml` and `deploy.sh`:

```bash
git pull          # pulls a newer deploy.sh/compose if they changed (optional)
./deploy.sh
```

`deploy.sh` automatically:
1. takes a **database backup** → `backups/pre-deploy-<date>.db` (if the backup fails, the update is aborted — nothing is touched)
2. records the current version → `backups/last-deployed-tag` (the rollback point)
3. pulls the new image (`docker compose pull`)
4. recreates the container on the new image
5. waits for the healthcheck (~90 s) and reports

If it prints `qp-crm is healthy` — the update succeeded. Done.

### If something goes wrong — rollback

```bash
./rollback.sh
```

Returns to the version that was running before the update (and takes its own
backup before returning). Data stays as it is. Once a fixed version ships,
run `./deploy.sh` again.

> The scripts work without build capacity on the server: the image is pulled
> from `ghcr.io/lakisan1/qp-crm:latest`, not built on the server.

---

## Mode 2 — Fully automatic (Watchtower) 🤖

Want updates to happen **by themselves**, with nobody running anything?
[Watchtower](https://containrrr.dev/watchtower/) is a small helper container
that periodically checks whether a newer image exists and, if so, does
exactly what `deploy.sh` does (pull + recreate).

### Setup (once)

Create a file `docker-compose.override.yml` **next to** the main
`docker-compose.yml` (the repo ships an example: `watchtower-compose.example.yml`)
with this content:

```yaml
services:
  watchtower:
    image: containrrr/watchtower
    container_name: watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      # (optional) Docker login for a PRIVATE image — NOT needed for a public one:
      # - ~/.docker/config.json:/config.json:ro
    environment:
      # checks every day at 04:00; `@hourly`, `@daily`, `@weekly` also work
      - WATCHTOWER_SCHEDULE=0 0 4 * * *
      # remove the old image after an update (keeps the disk clean)
      - WATCHTOWER_CLEANUP=true
      # restart ONLY labeled containers (never touches the rest of the machine):
      - WATCHTOWER_LABEL_ENABLE=true
    labels:
      # Watchtower watches ONLY containers carrying this label:
      - com.centurylinklabs.watchtower.enable=true
```

> ⚠️ Note: `WATCHTOWER_LABEL_ENABLE=true` means Watchtower updates ONLY
> containers that carry the `com.centurylinklabs.watchtower.enable=true`
> label. The repository example (`watchtower-compose.example.yml`) already
> includes that label on the `app` service — if you write the override by
> hand, add it too:
>
> ```yaml
> services:
>   app:
>     labels:
>       - com.centurylinklabs.watchtower.enable=true
> ```

Start it:

```bash
docker compose up -d
```

From then on: every new image on `ghcr.io/lakisan1/qp-crm:latest` (which CI
pushes only after all tests pass) is automatically pulled and applied at 04:00.

### Why manual mode is still the "safer" one

Automation is convenient, but:
- updates arrive **without you choosing the moment** (work hours vs. night)
- rollback still exists (`./rollback.sh`), but you have to notice the problem yourself

Recommendation: **manual** on the production instance (`./deploy.sh` whenever
you hear about a new version), **automatic** on a test/team instance.

---

## What an update does NOT do

- **Does not touch data** — the database, passwords, offers, images are on disk, outside the image
- **Does not change `.env`** — your secret keys stay as they are
- **Does not delete old versions** — `rollback.sh` can always go back
  (clean up old images manually: `docker image prune -f`)

## Common situations

| Situation | Fix |
|---|---|
| `deploy.sh` prints *backup FAILED* | Nothing was touched — check disk space (`df -h`), then run it again |
| Update stuck (container unhealthy) | `./rollback.sh` — returns the previous version |
| `git pull` error (local changes) | It warns and continues — only the image pull matters |
| I need a specific version | `./rollback.sh sha-<commit>` (every build gets such a tag) |

## Updating through the admin panel (a button in the UI)?

There is deliberately **no** update button in the admin panel. A container
cannot safely replace itself (a container restarting itself kills the very
process performing the update — the update would be left half-done). Server
scripts are the reliable way: `./deploy.sh` (or Watchtower for full automation).
