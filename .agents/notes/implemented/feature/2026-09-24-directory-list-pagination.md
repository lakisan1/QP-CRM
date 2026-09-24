# Agent Note: directory-list-pagination

Status: implemented

## Problem

The directory list rendered all 2156 contacts in one table — slow load and endless scroll. User asked to reuse the existing pagination system from Settings (default_items_per_page) and the offer list.

## Decision

contact_service.list_contacts(include_archived, search, roles, kind, page=None, per_page=None): without per_page it returns all rows (picker mode, unchanged contract); with per_page it appends LIMIT/OFFSET to the SAME WHERE-building path and returns (rows, total_count) via a COUNT(DISTINCT c.id) query sharing the identical clauses. The directory list route (qp_crm/contacts/routes/directory.py list_contacts) reads ?page= (1-based, min 1), page size from global_settings 'default_items_per_page' (helper _items_per_page(), fallback 25 — same key and fallback as qp_crm/offer/routes/offers.py), renders the offer-list-style controls (« Prethodna / Strana X od Y (N kontakata) / Sledeća ») in contacts/list.html, carrying search/kind/role/archived through every page link. Out-of-range ?page= redirects to the last page. Bug fixed during work: appending LIMIT after a trailing ';' produced a two-statement string — sqlite3.ProgrammingError; the ';' now appends after LIMIT. All pagination tests, suite 356 passed.
## Alternatives considered

["**Scroll-load / infinite scroll (JS fetch on scroll)**: rejected — the user explicitly asked for the page-division system already present in Settings and Offers; infinite scroll also breaks Ctrl+F, print, and deep links.", "**Client-side JS pagination over one big JSON payload**: rejected — still ships all 2000 rows to the browser on first load, which is the exact slowness being fixed; server-side LIMIT/OFFSET moves the cost to SQL.", "**Separate page-size for contacts (hardcoded 50)**: rejected — page size already exists as a user setting (Settings -> default_items_per_page, consumed by the offer list); a second knob duplicates the setting and drifts.", "**Keyset (cursor) pagination for scale**: rejected — SQLite OFFSET at 2000 rows is microseconds; the offer list already set the LIMIT/OFFSET precedent, and cursors complicate 'Strana X od Y' display that the user expects."]
## Consequences

Bought: first paint renders 25 rows instead of 2000+ with per-row role-badge queries down from ~2000 to 25; page size follows the existing Settings knob so users control density in one place; navigation preserves search/kind/role/archived context through page links. Cost: list_contacts now has TWO return shapes — (rows,) without per_page for pickers, (rows, total_count) with it — every future caller must know which mode it is in; the count query doubles the SQL work per page load (negligible at this scale); stale ?page= links now redirect instead of 404ing/empty-rendering (a bookmark may land one page earlier than before). Negative guarantees: pickers NEVER paginate — directory_choices/_directory_party_choices/rent client picker call list_contacts without per_page and still see all contacts (autocomplete across pages would silently hide parties); SQL string building interpolates only int()-coerced page numbers (params stay ?-bound); out-of-range pages redirect to the LAST page (clamped), never an empty table.

