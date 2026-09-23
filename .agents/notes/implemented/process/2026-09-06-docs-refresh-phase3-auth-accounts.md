# Docs refresh after Phase 3 + admin-only seeding

## Problem
Four top-level docs still described the pre-Phase-3 auth model: per-app
default passwords (Admin1/Price1/Offer1/Rent1), per-app logins, a self-service
password change, and a public (zero-login) Sale pricelist — all gone in code
since Phase 3 (single users table, admin-only bootstrap, per-user module
grants, per-user API keys, CSRF shield).

## Decision
Docs now state shipped Phase-3 reality, verified against code before writing
(grep/read on qp_crm/ in the same tree):

- **README_API.md** — "Security Management" bullet replaced with User
  Management; the four default credentials removed; new "First Login &
  Accounts" section: ONE login at /login (per-app logins redirect with safe
  ?next=), ONLY the admin account is seeded (default Admin1, or the legacy
  admin_password global-setting value when present), staff accounts are
  created by admin in Admin → Users with per-module grants
  (pricing/offer/rent/sale) and roles admin/staff (admins bypass grants), all
  password changes are admin-managed in Admin → Users, logout button lives on
  the Settings page (/settings) routing through /logout, 8h sliding session.
- **API_INSTRUCTIONS.md** — added "Getting a per-user key" steps (Admin → API
  Keys; raw key shown once, SHA-256 + 12-char prefix stored; header
  Authorization: Bearer <key>; no CSRF token on API calls); kept the
  deprecated-but-working legacy global key wording.
- **FEATURES.md** — "Role-based Authentication" bullet replaced by "Unified
  Accounts & Access Control" (admin/staff + per-module grants + CSRF +
  per-user API keys); the false "Standalone Read-Only Instances (zero-login)"
  bullet replaced by the Sale read-only pricelist gated by the sale grant.
  PWA bullet untouched (another agent owns that claim).
- **PROGRAM_DOCUMENTATION.md** — spot-fixed auth/account drift only: sale
  section (no longer public; require_module("sale")), settings 6.1 (public
  blueprint, cookie-based, no login route), admin 8.1 (require_role("admin")
  gate, unified-login redirects, users + per-user API-keys functions/routes,
  update_passwords and /api_key/* marked LEGACY), section 11 role/routing
  paragraph corrected to require_module reality and logout-UI location.

NOT changed (explicitly out of scope or owned elsewhere): the whole-file
architecture description of PROGRAM_DOCUMENTATION section 1+ (still describes
six sub-apps under DispatcherMiddleware — a larger rewrite than this card
allows), README_API PWA instructions paragraph, code comments that still carry
drift (users.py docstring claims a /change-password route and a
must-change-on-first-login flash that the auth code contradicts), and
AUDIT_FINDINGS.md/DOCKER.md (DOCKER.md was already Phase-3 accurate).

## Alternatives
- Rewriting PROGRAM_DOCUMENTATION.md architecture sections (1–10 module
  headers, DispatcherMiddleware) — rejected: card scope is "spot-check
  auth/account route sections; do not rewrite the whole file".
- Removing the legacy "Change Passwords" dashboard card / /admin/update_passwords
  from the docs entirely — rejected: the route and UI card still exist in
  code (they write to users via set_password), so docs mark them LEGACY with a
  pointer to Admin → Users instead of claiming they are gone.

## Consequences
- Four files changed, docs-only; host pytest baseline stays 251 passed, 3
  skipped (docs cannot affect tests).
- A follow-up docs pass should rewrite PROGRAM_DOCUMENTATION.md's structural
  sections (single Flask app + blueprints under qp_crm/, qp_session,
  app_data/ paths) — flagging the remaining architecture drift the
  spot-check intentionally left in place.
