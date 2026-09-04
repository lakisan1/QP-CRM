"""Regression for the phase-2 bug-fix stage (board card "BUG - offer
discount storage: NULL (new_offer) vs 0.0 (edit_offer) for zero
percentages + asymmetric recalc write-back").

The schema must carry ONE encoding of "no discount": 0.0. Whatever wrote
NULL historically made DB state depend on which form last touched the row.
These tests pin the route-level write paths and the recalc service's
tolerance for legacy NULL rows.
"""

import sqlite3


def _offer_row(conn_factory, offer_id):
    with conn_factory() as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT discount_percent, special_discount_percent, "
            "third_discount_percent, vat_percent, "
            "total_net, total_gross FROM offers WHERE id = ?;",
            (offer_id,),
        ).fetchone()


def _offer_id_from_redirect(response):
    # new_offer redirects to /offer/offers/<id>/edit
    loc = response.headers.get("Location", "").rstrip("/")
    return int(loc.rsplit("/", 2)[-2])


def test_new_offer_with_zero_discounts_stores_floats(
        temp_db, conn_factory, offer_client):
    """POST /offer/offers/new with all discount fields empty must store
    0.0 (never NULL) for the four percentage columns."""
    form = {
        "action": "save",
        "offer_number": "P2-NULL-TEST-1",
        "date": "2026-01-15",
        "client_name": "Null Check d.o.o.",
        "discount_percent": "",
        "special_discount_percent": "",
        "third_discount_percent": "",
        "vat_percent": "0",
    }
    response = offer_client.post("/offer/offers/new", data=form)
    # new_offer redirects to the edit page on success
    assert response.status_code == 302, response.data[:200]

    row = _offer_row(conn_factory, _offer_id_from_redirect(response))
    assert row["discount_percent"] == 0.0
    assert row["special_discount_percent"] == 0.0
    assert row["third_discount_percent"] == 0.0
    assert row["vat_percent"] == 0.0


def test_new_offer_empty_vat_uses_20_percent_default(
        temp_db, conn_factory, offer_client):
    """Empty vat_percent means 'use the 20% default' on BOTH write paths --
    pinned so the normalization cannot silently change the default."""
    form = {
        "action": "save",
        "offer_number": "P2-NULL-TEST-4",
        "date": "2026-01-15",
        "client_name": "Vat Default d.o.o.",
        "discount_percent": "",
        "special_discount_percent": "",
        "third_discount_percent": "",
        "vat_percent": "",
    }
    response = offer_client.post("/offer/offers/new", data=form)
    assert response.status_code == 302, response.data[:200]

    row = _offer_row(conn_factory, _offer_id_from_redirect(response))
    assert row["vat_percent"] == 0.2  # 20% default, stored as a float


def test_edit_offer_with_zero_discounts_stores_floats(
        temp_db, conn_factory, offer_client):
    """edit_offer is the reference behavior (0.0) -- pinned so the two
    write paths cannot drift apart again."""
    # Seed an offer directly, then re-save its header through edit_offer.
    with conn_factory() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO offers (offer_number, date, client_name,
               discount_percent, special_discount_percent, third_discount_percent,
               vat_percent, total_net, total_discount, total_net_after_discount,
               total_special_discount, total_net_after_special_discount,
               total_third_discount, total_net_after_third_discount,
               total_vat, total_gross, is_template)
               VALUES ('P2-NULL-TEST-2', '2026-01-15', 'Edit Check d.o.o.',
                       0.0, 0.0, 0.0, 0.0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0);"""
        )
        offer_id = cur.lastrowid
        conn.commit()

    response = offer_client.post(f"/offer/offers/{offer_id}/edit", data={
        "action": "update_header",
        "offer_number": "P2-NULL-TEST-2",
        "date": "2026-01-15",
        "client_name": "Edit Check d.o.o.",
        "discount_percent": "",
        "special_discount_percent": "",
        "third_discount_percent": "",
        "vat_percent": "0",
    })
    assert response.status_code == 302, response.data[:200]

    row = _offer_row(conn_factory, offer_id)
    assert row["discount_percent"] == 0.0
    assert row["special_discount_percent"] == 0.0
    assert row["third_discount_percent"] == 0.0
    assert row["vat_percent"] == 0.0


def test_recalc_normalizes_legacy_null_rows(
        temp_db, conn_factory, offer_client):
    """Legacy rows that already carry NULLs must read as zero AND be
    normalized on write-back by recalc_totals (single encoding going
    forward)."""
    with conn_factory() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO offers (offer_number, date, client_name,
               discount_percent, special_discount_percent, third_discount_percent,
               vat_percent, is_template)
               VALUES ('P2-NULL-TEST-3', '2026-01-15', 'Legacy Null d.o.o.',
                       NULL, NULL, NULL, NULL, 0);"""
        )
        offer_id = cur.lastrowid
        conn.commit()

    from qp_crm.services.offer_service import recalc_totals
    recalc_totals(offer_id)

    row = _offer_row(conn_factory, offer_id)
    # Derived totals were computed with NULL read as 0.
    assert row["total_net"] == 0.0
    assert row["total_gross"] == 0.0
    # The four input columns are normalized to the 0.0 encoding.
    assert row["discount_percent"] == 0.0
    assert row["special_discount_percent"] == 0.0
    assert row["third_discount_percent"] == 0.0
    assert row["vat_percent"] == 0.0
