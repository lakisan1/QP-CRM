# Agent Note: public-ghcr-image-safety

Status: implemented

## Problem

The user wants the GHCR image publicly pullable: anyone should be able to download it and self-host/update without GitHub credentials, because the image contains only code — no data, no secrets. Before flipping the package visibility to public, the build context had to be audited: whatever COPY . . ships is what the world gets, and two candidate leak paths existed (runtime data dirs and the local backups/ directory with pre-deploy DB snapshots that contain password hashes).

## Decision

The GHCR package ghcr.io/lakisan1/qp-crm is the user's choice to make PUBLIC: the image ships application code only. Safety boundary is enforced by build-time exclusion, verified by simulating the .dockerignore rules against the tree: app_data/ (pricing.db, product_images, .bak), backups/ (pre-deploy snapshots — added to .dockerignore in 7392d4b; it was gitignored but NOT dockerignored, so local DB backups with password hashes WOULD have entered the build context), .env, .agents/, venv/ never enter the context; git-tracked files contain no secrets (only .env.example with placeholders). Runtime secrets come from the instance's own .env via env_file; user data via bind mounts. Known-and-accepted public exposure, documented here: (1) DEFAULT_PASSWORDS bootstrap values ("Admin1"/"Price1"/"Offer1"/"Rent1") ship in qp_crm/shared/auth.py — they are first-login bootstrap seeds, hashed at rest, and the operator is expected to rotate them; they are ALSO in the public git history since P2/P3, so the repo's public face already assumes rotation; (2) README/docs mention generic LAN IPs; (3) product/branding images and the pytest suite ship in the image by design.
## Alternatives considered

**Keep the package private + docker login per host** — works, but the user explicitly wants one-command updates on any machine with zero GitHub account setup; public package is the product requirement.

**Separate public "distribution" repo** — a second repo/image for public consumption would fork the pipeline and drift; same image, same repo, simpler.

**Scrub default passwords from the codebase before going public** — the right long-term hardening, but it changes the bootstrap contract (docs, tests, admin bootstrap flow) and needs the user present to set real passwords; recorded as follow-up rather than blocking the visibility change.
## Consequences

Bought: the image is safe to flip public — verified no data, secrets, or customer content in the build context; anyone can pull and self-host without GitHub auth. Cost: the repo's public history stays as-is (default bootstrap passwords are documented in code and docs; product images, branding and KANBAN.json ship in the image); the bootstrap hardening follow-up is now more urgent since public viewers can read the defaults. NOT done: default bootstrap password rotation/scrub (user action, needs their input), no image-minimization pass (tests + baselines still ship by design for docker compose run app pytest), repo itself stays private — only the GHCR package goes public.

