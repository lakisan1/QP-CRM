# Agent Note: directory-country-filter

Status: implemented

## Problem

User request following the country-column and country-dropdown work: add a country filter to the directory list page so the 2156-contact list can be narrowed to one country.

## Decision

The directory list has a Država dropdown filter (contacts/list.html) fed from qp_crm/shared/countries.get_country_list() — the same 205-entry list the entry dropdowns use, exact match on contacts.country (c.country = ?, ?-bound). contact_service.list_contacts gained a country=None param; the clause joins the shared WHERE path, so the pagination COUNT query and the row query filter identically. The route reads ?country=, passes it to the service, re-selects it in the dropdown, and threads it through both pagination links and the out-of-range redirect (contacts/list.html links now carry country=country). Suite 356 passed.
## Alternatives considered

["**Filter by country of any LOCATION (JOIN contact_locations) instead of the contact's main country**: rejected — the list column shows contacts.country; a location-country filter would return contacts whose MAIN address shows a different country than the filter, which reads as a bug; if site-level search is ever needed it belongs in the detail page's locations table, not the party list.", "**Free-text country search input (LIKE) instead of a dropdown**: rejected — the dropdown migration just removed typo countries; a LIKE input would match fragments and resurface inconsistent values; the dropdown's exact match is also index-friendly.", "**Multi-select country filter**: rejected — single-select matches every other filter on this page (Vrsta, Uloga) and the common query is 'show me all our Serbian clients'; multi-select adds UI complexity with no demonstrated need.", "**Persist country filter in session like the offer list's filters**: rejected — offer filters persist because that list is a working queue; the directory's filters are deliberately stateless (GET params), so shared/bookmarked links behave identically for all users."]
## Consequences

Bought: 'show me all clients in Srbija / Hrvatska' is now one dropdown click combined with search/role/kind and works across pages; the filter rides every pagination link and the out-of-range redirect, so paging through a filtered set is stable. Cost: one more GET param threading through the list route and template (search, kind, role, country, archived, page); the COUNT query shares the country clause so filtered counts stay exact. Negative guarantees: the filter matches contacts.country EXACTLY (values not in the shared list — legacy typo rows — are invisible to the dropdown and can only be found via the free-text search box); pickers are untouched (directory_choices has no country param — the offer/rent party pickers deliberately keep showing all parties); no session persistence (stateless GET filters, bookmark-safe).

