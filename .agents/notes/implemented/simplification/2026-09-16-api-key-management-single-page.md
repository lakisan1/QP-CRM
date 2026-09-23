# Agent Note: api-key-management-single-page

Status: implemented

## Problem

API key settings were split across two admin pages: the legacy global-key panel (show/generate/revoke + curl quick-test) lived on the Dashboard while per-user key issuance/revocation lived at /admin/api_keys. The user wants /admin/api_keys to be the ONLY place for API settings.

## Decision

The dashboard card and its toggleApiKeyVisibility script are removed from admin/templates/admin/admin_dashboard.html; admin/routes/core.py no longer fetches api_key_value/api_key_exists. The full legacy card (blurred key display + Show toggle, Generate New Key, Revoke Key, curl quick-test) now renders at the bottom of admin/templates/admin/api_keys.html, below the per-user key table, and admin/routes/api_keys.py list_api_keys() supplies api_key_value/api_key_exists via get_api_key(). The legacy POST routes /admin/api_key/generate and /admin/api_key/revoke in admin/routes/settings.py keep their endpoint paths but redirect to admin.list_api_keys (was admin.index) on both success and wrong-password. API_INSTRUCTIONS.md now points the legacy-key mention at Admin Panel → API Keys → Legacy Global API Key. The revoke form renders only when a key exists (unchanged behavior). API auth contract is untouched: resolve_api_identity() still checks per-user keys first, then the global key; /health needs no auth; bad key 403, missing key 401.
## Alternatives considered

**Keep the panel on both pages.** Rejected: two UIs mutating the same api_key row invites confusion about which key is live, and the user explicitly asked for /admin/api_keys to be the ONLY place. **Retire the legacy global key entirely (drop the card).** Rejected: existing integrations (AI agent tooling) still authenticate with the live key 73f482ad…; removal would break them — the card moved with its DEPRECATED warning intact and retirement remains a later phase. **Have api_key_generate/revoke redirect to the dashboard.** Rejected: the actions' only UI now lives on /admin/api_keys, so bouncing the admin back to the dashboard would strand them away from the keys they just changed.
## Consequences

Bought: one obvious place for all API settings; dashboard loses a deprecated panel it only duplicated; generate/revoke feedback now appears next to the key table. Cost: admins who had the curl quick-test bookmarked on the dashboard must look one nav-link further; the legacy routes (/admin/api_key/generate, /admin/api_key/revoke) keep their old endpoint paths, so any bookmarked POST integration still works but now lands on /admin/api_keys after redirect. Coverage gap: no automated test pins the dashboard's lack of the API panel — the functional checks were run ad hoc on an isolated DB (dashboard clean, api_keys complete, legacy key 200, per-user key 200, bad key 403, /health 200, revoke kills access, wrong-password flash) plus live-server curls after deploy (legacy key 200, bad key 403, no key 401, per-user key 200).

