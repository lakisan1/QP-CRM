# Agent Note: offer-item-ordinals

Status: implemented

## Problem

User report 2026-11-04: "Kad se napravi duplikat ponude ili kad se dodaju novi artikli, BR. redni broj u ponudi se nekad pokvari." The offer item ordinal is `offer_items.line_order`, used BOTH as the ordering key and as the displayed "BR."/"Rb." value in the edit form and the offer view page (the PDFs show `loop.index`). It was append-only (`MAX(line_order)+1` on every add, no renumber on delete) and copied verbatim by `duplicate_offer`, so every add/delete cycle left holes and every duplicate inherited them: in the live DB 16 of 83 offers had non-contiguous ordinals (e.g. P-1061 `1,8,17,25`, P-1100 `1,2,9,16,17,18,25,26` and its copies P-1100-1/P-1100-2 with exactly the same gaps, P-1018 up to `50`). A stale drag-and-drop list could additionally write the same ordinal to two items, because `update_item_order` renumbered only the ids it received.

## Decision

Shipped in qp_crm/services/offer_service.py + offer/routes/offers.py + offer/app.py + the two item-table templates:

1. `renumber_offer_items(cur, offer_id)` assigns 1..n by the reader order `ORDER BY line_order, id` — the exact order the form, the view page and every PDF use, so the relative order never changes, only the gaps close.

2. Every mutation that can break the sequence now renumbers: `add_item` (the INSERT still uses MAX+1 as a temporary slot, then the sequence is closed), `delete_item` (closes the hole the deletion leaves), `duplicate_offer` (the copy is inserted with an explicit `enumerate(items, 1)` counter and the source SELECT is `ORDER BY line_order, id`, so a copy never inherits the source's holes or repeated ordinals), and `update_item_order` (the posted ids go first in posted order, then EVERY remaining item of the offer follows in its current order — a stale page that posts a partial list can no longer write colliding ordinals).

3. `normalize_offer_item_orders(cur)` — one-time, idempotent repair over all offers, invoked from `offer.init_db()` right after the schema migrations, so the canonical boot/restore sequence (main.py, wsgi.py, conftest, Admin -> Backup restore) closes the holes of existing documents. The guard query (MIN!=1 OR MAX!=COUNT OR DISTINCT!=COUNT) makes later boots a pure no-op; offers without items are never touched.

4. Display is positional: the edit form's `.row-index` and the offer view page's first column print `loop.index` instead of the stored `line_order`. The PDFs already used `loop.index`/`Rb.`; nothing to change there.

5. Adjacent list-logic fix found while auditing: the Offers/Templates toggle was ignored whenever the "Artikal" (product) filter was active, so the Templates tab listed ordinary offers. The item-filter branch now applies `o.is_template = ?`.

Negative guarantees: no schema/column change and no new index; ordinals are NOT treated as stable identity (id remains the identity); items are never reordered by the repair (verified against a copy of the live DB: 16 offers repaired, zero row-order changes, no broken sequences left); a reorder request still refuses an empty id list (400) and rows not belonging to the offer are ignored; the drag-and-drop client is unchanged (it already re-renders the position after drop).
## Alternatives considered

**Renumber only on reorder (leave add/delete as MAX+1 and holes)** — rejected: the holes come from delete + MAX+1 cycles, which is exactly the duplicated-offer path the user hit; the number would still drift after every edit session.

**Display-only fix (print loop.index and leave line_order alone)** — rejected as the ONLY fix: it makes the UI look right but the stored order keeps growing (38, 39, 46...), duplicates inherit the mess, the reorder route can still write colliding ordinals, and any future reader that sorts by line_order (export, PDF custom template, an ORDER BY) still gets the broken values. The display change is kept AS WELL, as a defensive layer for rows the repair has not touched yet (e.g. a row inserted by an old client right before deploy).

**Boot-time repair inside shared/schema.py migrate_offer_tables** — rejected: schema.py is the DDL single source; normalizing data there mixes concerns and would run for callers that never touch offers. The repair lives in offer_service and is invoked from offer.init_db, which is the canonical boot/restore sequence (main.py, wsgi.py, conftest, admin restore) — so every path that can surface offers repairs them.

**Recompute line_order on read (SELECT ... ROW_NUMBER)** — rejected: SQLite version-dependent window support adds a query complexity tax on every list, leaves the stored data drifting, and the PDF/DB-template path passes plain item rows into a sandboxed Jinja context where a computed column is easy to miss.

**Skip the data repair and rely on the next edit of each offer** — rejected: 16 of 83 live offers would keep showing wrong "BR." until someone opens and saves them, and the user's complaint is exactly about seeing the wrong number on existing/doubled documents.
## Consequences

Bought: the "BR./Rb." column is 1..n on every offer — existing rows are repaired once at boot (16 of 83 in the live DB, verified on a copy: only the numbers change, no item row moved), duplicates start clean, add/delete/reorder cannot leave holes or duplicates again. Cost: offer.init_db now runs one grouped query over offer_items on every boot/restore (a no-op scan, ~230 rows today); the repair silently rewrites line_order values, which is safe only because the ordering key is (line_order, id) everywhere — any future code that treats an item's ordinal as stable identity would be wrong. The reorder endpoint now tolerates unknown/duplicate ids instead of blindly writing 1..k, so a stale client cannot corrupt the sequence but also cannot reorder rows it did not render (they go last). The reorder and add/delete paths still run one UPDATE per item inside the same transaction — fine at offer size (tens of rows), not meant for thousands. Deploy: templates + service are baked into the GHCR image, so a main push (CI) + ./deploy.sh is required; version bumped to 1.1.3 so Admin -> About proves the new image is running. No schema change, no backup risk: rollback returns to 1.1.2 with the repaired numbers intact (the repair is one-way only in the harmless direction — it never changes item order).

