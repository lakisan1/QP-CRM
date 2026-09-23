# Agent Note: install-update-guides

Status: implemented

## Problem

The repo front page (README.md) had no link to installation or update instructions, and its "How to Update" section was stale — it still told Docker users to run ./run_apps.sh (the bare-metal script), while the shipped update system is pull-deploy via ./deploy.sh. The user also wants updates to require no manual step at all if possible (git pull + redeploy unattended), and asked whether an update button inside the admin panel would work with Docker.

## Decision

README.md returns on Dev (it was renamed to README_API.md in e70abaa) as the project front page with a "Guides" table linking INSTALL.md, UPDATE.md, DOCKER.md and README_API.md. INSTALL.md covers first-time Docker setup from the public GHCR image (prerequisites, compose + .env.example download, six secret keys via secrets.token_hex, docker compose up -d, first-login rotation of admin/Admin1, data-location table). UPDATE.md documents both update modes: manual ./deploy.sh (backup DB → record rollback tag → pull → recreate → health-wait; failure aborts untouched) and unattended Watchtower, shipped as watchtower-compose.example.yml — a compose override adding a label-scoped Watchtower (WATCHTOWER_SCHEDULE nightly 04:00, WATCHTOWER_CLEANUP, WATCHTOWER_LABEL_ENABLE so it never touches other containers on the host; the app service gets com.centurylinklabs.watchtower.enable=true). The example is validated with docker compose config against the main stack. DOCKER.md's First run/Updating sections now describe pull-deploy (compose up -d pulls ghcr.io/lakisan1/qp-crm:latest; --build is the local-dev fallback). The stale README "How to Update: ./run_apps.sh" section is replaced with deploy.sh/rollback.sh + a bare-metal note.
## Alternatives considered

**Update button in the admin UI** — the user explicitly asked about it. Rejected for a shipped reason: a container cannot safely replace itself — recreating the container kills the very process performing the update, so an in-UI update would either die mid-flight or need a supervisor daemon outside the container (docker.sock mounted into the Flask app), which hands the web app root-equivalent Docker API access — a serious attack surface for a LAN-exposed app. deploy.sh/Watchtower do the same job with zero new attack surface. Documented in UPDATE.md so the question stays answered.

**Move Watchtower into the main docker-compose.yml** — auto-update as a default would surprise operators (updates land unattended); it is a choice, so it ships as an opt-in override file the operator copies into place.

**Wiki / GitHub Pages for the guides** — docs live next to the code they describe and version with it; the README links stay valid on every branch.
## Consequences

Bought: a public-repo front page that routes a beginner from zero to a running instance (INSTALL.md) and answers the recurring "how do I update / did I lose data / can I go back" questions (UPDATE.md) without reading DOCKER.md; an opt-in path to fully unattended updates. Cost: README.md is restored on Dev while README_API.md keeps its renamed role — the two-doc split is now intentional and must be maintained; the Watchtower example adds a second supported update path whose failure modes (silent unattended rollbacks) are documented but not preventable by the repo. NOT done: no update button in the admin UI (deliberate — see Alternatives); Watchtower does not run deploy.sh (it does pull+recreate only, no DB snapshot — the bind-mount data safety guarantee is the same, but the pre-deploy .db snapshot is a deploy.sh feature); no notification channel configured in the example (WATCHTOWER_NOTIFICATIONS left empty on purpose).

