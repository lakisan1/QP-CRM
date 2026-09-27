# Agent Note: offer-duplicate-contact-id

Status: implemented

## Problem

POST /offer/offers/<id>/duplicate (Duplicate button on an offer) returned a bare "Internal Server Error" in production since the P5 directory unification added offers.contact_id. The column was added to edit_offer's UPDATE and new_offer's INSERT, but duplicate_offer's INSERT kept its old 29-placeholder column list — sqlite3.OperationalError: 29 values for 30 columns, no error surfaced to the user because the Dockerized gunicorn app logs nothing accessible and the endpoint has no try/except.

## Decision

duplicate_offer in qp_crm/offer/routes/offers.py now lists contact_id in its INSERT column list and binds offer["contact_id"], so the copy stays linked to the same directory party as the original (is_template still hard-coded to 0, offer_number still cleared for renumbering). Verified by direct route replay: original 500-causing call now 302-redirects to /offer/offers/<new>/edit with items and contact_id carried over; offers tests 30 passed. Deployed by rebuilding the qp-crm:phase3 image (docker compose build/up, healthcheck healthy) — the running gunicorn serves from the baked image, not the checkout, so a rebuild is mandatory for any code change.
## Alternatives considered

**Copy with contact_id left NULL (user re-picks the party).** Rejected: a duplicate is supposed to be a faithful copy; silently dropping the musterija link would make every duplicate offer lose its directory binding and per-user app-access data would not match either. **Hot-patch the file inside the running container (docker cp) instead of rebuilding.** Rejected: the image is built with COPY . . from this checkout, so an in-container edit would be overwritten on the next deploy.sh and drift between image and repo. **Add a try/except with a flash message around the INSERT.** Rejected as a follow-on improvement, not the fix: masking a schema/query mismatch is worse than a loud 500; the column-count error is a programmer bug and should fail loudly in tests.
## Consequences

Bought: Duplicate works again and preserves the directory link. Cost/obligations: any future offers column must now be added in FOUR places — shared/schema.py CREATE, migrate_schema ALTER (via ensure_column-style guard), new_offer INSERT, edit_offer write path, and duplicate_offer INSERT — none of these are generated from the schema, so column-count mismatches like this one can recur; a test covering duplicate_offer against the unified schema would have caught it and is the cheap follow-up. Also: deploy requires sudo for the docker socket (user dsh is not in the docker group) — ./deploy.sh fails for non-root docker; run the compose steps with sudo.

