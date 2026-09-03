"""P1-T3 characterization: offer.app.recalc_totals -- behavior AS IS.

recalc_totals(offer_id) reads the offer row + SUM(line_net) of its items and
writes totals back. Discount/vat percentages are stored as FRACTIONS in the
DB (the form divides user input by 100 at offer/app.py:524-526 and :642).

Captured from the unmodified app via tests/_capture.py and hand-checked
against offer/app.py:750-802. Pinned quirks:

* 'offer["x"] or 0.0' coerces NULL **and** stored 0.0 to 0.0 -- a NULL
  discount behaves like "no discount".
* The UPDATE writes special/third discount percentages back as coerced
  floats (NULL -> 0.0 persisted) but leaves discount_percent/vat_percent
  NULL -- asymmetric persistence.
* Item-level discount_percent is NOT re-derived: only SUM(line_net) counts
  (items store their already-discounted line_net, offer/app.py:956).
* The VAT product carries a float artifact (24 591.9375 * 0.2 ->
  4 918.387500000001, audit L11 floats-for-money) -- pinned exactly.
* Unknown offer id is a silent no-op (no exception, no write).
"""

from offer.app import recalc_totals


def _insert_offer(conn, number, discount, special, third, vat):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO offers (offer_number, date, client_name, currency, exchange_rate,
            discount_percent, special_discount_percent, third_discount_percent, vat_percent)
         VALUES (?, '2026-03-15', 'Characterization d.o.o.', 'RSD', 1.0, ?, ?, ?, ?);""",
        (number, discount, special, third, vat),
    )
    return cur.lastrowid


def _insert_item(conn, offer_id, name, line_net, item_discount=0.0, order=1):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO offer_items (offer_id, item_name, quantity, unit_price,
            discount_percent, line_net, line_order)
         VALUES (?, ?, 1, ?, ?, ?, ?);""",
        (offer_id, name, line_net, item_discount, line_net, order),
    )
    return cur.lastrowid


def _totals(conn, offer_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
    return dict(cur.fetchone())


def test_three_level_cascade_exact(temp_db, conn_factory):
    with conn_factory() as conn:
        oid = _insert_offer(conn, "P1T3-CASCADE", 0.10, 0.05, 0.025, 0.20)
        for order, net in ((1, 10000.0), (2, 19000.0), (3, 500.0)):
            _insert_item(conn, oid, f"Item {order}", net, order=order)

    recalc_totals(oid)

    with conn_factory() as conn:
        row = _totals(conn, oid)
    # Captured from the unmodified app -- exact float literals:
    assert row["total_net"] == 29500.0
    assert row["total_discount"] == 2950.0
    assert row["total_net_after_discount"] == 26550.0
    assert row["total_special_discount"] == 1327.5
    assert row["total_net_after_special_discount"] == 25222.5
    assert row["total_third_discount"] == 630.5625
    assert row["total_net_after_third_discount"] == 24591.9375
    # 24 591.9375 * 0.2 in IEEE double -> ...0001. Do NOT "fix" to 4918.3875.
    assert row["total_vat"] == 4918.387500000001
    assert row["total_gross"] == 29510.325


def test_null_discounts_behave_as_zero_and_are_partially_persisted(temp_db, conn_factory):
    with conn_factory() as conn:
        oid = _insert_offer(conn, "P1T3-NULLS", None, None, None, None)
        _insert_item(conn, oid, "Item", 100.0)

    recalc_totals(oid)

    with conn_factory() as conn:
        row = _totals(conn, oid)
    # readback after recalc: totals are all zero, gross == net
    assert row["total_net"] == 100.0
    assert row["total_discount"] == 0.0
    assert row["total_net_after_discount"] == 100.0
    assert row["total_vat"] == 0.0
    assert row["total_gross"] == 100.0
    # asymmetric write-back: special/third coerced to 0.0 and PERSISTED,
    # discount_percent / vat_percent stay NULL (offer/app.py:788-800)
    assert row["special_discount_percent"] == 0.0
    assert row["third_discount_percent"] == 0.0
    assert row["discount_percent"] is None
    assert row["vat_percent"] is None


def test_recalc_ignores_item_level_discount_column(temp_db, conn_factory):
    # Items carry their own discount_percent column, but recalc only sums
    # line_net (line_net was already discounted at insert time,
    # offer/app.py:956). Changing the item discount column afterwards does
    # not change any total.
    with conn_factory() as conn:
        oid = _insert_offer(conn, "P1T3-ITEMDISC", 0.0, 0.0, 0.0, 0.20)
        _insert_item(conn, oid, "Item", 95.0, item_discount=0.05)

    recalc_totals(oid)

    with conn_factory() as conn:
        row = _totals(conn, oid)
    assert row["total_net"] == 95.0
    assert row["total_gross"] == 114.0


def test_float_artifact_sum(temp_db, conn_factory):
    with conn_factory() as conn:
        oid = _insert_offer(conn, "P1T3-FLOAT", 0.0, 0.0, 0.0, 0.20)
        _insert_item(conn, oid, "A", 33.33, order=1)
        _insert_item(conn, oid, "B", 0.1, order=2)

    recalc_totals(oid)

    with conn_factory() as conn:
        row = _totals(conn, oid)
    assert row["total_net"] == 33.43
    assert row["total_vat"] == 6.686
    assert row["total_gross"] == 40.116


def test_unknown_offer_id_is_silent_noop(temp_db):
    # offer/app.py:758-760 -- close + return, no exception, no write
    assert recalc_totals(987654321) is None


def test_empty_offer_totals_zero(temp_db, conn_factory):
    with conn_factory() as conn:
        oid = _insert_offer(conn, "P1T3-EMPTY", 0.10, 0.05, 0.025, 0.20)

    recalc_totals(oid)

    with conn_factory() as conn:
        row = _totals(conn, oid)
    assert row["total_net"] == 0.0
    assert row["total_gross"] == 0.0
