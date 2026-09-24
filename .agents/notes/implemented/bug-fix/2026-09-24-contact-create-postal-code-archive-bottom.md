# Agent Note: contact-create-postal-code-archive-bottom

Status: implemented

## Problem

User report: a new contact's Poštanski broj did not save on first create — only after an edit roundtrip. Root cause: when postal_code was added to the schema and _CONTACT_FIELDS (2026-09-24), create_contact's INSERT column list and VALUES tuple were missed (they stopped at city, country), so the field was dropped on insert while update_contact handled it fine. Second request: move the Archive button from the detail page's top action row (next to Izmeni) to the bottom — too easy to mis-click.

## Decision

create_contact's INSERT (qp_crm/services/contact_service.py) now lists postal_code between city and country — 19 explicit columns, explicit ?-bound tuple matching _CONTACT_FIELDS. The archive form moved from the detail page's top action row (next to Izmeni) to the BOTTOM of contacts/detail.html, below the Povezani dokumenti card, separated by a border-top, with the confirm dialog and an explanatory note ('Arhiviranje ne briše kontakt — dokumenti koji ga referenciraju ga i dalje rešavaju po id-u'); the top row now carries only Izmeni.
## Alternatives considered

["**Fix by reading the column list from _CONTACT_FIELDS dynamically in create_contact**: rejected — the INSERT order must match the VALUES tuple order exactly; a dynamic build saves no duplication worth the indirection and would obscure which columns the create path actually writes; an explicit column list + explicit tuple is the same convention update_contact uses (explicit assignments).", "**Move Archive into a dropdown/menu instead of the page bottom**: rejected — the user asked for the bottom; a menu hides the action behind a second click and adds JS for no benefit; the bottom placement with border separation reads naturally as 'danger zone'.", "**Also move the Archive button on the LIST page rows**: rejected — the list has no archive button today (only detail does); inventing one would add risk, not reduce it."]
## Consequences

Bought: new contacts save their postal code on the FIRST save — no edit roundtrip; the archive action sits away from daily actions with an inline explanation of what archiving does (and does not). Cost: none beyond the template move; the detail page grows one section. Negative guarantees: the bug affected ONLY contact create — location creates (create_contact_location) always had postal_code in their INSERT and are untouched; the backfill INSERTs (rent_clients, document backfill) intentionally omit postal_code (legacy tables carry no postal data); archive semantics unchanged (confirm dialog, archive=1/0 toggle, no delete).

