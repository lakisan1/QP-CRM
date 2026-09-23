"""Product product_code — optional external ID / catalogue code (user request).

Follows the website_url / manufacturer_url pattern exactly (schema 3d):
- products.product_code is a nullable free-text column, empty-as-NULL;
- the pricing product form (add + edit) carries the input and round-trips
  the value through POST -> DB -> GET;
- it shows on product-facing surfaces only (products list, sale view);
- it is OFFER-INVISIBLE by construction: add_item snapshots only
  name/description/photo_path, so no offer surface ever carries it;
- api_v1 list/detail expose it; create accepts it; update treats absent
  as keep and empty string as clear.
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


def _create_product(client, name, product_code=""):
    return client.post(
        "/pricing/products/add",
        data={
            "_csrf_token": _csrf(client),
            "name": name,
            "category": "Alati",
            "brand": "TestBrand",
            "description": "opis",
            "item_type": "proizvod",
            "product_code": product_code,
        },
        follow_redirects=True,
    )


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


# ---------- form round-trip ----------

def test_add_product_persists_code():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(client, "Code Roundtrip Product", product_code="DW-XR-2233")
    assert resp.status_code == 200
    row = _product_row_by_name("Code Roundtrip Product")
    assert row["product_code"] == "DW-XR-2233"


def test_add_product_empty_code_stores_null():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "No Code Product")
    row = _product_row_by_name("No Code Product")
    assert row["product_code"] is None


def test_edit_product_updates_and_clears_code():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "Editable Code Product", product_code="OLD-01")
    product = _product_row_by_name("Editable Code Product")

    resp = client.post(
        f"/pricing/products/{product['id']}/edit",
        data={
            "_csrf_token": _csrf(client),
            "name": "Editable Code Product",
            "category": "Alati",
            "brand": "TestBrand",
            "description": "opis",
            "item_type": "proizvod",
            "product_code": "",  # cleared
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    row = _product_row_by_name("Editable Code Product")
    assert row["product_code"] is None


def test_form_renders_input_on_add_and_edit():
    client = login_client(app.test_client(), "pricing")
    html = client.get("/pricing/products/add").data.decode()
    assert 'name="product_code"' in html

    _create_product(client, "Form Render Code Product", product_code="RENDER-77")
    product = _product_row_by_name("Form Render Code Product")
    html = client.get(f"/pricing/products/{product['id']}/edit").data.decode()
    assert 'name="product_code"' in html
    assert "RENDER-77" in html


# ---------- visible surfaces ----------

def test_code_shows_on_products_list():
    pricing = login_client(app.test_client(), "pricing")
    _create_product(pricing, "Visible Code Product", product_code="VIS-42")

    list_html = pricing.get("/pricing/products").data.decode()
    assert "VIS-42" in list_html


# ---------- offer invisibility ----------

def test_code_never_appears_in_offer_form_items_or_snapshot():
    pricing = login_client(app.test_client(), "pricing")
    offer = login_client(app.test_client(), "offer")

    _create_product(pricing, "Offer Invisibility Code Product", product_code="SECRET-CODE-9")
    product = _product_row_by_name("Offer Invisibility Code Product")
    pid = product[0]

    resp = offer.post(
        "/offer/offers/new",
        data={
            "_csrf_token": _csrf(offer),
            "offer_number": "CODE-VIS-001",
            "date": "2026-09-22",
            "client_name": "Code Vis Customer",
            "country": "Srbija",
            "currency": "EUR",
            "vat_percent": "20",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM offers WHERE offer_number = 'CODE-VIS-001';")
    offer_id = cur.fetchone()[0]

    resp = offer.post(
        f"/offer/offers/{offer_id}/edit",
        data={
            "_csrf_token": _csrf(offer),
            "action": "add_item",
            "product_id": str(pid),
            "item_name": "",
            "item_description": "",
            "quantity": "1",
            "unit_price": "100",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    form_html = offer.get(f"/offer/offers/{offer_id}/edit").data.decode()
    assert "SECRET-CODE-9" not in form_html

    cur.execute(
        "SELECT item_name, item_description FROM offer_items WHERE offer_id = ?;",
        (offer_id,),
    )
    item = cur.fetchone()
    assert item is not None
    assert "SECRET-CODE-9" not in (item["item_name"] or "")
    assert "SECRET-CODE-9" not in (item["item_description"] or "")
    conn.close()


# ---------- api_v1 (session identity: pricing grant, no Bearer needed) ----------

def test_api_list_and_detail_carry_code():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "API Code Product", product_code="API-1001")

    resp = client.get("/api/v1/products")
    assert resp.status_code == 200
    rows = [p for p in resp.get_json()["data"] if p["name"] == "API Code Product"]
    assert rows and rows[0]["product_code"] == "API-1001"

    pid = rows[0]["id"]
    resp = client.get(f"/api/v1/products/{pid}")
    assert resp.get_json()["data"]["product_code"] == "API-1001"


def test_api_update_absent_keeps_empty_clears():
    import json as _json

    client = login_client(app.test_client(), "pricing")
    _create_product(client, "API Update Code Product", product_code="KEEP-ME")
    product = _product_row_by_name("API Update Code Product")

    # absent -> keep
    resp = client.put(
        f"/api/v1/products/{product['id']}",
        data={"description": "novo"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["product_code"] == "KEEP-ME"

    # empty string -> clear
    resp = client.put(
        f"/api/v1/products/{product['id']}",
        data=_json.dumps({"product_code": ""}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.get_json()["data"]["product_code"] is None
