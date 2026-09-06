# Agent Note: date-format-single-source-of-truth

Status: implemented

## Problem

Audit M4: `date_format` had two sources of truth — the `global_settings.date_format` DB row (written by Admin -> Default Settings, `admin/routes/settings.py update_settings`) and a per-browser `date_format` cookie that the /settings page wrote (`settings/app.py settings_index`) and that `get_date_format()` (then `shared/web.py`) fell back to when the DB read missed. Because `init_db` always seeds the DB row, the cookie never actually won — but one browser could still be served formatting from a stale cookie in edge paths, and the UI implied per-user control while golden/PDF output stayed company-consistent. Users saw per-page inconsistency; golden/PDF output must be company-consistent.

## Decision

The global_settings row is now the ONLY source of the date format.

- `qp_crm/shared/web.py get_date_format()`: reads ONLY `SELECT value FROM global_settings WHERE key='date_format'` and returns `'YYYY-MM-DD'` when the row is missing, empty, or the read raises. The `request.cookies.get('date_format', ...)` fallback is deleted.
- `qp_crm/settings/app.py settings_index()`: GET passes only `current_theme`; POST reads only `theme` and sets only the `theme` cookie (theme stays per-browser — out of scope). The `date_format` cookie write is removed; a `date_format` form field (e.g. from an old client/test) is simply ignored.
- `qp_crm/settings/templates/settings/settings.html`: the date-format `<select name="date_format">` block is removed; the page now edits only the theme. Admin dashboard (Admin -> Default Settings) is the single place to change the company-wide format.
- All formatting consumers already funnel through `get_date_format()` — the app-wide `format_date` Jinja filter (`web.format_date_filter`), the offer blueprint context processor (`offer/app.py`), and the offer PDF context (`offer/routes/pdf.py:103`) — so no other read site changed.
- Characterization tests: `tests/characterization/test_date_format_global_settings.py` pins the contract with `app.test_request_context` carrying a stale `HTTP_COOKIE: date_format=MM/DD/YYYY`: DB row set (DD/MM/YYYY) wins; row deleted or empty -> `YYYY-MM-DD` with the cookie ignored. Each test snapshots and restores the session-scoped suite DB row via a module autouse fixture.
- Docs: `PROGRAM_DOCUMENTATION.md` section 9.1 and `tests/README.md` describe the cookie-free contract.

NOT done: the theme setting is NOT consolidated (cookie on /settings vs a `global_settings.theme` row the admin dashboard writes — pre-existing, out of scope). The dead, unrendered `offer/templates/offer/settings.html` and `pricing/templates/pricing/settings.html` copies still carry date-format selects; no route renders them, so they cannot write or read cookies — left for the shared-template/i18n owner. No PDF-rendered template and no `qp_crm/shared/utils.py` TRANSLATIONS/format_date were touched.

## Alternatives considered

**Keep the date-format control on /settings but make it write global_settings instead of a cookie** — lost: /settings is public (no role gate), so an anonymous or staff visitor could silently change company-wide formatting that golden PDFs depend on; the admin dashboard already provides the one authenticated, intended place. Removing the control makes the single authority structurally obvious.

**Keep the cookie as the preferred source** — lost outright: contradicts the requirement that golden/PDF output be company-consistent, and the DB row is the documented company setting.

**Also delete the dead offer/pricing settings.html date-format selects in this commit** — lost: they are unreachable leftovers (the comment in `settings/app.py` already documents them as dead name-collision copies) and belong to the shared-template cleanup debt owner.

## Consequences

Cost: users who had picked a per-browser format lose that choice — formatting is company-wide only, matching the PDF/golden requirement. Stale `date_format` cookies already in browsers remain set but inert (nothing reads them anymore). The change is entirely a read-path and UI removal: no write path moved, so no migration is needed; `global_settings` already seeded `YYYY-MM-DD` on every boot. Tests: 254 passed, 3 skipped on the host (golden-PDF skips by design). Related notes: `../testing/2026-09-05-golden-host-skip-and-retired-change-password-contract.md` (why golden PDFs skip on host), `../feature/2026-09-04-phase3-unified-auth-roles-csrf.md`.
