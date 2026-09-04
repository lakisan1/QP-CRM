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

    cur.execute("""
        UPDATE offers
        SET total_net = ?, total_discount = ?, total_net_after_discount = ?,
            special_discount_percent = ?, total_special_discount = ?, total_net_after_special_discount = ?,
            third_discount_percent = ?, total_third_discount = ?, total_net_after_third_discount = ?,
            total_vat = ?, total_gross = ?
        WHERE id = ?;
    """, (
        total_net, total_discount, total_net_after_discount,
        special_discount_percent, total_special_discount, total_net_after_special_discount,
        third_discount_percent, total_third_discount, total_net_after_third_discount,
        total_vat, total_gross, offer_id
    ))
    conn.commit()
    conn.close()
