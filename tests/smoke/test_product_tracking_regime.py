"""Product tracking regime — opt-in stock tracking (P5-T5).

The P5-T1 schema added products.tracking_regime / min_stock / unit_base /
pack_size but nothing in the pricing UI read or wrote them. This pins the
UI contract on top of that schema:

1. The pricing product form (add + edit) carries a tracking_regime select
   (untracked / qty / serialized) plus the qty-only min_stock / unit_base /
   pack_size inputs; the route whitelists and persists all four.
2. An empty or garbage regime falls back to 'untracked' -- never a 500,
   never an invalid row (the closed set lives in shared.schema).
3. Empty min_stock / pack_size become NULL, not 0 (the column is nullable
   and 0 is a real reorder point).
4. A product created without any tracking field stays 'untracked', exactly
   like the 254 legacy catalog rows (tracking is deliberately opt-in).
5. The products list shows a badge for tracked rows and an item_type-style
   'tracking_regime' filter.

These tests hit the real routes through the throwaway DB (conftest temp_db)
and read the row back with raw SQL, so they cover form -> route -> DB
round-trips, not just HTTP status codes.
"""

import pytest

from conftest import csrf_token_for, login_client

from qp_crm.main import app
from qp_crm.shared.db import get_db


def _csrf(client):
    return csrf_token_for(client)


def _product_row_by_name(name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE name = ? COLLATE NOCASE;", (name,))
    row = cur.fetchone()
    conn.close()
    return row


def _add_data(name, **extra):
    data = {
        "name": name,
        "category": "Alati",
        "brand": "TestBrand",
        "description": "opis",
        "item_type": "proizvod",
    }
    data.update(extra)
    return data


def _create_product(client, name, **extra):
    data = _add_data(name, **extra)
    data["_csrf_token"] = _csrf(client)
    return client.post("/pricing/products/add", data=data, follow_redirects=True)


def _edit_product(client, product_id, name, **extra):
    data = _add_data(name, **extra)
    data["_csrf_token"] = _csrf(client)
    return client.post(
        f"/pricing/products/{product_id}/edit", data=data, follow_redirects=True
    )


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


# ---------- add: qty round-trip ----------

def test_add_product_persists_qty_tracking():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(
        client, "Tracking Qty Product",
        tracking_regime="qty", min_stock="5", unit_base="kom", pack_size="10",
    )
    assert resp.status_code == 200
    row = _product_row_by_name("Tracking Qty Product")
    assert row["tracking_regime"] == "qty"
    assert row["min_stock"] == 5.0
    assert row["unit_base"] == "kom"
    assert row["pack_size"] == 10.0


def test_add_product_persists_serialized_regime():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Tracking Serialized Product",
                           tracking_regime="serialized")
    assert resp.status_code == 200
    assert _product_row_by_name("Tracking Serialized Product")["tracking_regime"] == "serialized"


def test_serbian_decimal_comma_accepted():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Tracking Comma Product",
                           tracking_regime="qty", min_stock="1,5")
    assert resp.status_code == 200
    assert _product_row_by_name("Tracking Comma Product")["min_stock"] == 1.5


# ---------- add: defaults + garbage fallback ----------

def test_product_without_tracking_fields_stays_untracked():
    """The 254-row default behaviour: no tracking field -> column default."""
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Tracking Untouched Product")
    assert resp.status_code == 200
    row = _product_row_by_name("Tracking Untouched Product")
    assert row["tracking_regime"] == "untracked"
    assert row["min_stock"] is None
    assert row["unit_base"] is None
    assert row["pack_size"] is None


def test_garbage_regime_falls_back_to_untracked_without_500():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Tracking Garbage Product",
                           tracking_regime="teleportation")
    assert resp.status_code == 200
    assert _product_row_by_name("Tracking Garbage Product")["tracking_regime"] == "untracked"


def test_empty_regime_falls_back_to_untracked_without_500():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Tracking Empty Regime Product",
                           tracking_regime="")
    assert resp.status_code == 200
    assert _product_row_by_name("Tracking Empty Regime Product")["tracking_regime"] == "untracked"


def test_empty_min_stock_and_pack_size_become_null_not_zero():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Tracking Empty Numbers Product",
                           tracking_regime="qty", min_stock="", pack_size="",
                           unit_base="")
    assert resp.status_code == 200
    row = _product_row_by_name("Tracking Empty Numbers Product")
    assert row["tracking_regime"] == "qty"
    assert row["min_stock"] is None
    assert row["pack_size"] is None
    assert row["unit_base"] is None


def test_garbage_numbers_do_not_500():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Tracking Garbage Numbers Product",
                           tracking_regime="qty", min_stock="abc", pack_size="x,y")
    assert resp.status_code == 200
    row = _product_row_by_name("Tracking Garbage Numbers Product")
    assert row["min_stock"] is None
    assert row["pack_size"] is None


# ---------- edit ----------

def test_edit_product_updates_regime_and_qty_fields():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "Tracking Editable Product")
    product = _product_row_by_name("Tracking Editable Product")
    assert product["tracking_regime"] == "untracked"

    resp = _edit_product(
        client, product["id"], "Tracking Editable Product",
        tracking_regime="qty", min_stock="3", unit_base="litar", pack_size="6",
    )
    assert resp.status_code == 200
    row = _product_row_by_name("Tracking Editable Product")
    assert row["tracking_regime"] == "qty"
    assert row["min_stock"] == 3.0
    assert row["unit_base"] == "litar"
    assert row["pack_size"] == 6.0

    # and back off again: untracked is reachable and clears the numbers
    resp = _edit_product(
        client, product["id"], "Tracking Editable Product",
        tracking_regime="untracked", min_stock="", pack_size="", unit_base="",
    )
    assert resp.status_code == 200
    row = _product_row_by_name("Tracking Editable Product")
    assert row["tracking_regime"] == "untracked"
    assert row["min_stock"] is None
    assert row["pack_size"] is None


def test_edit_product_garbage_regime_falls_back_to_untracked():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "Tracking Edit Garbage Product",
                    tracking_regime="serialized")
    product = _product_row_by_name("Tracking Edit Garbage Product")

    resp = _edit_product(client, product["id"], "Tracking Edit Garbage Product",
                         tracking_regime="bogus")
    assert resp.status_code == 200
    assert _product_row_by_name("Tracking Edit Garbage Product")["tracking_regime"] == "untracked"


# ---------- form rendering ----------

def test_form_renders_tracking_select_and_qty_inputs():
    client = login_client(app.test_client(), "pricing")
    html = client.get("/pricing/products/add").data.decode()
    assert 'name="tracking_regime"' in html
    assert 'name="min_stock"' in html
    assert 'name="unit_base"' in html
    assert 'name="pack_size"' in html
    assert 'value="untracked"' in html
    assert 'value="qty"' in html
    assert 'value="serialized"' in html
    assert "Ne prati" in html
    assert "Količinski" in html
    assert "Serijski" in html
    assert "tracking-qty-fields" in html


def test_edit_form_preselects_stored_regime():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "Tracking Preselect Product",
                    tracking_regime="qty", min_stock="7", unit_base="metar")
    product = _product_row_by_name("Tracking Preselect Product")
    html = client.get(f"/pricing/products/{product['id']}/edit").data.decode()
    assert html.count('<option value="qty" selected') == 1
    assert 'value="7' in html
    assert 'value="metar"' in html


# ---------- products list: filter + badge ----------

def test_products_list_filter_and_badge():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "Tracked List Product",
                    tracking_regime="qty", min_stock="1", unit_base="kom")
    _create_product(client, "Untracked List Product")

    html = client.get(
        "/pricing/products",
        query_string={"tracking_regime": "qty", "search": "List Product"},
    ).data.decode()
    assert "Tracked List Product" in html
    assert "Untracked List Product" not in html
    assert ">Količinski<" in html  # badge on the qty row

    html = client.get(
        "/pricing/products",
        query_string={"tracking_regime": "untracked", "search": "List Product"},
    ).data.decode()
    assert "Untracked List Product" in html
    assert "Tracked List Product" not in html


def test_products_list_serialized_badge():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "Serialized List Product", tracking_regime="serialized")
    html = client.get(
        "/pricing/products", query_string={"search": "Serialized List Product"}
    ).data.decode()
    assert "Serialized List Product" in html
    assert ">Serijski<" in html


def test_products_list_filter_renders_regime_dropdown():
    client = login_client(app.test_client(), "pricing")
    html = client.get("/pricing/products").data.decode()
    assert 'name="tracking_regime"' in html
    assert ">Količinski<" in html
    assert ">Serijski<" in html
    assert ">Ne prati<" in html
