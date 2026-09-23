# Agent Note: retire-legacy-global-api-key

Status: implemented

## Problem

The legacy global API key (global_settings.api_key, live value 73f482ad…) authenticated /api/v1 with no per-user attribution (audit rows kind='global', username NULL). The user approved full removal: the key was a standing shared secret, and product_sync's page JS embedded it into every rendered page source.

## Decision

shared/auth.resolve_api_identity() now returns ONLY ('user', username, user_id) / ('user-denied', ...) / None — the ('global', None, None) fallback and its secrets.compare_digest against global_settings.api_key are gone. pricing/api_v1.require_api_key() accepts Bearer per-user keys, and when no Authorization header is present falls back to the logged-in session: get_user_by_id + user_has_module(user_id, 'pricing'); anonymous -> 401, inactive user -> 403, grant-less staff -> 403; identity is stamped g.api_key_kind='user' + username so api_audit attribution is unchanged (always a username). product_sync.html no longer embeds const API_KEY; its apiFetch uses credentials='same-origin' and no Authorization header. Removed: admin/routes/settings.py api_key_generate/api_key_revoke routes, the Legacy Global API Key card + toggle script in admin/templates/admin/api_keys.html, the dashboard API panel (already gone), admin app/core/api_keys get_api_key plumbing. Kept as stubs: generate_api_key() raises NotImplementedError; get_api_key() reads a leftover row (None when absent); validate_api_key() returns False; revoke_api_key() deletes the dead row — so restored old backups import cleanly and the leftover secret can be removed. The live DB's api_key row (73f482ad…) was deleted after deploy. pricing/app.py dev-run block no longer auto-generates a key.
## Alternatives considered

**Keep the global key working but stop showing it (silent deprecation).** Rejected: the user explicitly chose full removal for security; a secret that authenticates but is undocumented is worse than either extreme. **Keep the key row in global_settings but ignore it in resolve_api_identity only.** Rejected: leaves a live-looking 48-hex secret at rest in the DB — dead credentials must be deleted, not just unwired. **Give product_sync its own scoped key instead of session auth.** Rejected: the page is already behind require_module('pricing') with a unified session; a key would re-introduce exactly the unattributed shared secret this change removes, and session identity makes the api_audit attribution BETTER (username instead of NULL). **Hard-delete generate_api_key/revoke_api_key from shared/auth.py.** Rejected: restored pre-retirement backups would crash on import; stubs (NotImplementedError / read-only get_api_key) keep old DBs detectable and imports safe.
## Consequences

Bought: every /api/v1 audit row now carries a username (kind='global' can no longer occur); one less secret at rest in global_settings; product_sync no longer embeds any credential in page HTML (previously ANY user who could load the page saw a working API key in view-source). Cost: integrations still sending the old key get 403 starting now — the only known senders were the product_sync page (migrated) and ad-hoc curls; a restored old backup would reappear with an api_key row that silently authenticates nothing (detect via get_api_key(), delete via revoke_api_key()). The session fallback means any active user with the pricing grant can call /api/v1 from a browser session — audited under their username, gated identically to the pricing pages themselves.

