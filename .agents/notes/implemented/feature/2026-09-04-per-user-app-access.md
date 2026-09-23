# Agent Note: per-user-app-access

Status: implemented

## Problem

The phase-3 unified model gave every staff user access to all three business apps (pricing/offer/rent). The owner wants least-privilege per user — e.g. an offers-only employee — controlled from the admin panel, and explicitly does NOT want per-app passwords back.

## Decision

Admin -> Users now carries per-user app access: a user_modules junction table (UNIQUE(user_id, module), FK to users) plus a users.modules_set marker, exposed as pricing/offer/rent checkboxes per staff row (POST /admin/users/<id>/modules, own-password confirmed like every sensitive Users action) and pre-checked on the create form (create_user takes modules=None -> all MODULE_CHOICES). Enforcement moved from require_role("staff","admin") to require_module(module) in shared/web.py on the pricing/offer/rent blueprints: same per-request DB re-read as require_role, so revocation hits on the user's next click; the admin ROLE bypasses the grant check entirely, making the role gate binary admin/not-admin. seed_default_user_modules materializes all three grants once per staff user at boot (marker prevents re-granting sets the admin deliberately emptied), and factory_reset in backup.py now runs the full init_users_table contract (migrate_users + seed_users_from_legacy + seed_default_user_modules + scrub) after DELETEing user_modules/api_keys/users — its old inline re-seed silently produced grant-less staff and 403'd half the suite. Extending to a Phase-4 module is one append to MODULE_CHOICES plus one require_module call.
## Alternatives considered

Separate per-app passwords — the pre-phase-3 mechanism the owner explicitly rejected. A JSON/CSV modules column on users — lost to the junction table: FK-enforced, queryable with EXISTS, no parsing. Caching grants in the session at login — lost because deactivation/grant-revocation must bite immediately, matching require_role's per-request re-read. Per-module ROLES (e.g. 'offer-only' role) — lost: roles stay the binary admin/not-admin distinction and grants carry the per-user nuance; N modules x M roles would explode combinatorially.
## Consequences

Bought: least-privilege per user with one admin page, instant revocation, and a schema that scales to future modules. Cost: test fixtures that assumed staff-opens-everything now depend on the boot migration (tests/auth/test_role_gates.py, smoke); the role_change test's semantics changed (a non-admin role with grants still reaches granted apps — pinned in test_role_gates.py); FK order matters in every test cleanup that deletes users (user_modules rows first); require_role is now used ONLY by the admin blueprint. Consequence to watch: MODULE_CHOICES is the single source for UI checkboxes and gates — a Phase-4 module must update it and re-run the module-scoped migrations, and users get no new-module access until the admin grants it (grants do not auto-extend).

