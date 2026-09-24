# Agent Note: country-dropdown-directory

Status: implemented

## Problem

User request: the Država field (contact form + location add/edit forms) must become a dropdown like the offer form's country select — free-text entry lets typo countries ('Hrvatskaa', 'SRBIJA') into the data and breaks grouping/filtering later.

## Decision

Country entry is now a <select> fed from qp_crm/shared/countries.get_country_list() (the SAME COUNTRIES list the offer form uses — 205 entries, regional countries first) at all three directory entry points: the contact form (contacts/form.html, selected = saved value, new-contact default = first entry Srbija), the detail page's "Dodaj lokaciju" form (default Srbija), and the per-row "Izmeni" — which changed from a hidden-only one-click submit into a <details> inline form exposing ALL location fields (name, address, city, postal_code, country select, contact_name, contact_phone) so an edit no longer silently keeps stale values for the fields it did not render. All four render sites in qp_crm/contacts/routes/directory.py pass countries=get_country_list(). Language naming: the contacts form uses the app-level context processor's current_lang (main.py inject_i18n), NOT the offer routes' ad-hoc current_language variable.
## Alternatives considered

["**Keep the location 'Izmeni' as hidden-only-name form and route users to a separate location edit page**: rejected — an extra page for a 7-row table is overkill; the inline <details> form keeps the edit on the same screen with zero navigation, and the previous hidden-only form was already a UX trap (it silently dropped address/city edits the user typed elsewhere).", "**Add a free-text fallback option ('Druga država...') to the select**: rejected — it re-opens exactly the typo problem the user is closing; if a country is missing from the shared list, the fix is adding it to COUNTRIES (one migration-style edit), not a per-form escape hatch.", "**Build the select client-side from a JSON endpoint**: rejected — the list is static (205 entries); server-side render is one loop in the template, no JS dependency, and works without JS like the rest of the directory forms.", "**Per-module country lists (shorter list for locations)**: rejected — two lists drift; the offer form already renders the full COUNTRIES list and users expect the same options everywhere."]
## Consequences

Bought: typo-proof country entry everywhere the directory asks for a country (contact form + location add + inline location edit), one shared list, default Srbija on new entries; existing stored values that match the list stay selected (roundtrip-tested), and a stored value NOT in the list (e.g. 'Hrvatska xyz' typo from earlier) renders unselected — the user must pick a valid one on next save, which is exactly the cleanup the user wants. Cost: legacy typo values remain visible in the detail table as '—'-style text until the row is re-saved; the 205-entry select renders three times on a locations-heavy detail page (negligible bytes, no JS). Negative guarantees: no data migration rewrites existing contacts.country (snapshot discipline — only new saves go through the list); the list itself stays static in qp_crm/shared/countries.py (fixed-list discipline; adding a country is a code edit, not runtime data).

