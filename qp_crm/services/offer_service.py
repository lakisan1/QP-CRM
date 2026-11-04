"""Offer services (Phase 2 stage 4).

recalc_totals moved verbatim from offer/app.py; offer/app.py imports it
back so route call sites and the existing test imports keep working.
"""

from qp_crm.shared.db import get_db


def recalc_totals(offer_id):
    """Recalculate totals for an offer based on its items and discount/VAT."""
    conn = get_db()
    cur = conn.cursor()

    # Load offer
    cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
    offer = cur.fetchone()
    if offer is None:
        conn.close()
        return

    discount_percent = offer["discount_percent"] or 0.0
    special_discount_percent = offer["special_discount_percent"] or 0.0
    third_discount_percent = offer["third_discount_percent"] or 0.0
    vat_percent = offer["vat_percent"] or 0.0

    # Sum line_net
    cur.execute("""
        SELECT COALESCE(SUM(line_net), 0) AS sum_net
        FROM offer_items
        WHERE offer_id = ?;
    """, (offer_id,))
    row = cur.fetchone()
    total_net = row["sum_net"] or 0.0

    total_discount = total_net * discount_percent
    total_net_after_discount = total_net - total_discount
    
    total_special_discount = total_net_after_discount * special_discount_percent
    total_net_after_special_discount = total_net_after_discount - total_special_discount
    
    total_third_discount = total_net_after_special_discount * third_discount_percent
    total_net_after_third_discount = total_net_after_special_discount - total_third_discount
    
    total_vat = total_net_after_third_discount * vat_percent
    total_gross = total_net_after_third_discount + total_vat

    # BUG fix (phase-2 bug-fix stage, card "offer discount storage: NULL
    # (new_offer) vs 0.0 (edit_offer) + asymmetric recalc write-back"):
    # the four input percentage columns are written back coerced to 0.0 so
    # the schema carries ONE encoding of "no discount" -- recalc used to
    # persist special/third coerced while leaving discount_percent /
    # vat_percent NULL on legacy rows.
    discount_percent = float(offer["discount_percent"] or 0.0)
    vat_percent = float(offer["vat_percent"] or 0.0)

    cur.execute("""
        UPDATE offers
        SET total_net = ?, total_discount = ?, total_net_after_discount = ?,
            discount_percent = ?, vat_percent = ?,
            special_discount_percent = ?, total_special_discount = ?, total_net_after_special_discount = ?,
            third_discount_percent = ?, total_third_discount = ?, total_net_after_third_discount = ?,
            total_vat = ?, total_gross = ?
        WHERE id = ?;
    """, (
        total_net, total_discount, total_net_after_discount,
        discount_percent, vat_percent,
        special_discount_percent, total_special_discount, total_net_after_special_discount,
        third_discount_percent, total_third_discount, total_net_after_third_discount,
        total_vat, total_gross, offer_id
    ))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Offer item ordinals (line_order) -- displayed as "BR." / "Rb."
#
# line_order is BOTH the ordering key and the user-visible ordinal: the
# edit form, the offer view page and the PDFs list items ORDER BY
# line_order, id. It used to be append-only (MAX+1 when adding an item) and
# copied verbatim when an offer was duplicated, so deleting/re-adding items
# left holes ("1, 8, 17, 25" -- 16 of 83 live offers had such values) and
# every duplicate inherited them. Renumbering by the CURRENT order
# (line_order, id) keeps the relative order exactly as every reader shows
# it, and only closes the gaps.
# ---------------------------------------------------------------------------

def renumber_offer_items(cur, offer_id):
    """Assign contiguous 1..n line_order values to one offer's items.

    Uses the reader order (line_order, id), so nothing moves -- it only
    removes holes and duplicates. Returns the number of items.
    """
    cur.execute(
        "SELECT id FROM offer_items WHERE offer_id = ? ORDER BY line_order, id;",
        (offer_id,))
    item_ids = [row[0] for row in cur.fetchall()]
    for position, item_id in enumerate(item_ids, start=1):
        cur.execute(
            "UPDATE offer_items SET line_order = ? WHERE id = ?;",
            (position, item_id))
    return len(item_ids)


def normalize_offer_item_orders(cur):
    """One-time, idempotent repair of every offer whose ordinals are broken.

    Called from offer.init_db (the boot/restore sequence), so existing
    documents show 1..n without anyone editing them. The guard query makes
    later boots a no-op. Returns the number of repaired offers.
    """
    cur.execute("""
        SELECT offer_id
        FROM offer_items
        GROUP BY offer_id
        HAVING COALESCE(MIN(line_order), 0) != 1
            OR COALESCE(MAX(line_order), 0) != COUNT(*)
            OR COUNT(DISTINCT line_order) != COUNT(*)
    """)
    repaired = 0
    for (offer_id,) in cur.fetchall():
        renumber_offer_items(cur, offer_id)
        repaired += 1
    return repaired
