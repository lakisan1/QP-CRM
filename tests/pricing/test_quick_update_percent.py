"""Quick Update: percentage adjustment of the purchase price.

User request (2026-11-06): next to the manual purchase price field a percent
can be entered (+7 / -7), which recalculates the purchase price from the
CURRENTLY stored one. The server applies the percent itself — the page JS only
previews it — so the saved result never depends on the browser. While a valid
percent is present the absolute base_price field is ignored; an unparsable
percent falls back to the absolute field instead of rejecting the row. A
-100 % (or stronger) reduction clamps the purchase price to 0.

All rows created here use the ZZQU prefix and are deleted again, so the
shared session temp DB catalogue is never polluted.
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


def _new_product_with_price(name_suffix, base_price):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO products (name, brand, category, item_type) "
            "VALUES (?, 'ZZTEST', 'ZZTEST', 'proizvod');",
            (f"ZZQU {name_suffix}",),
        )
        product_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO prices (product_id, date, base_price, extras,
                                import_percent, margin_percent,
                                warranty_percent, service_percent,
                                domestic_transport, instalation, traning, other)
            VALUES (?, '2026-01-01', ?, 0, 0, 0.4, 0, 0, 0, 0, 0, 0);
            """,
            (product_id, base_price),
        )
        conn.commit()
        return product_id
    finally:
        conn.close()


def _drop(product_id):
    conn = get_db()
    try:
        conn.execute("DELETE FROM prices WHERE product_id = ?;", (product_id,))
        conn.execute("DELETE FROM products WHERE id = ?;", (product_id,))
        conn.commit()
    finally:
        conn.close()


def _latest_price(product_id):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM prices WHERE product_id = ? ORDER BY id DESC LIMIT 1;",
            (product_id,),
        ).fetchone()
    finally:
        conn.close()


def _save(client, product_id, **fields):
    data = {
        "_csrf_token": csrf_token_for(client),
        "base_price": "999999",   # deliberately wrong: a percent must win
        "extras": "0",
    }
    data.update(fields)
    return client.post(f"/pricing/products/{product_id}/quick_update_save", data=data)


@pytest.fixture(scope="module")
def client():
    return login_client(app.test_client(), "pricing")


def test_quick_update_page_has_the_percent_input(client):
    # The temp DB catalogue may be empty — seed one row so the row markup
    # (and with it the percent input) renders.
    product_id = _new_product_with_price("ui", 1000.0)
    try:
        html = client.get("/pricing/products/quick_update").data.decode()
        assert 'name="base_price_percent"' in html
        assert 'placeholder="&plusmn; %"' in html
        # Visual follow-up (2026-11-06): no side label, field spans the cell.
        assert '% change' not in html
        i = html.find('name="base_price_percent"')
        assert 'width: 100%' in html[i:i + 400]
    finally:
        _drop(product_id)


def test_positive_percent_increases_the_purchase_price(client):
    product_id = _new_product_with_price("plus7", 1000.0)
    try:
        resp = _save(client, product_id, base_price_percent="7")
        assert resp.status_code == 302
        assert _latest_price(product_id)["base_price"] == pytest.approx(1070.0)
    finally:
        _drop(product_id)


def test_negative_percent_decreases_the_purchase_price(client):
    product_id = _new_product_with_price("minus7", 1000.0)
    try:
        resp = _save(client, product_id, base_price_percent="-7")
        assert resp.status_code == 302
        assert _latest_price(product_id)["base_price"] == pytest.approx(930.0)
    finally:
        _drop(product_id)


def test_percent_is_applied_to_the_stored_not_the_posted_base(client):
    """The absolute field is ignored while a percent is present — the base
    is recomputed from the stored purchase price (1000), not from 999999."""
    product_id = _new_product_with_price("stored", 1000.0)
    try:
        _save(client, product_id, base_price="999999", base_price_percent="10")
        assert _latest_price(product_id)["base_price"] == pytest.approx(1100.0)
    finally:
        _drop(product_id)


def test_without_percent_the_absolute_field_still_wins(client):
    product_id = _new_product_with_price("manual", 1000.0)
    try:
        _save(client, product_id, base_price="555")
        assert _latest_price(product_id)["base_price"] == pytest.approx(555.0)
    finally:
        _drop(product_id)


def test_unparsable_percent_falls_back_to_the_absolute_field(client):
    product_id = _new_product_with_price("badpct", 1000.0)
    try:
        _save(client, product_id, base_price="800", base_price_percent="abc")
        assert _latest_price(product_id)["base_price"] == pytest.approx(800.0)
    finally:
        _drop(product_id)


def test_percent_below_minus_100_clamps_to_zero(client):
    product_id = _new_product_with_price("clamp", 1000.0)
    try:
        _save(client, product_id, base_price_percent="-150")
        assert _latest_price(product_id)["base_price"] == pytest.approx(0.0)
    finally:
        _drop(product_id)
