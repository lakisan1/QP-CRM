# Agent Note: theme-cookie-applied-every-screen

Status: implemented

## Problem

The /settings theme selector only worked on some pages: / (landing) and /offer/offers stayed dark. Root cause was structural: theme is stored in the per-browser 'theme' cookie but only some blueprints injected it into their templates — main.py (landing, auth/login) injected no theme at all, offer's registered context processor never injected theme (a dead shadowed inject_helpers sat at offer/app.py:61), admin had no processor and its dashboard read a legacy global_settings.theme DB row instead, and several screen templates hardcoded data-theme="dark".

## Decision

Shipped in commit 555ce2a (merged on Dev): ONE app-level context processor in qp_crm/main.py — app.context_processor(inject_theme) returning dict(theme=get_theme()) — fires for every render_template on the consolidated app, so the same 'theme' cookie (default 'dark', 1y, set by /settings) now reaches landing, pre-login /login (get_theme reads request.cookies without needing a session), every module blueprint incl. offer, and admin. Screen templates that hardcoded data-theme="dark" (templates/landing.html, auth/login.html, admin users/api_keys/pdf_templates/pdf_template_edit/admin_login) now use {{ theme|default('dark') }}. Admin dashboard (admin/routes/core.py) reads the cookie via get_theme() instead of the global_settings.theme DB row, and the dashboard Default Settings Theme select (admin/routes/settings.py) now sets the same cookie /settings sets instead of writing the DB row; the legacy DB row stays seeded/backup-only and is unread. NOT done: no per-user DB theming (cookie is per-device by design), no PDF template changes (none reference theme; golden bytes stable, full suite 268 passed 3 skipped), PWA theme-color meta stays dark-static, offer/app.py dead duplicate inject_helpers left untouched, inert global_settings.theme seed left in place. 5 new smoke tests in tests/smoke/test_theme_consistency.py pin: settings POST sets the cookie, landing + /offer/offers light-with-cookie/dark-without, pre-login login follows the cookie, dashboard ignores a stale DB theme row.
## Alternatives considered

Fixing per-blueprint (adding theme injection to offer's processor + admin + main) was rejected: it closes only the known offenders and the same 'page forgot its processor' bug class stays open for any future blueprint. Migrating theme to per-user DB storage (global_settings or a users.theme column) was rejected: /settings is a per-device page by design (like the date_format cookie we retired the other direction in audit M4), and the user asked to check how it is stored, not to redesign it.
## Consequences

One subtle shift: the admin dashboard previously followed its own Default Settings DB theme (per-company), now it follows the operator's browser cookie like every other page — the Default Settings Theme select writes the cookie on redirect so behavior appears identical per browser. Anyone who set a company-wide theme via the DB row before this change will see the dark default until they pick a theme (cookie absent); the row is inert, not deleted. Live verified: pre-login /login renders light with the cookie and dark without; authenticated landing and /offer/offers are pinned by the smoke suite.

