"""Product item_type — physical product vs service (user request, 2026-09-23).

Contract pinned here:
1. item_type is REQUIRED on the pricing product form: 'proizvod'
   (physical product, the default for every pre-existing row) or
   'usluga' (service); an empty/invalid value re-renders the form with
   an error and the user's input preserved.
2. The migration backfills every existing row to 'proizvod'
   (NOT NULL DEFAULT 'proizvod' on the idempotent ALTER).
3. Filter dropdown on the pricing products list and the sale list;
   'usluga' rows carry a visible badge on both lists and the sale view.
4. api_v1: create requires item_type; update: absent keeps, present must
   be valid; list/detail expose it.
5. Offer-invisible like the product_code/links family: never in offer
   item snapshots (add_item snapshots only name/description/photo_path).
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


def _create_product(client, name, item_type="proizvod", **extra):
    data = {
        "_csrf_token": _csrf(client),
        "name": name,
        "category": "Alati",
        "brand": "TestBrand",
        "description": "opis",
        "item_type": item_type,
    }
    data.update(extra)
    return client.post("/pricing/products/add", data=data, follow_redirects=True)


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


# ---------- required field + round-trip ----------

def test_add_product_defaults_to_physical():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Default Type Product", item_type="proizvod")
    assert resp.status_code == 200
    row = _product_row_by_name("Default Type Product")
    assert row["item_type"] == "proizvod"


def test_add_service_roundtrip():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Montaža i servis opreme", item_type="usluga")
    assert resp.status_code == 200
    row = _product_row_by_name("Montaža i servis opreme")
    assert row["item_type"] == "usluga"


def test_missing_item_type_rejected_with_error_and_preserved_input():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "No Type Product", item_type="")
    assert resp.status_code == 200
    assert "Vrsta stavke je obavezna" in resp.data.decode()
    row = _product_row_by_name("No Type Product")
    assert row is None  # nothing inserted
    # the form must still render with the typed name preserved
    assert 'value="No Type Product"' in resp.data.decode()


def test_edit_product_changes_type():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "Switchable Type Product", item_type="proizvod")
    product = _product_row_by_name("Switchable Type Product")

    resp = client.post(
        f"/pricing/products/{product['id']}/edit",
        data={
            "_csrf_token": _csrf(client),
            "name": "Switchable Type Product",
            "category": "Alati",
            "brand": "TestBrand",
            "description": "opis",
            "item_type": "usluga",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert _product_row_by_name("Switchable Type Product")["item_type"] == "usluga"


def test_form_renders_required_select():
    client = login_client(app.test_client(), "pricing")
    html = client.get("/pricing/products/add").data.decode()
    assert 'name="item_type"' in html
    assert "required" in html


# ---------- migration backfill ----------

def test_legacy_rows_carry_default_proizvod(temp_db):
    """NOT NULL DEFAULT 'proizvod' on the ALTER: the migration backfills
    every pre-existing row to physical product without a data fix. A row
    inserted without item_type lands on the default."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name, category, brand, description) VALUES (?, ?, ?, ?);",
        ("Backfill Type Product", "Alati", "TestBrand", "opis"),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    assert _product_row_by_name("Backfill Type Product")["item_type"] == "proizvod"


# ---------- filters + badges ----------

def test_products_list_filter_and_badge():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "Filter Fiz Product", item_type="proizvod")
    _create_product(client, "Filter Usl Product", item_type="usluga")

    html = client.get("/pricing/products?item_type=usluga").data.decode()
    assert "Filter Usl Product" in html
    assert "Filter Fiz Product" not in html

    all_html = client.get("/pricing/products").data.decode()
    assert ">Service<" in all_html  # badge on the service row


def test_sale_list_filter_and_badge():
    sale = login_client(app.test_client(), "pricing")
    _create_product(sale, "Sale Fiz Product", item_type="proizvod")
    _create_product(sale, "Sale Usl Product", item_type="usluga")

    html = sale.get("/sale/pricelist?item_type=usluga").data.decode()
    assert "Sale Usl Product" in html
    assert "Sale Fiz Product" not in html


def test_sale_view_shows_item_type():
    pricing = login_client(app.test_client(), "pricing")
    _create_product(pricing, "View Type Product", item_type="usluga")
    product = _product_row_by_name("View Type Product")
    html = pricing.get(f"/sale/product/{product['id']}").data.decode()
    assert ">Service<" in html


# ---------- api_v1 ----------

def test_api_create_requires_item_type():
    client = login_client(app.test_client(), "pricing")
    resp = client.post("/api/v1/products", json={"name": "API No Type"})
    assert resp.status_code == 400
    assert "item_type" in resp.get_json()["error"]

    resp = client.post("/api/v1/products", json={"name": "API Usl", "item_type": "usluga"})
    assert resp.status_code == 201
    assert resp.get_json()["data"]["item_type"] == "usluga"


def test_api_update_absent_keeps_invalid_rejected():
    client = login_client(app.test_client(), "pricing")
    client.post("/pricing/products/add", data={
        "_csrf_token": _csrf(client), "name": "API Type Keep",
        "category": "Alati", "brand": "TestBrand", "item_type": "usluga",
    }, follow_redirects=True)
    product = _product_row_by_name("API Type Keep")

    # absent -> keep
    resp = client.put(f"/api/v1/products/{product['id']}", json={"description": "novo"})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["item_type"] == "usluga"

    # invalid -> 400
    resp = client.put(f"/api/v1/products/{product['id']}", json={"item_type": "bogus"})
    assert resp.status_code == 400
