# Agent Note: offer-drag-renumber-nested-rows

Status: implemented

## Problem

User report 2026-11-04 (after the 1.1.3 ordinal fix): "sad radi ali ako zamenim mesta uredjajima pokvari se do refresha stranice" — the "BR." numbers are wrong right after a drag-and-drop reorder and only a page refresh fixes them. Root cause: an item description is rendered as markdown (qp_crm/shared/web.py render_markdown, extensions `extra` + `nl2br`), and the catalog descriptions contain spec tables ("| Parametar | Specifikacija |"), so a real `<table><tr>` sits INSIDE the item row's description cell. The Sortable onEnd handler used `itemsBody.querySelectorAll('tr')`, counted those nested rows when writing `.row-index = index + 1`, and also pushed `undefined` ids into the reorder payload. The server then renumbered the real items correctly, so a refresh (server `loop.index`) showed 1..n again — exactly "broken until refresh".

## Decision

The offer edit page's Sortable handler now renumbers and collects ids from `itemsBody.querySelectorAll('tr[data-id]')` instead of `querySelectorAll('tr')`. Item rows are the only elements carrying `data-id`; the rows produced by markdown tables inside an item description (the `md` filter = python-markdown with the `extra` extension, so `| Parametar | Specifikacija |` becomes a real `<table><tr>` inside the description cell) are no longer counted. The handler therefore writes 1..n to `.row-index` cells of the actual items only, and posts only real ids to /offers/<id>/reorder.

Negative guarantees: the server-side reorder logic is unchanged and still renumbers ALL items in posted-first order (stale-page safe); nested description rows are never draggable (the `.drag-handle` exists only in item rows) and are never sent; the PDF/view ordinals were already positional (`loop.index`) and stay untouched; no schema or data change — the stored line_order was already correct after the 1.1.3 repair, this was purely the client-side display and id list.

Pinned by tests/characterization/test_offer_item_ordinals.py::test_drag_renumber_ignores_nested_description_table_rows — it renders an offer whose item description contains a two-row markdown table and asserts (a) `#items-body` really contains 5 `<tr>` for 3 items (the hazard), (b) the page contains `querySelectorAll('tr[data-id]')` and no longer contains `querySelectorAll('tr').forEach`.
## Alternatives considered

**`:scope > tr` selector** — equally correct (Sortable only moves direct children), rejected only because it is newer syntax and the `data-id` filter states the real invariant: only item rows carry an identity, everything else inside a description is presentation.

**Strip/normalize HTML in descriptions (disallow markdown tables)** — rejected: descriptions legitimately embed spec tables (the catalog-standard format relies on them, and the PDF/print output shows them); killing tables in the edit list would change the product-text format and the PDF output.

**Freeze the BR. column during a drag and only refresh it from the server** (re-fetch the page or the items after the reorder POST) — rejected: a full reload after every drop is the jank the drag feature exists to avoid, and a partial re-render would still need the same "which rows are items" selector.

**Debounce/re-render numbers server-side via the reorder response** — rejected as over-engineering for a 2-number fix: the reorder response already confirms success, and the client-side renumber is now correct because it only walks item rows.
## Consequences

Bought: dragging an item re-numbers the "BR." column correctly with no page refresh, and the reorder POST carries only real item ids (the nested description rows used to push `undefined` entries into the request). Cost: the invariant is now documented in the template — every item row must keep `data-id`; anything inserted into `#items-body` that is not an item row is silently ignored by the drag handler (which is the desired behavior, but a future "add row" feature that forgets data-id would not be draggable/renumbered). No server change, no data repair: the stored ordinals were already correct; the client display was the only thing off. Deploy: the template is baked into the GHCR image, so a main push + `./deploy.sh` is required; version bumped to 1.1.4 (built on top of the 1.1.3 ordinal repair, which stays as is).

