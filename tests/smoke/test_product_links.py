"""Product website_url / manufacturer_url (user request, 2026-09).

Two OPTIONAL link fields on the product itself:
- products.website_url  -- link to the product's own web page
- products.manufacturer_url -- link to the manufacturer's page

Contract (what this test module pins):
1. The pricing product form (add + edit) carries both inputs and round-trips
   the values through POST -> DB -> GET.
2. Empty input stores NULL (not '').
3. The fields appear on product-facing pages only: the pricing products list
   and the sale product view. They are OFFER-INVISIBLE by construction:
   offer add_item snapshots only name/description/photo_path from the product
   row, so neither the offer form's product dropdown data, nor the offer items
   table, nor the offer PDF ever contain the links.
"""

import pytest

from conftest import csrf_token_for, login_client

from qp_crm.main import app
from qp_crm.shared.db import get_db


# ---------- helpers ----------

def _csrf(client):
    return csrf_token_for(client)


def _product_row_by_name(name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE name = ? COLLATE NOCASE;", (name,))
    row = cur.fetchone()
    conn.close()
    return row


def _create_product(client, name, website_url="", manufacturer_url=""):
    return client.post(
        "/pricing/products/add",
        data={
            "_csrf_token": _csrf(client),
            "name": name,
            "category": "Alati",
            "brand": "TestBrand",
            "description": "opis",
            "item_type": "proizvod",
            "website_url": website_url,
            "manufacturer_url": manufacturer_url,
        },
        follow_redirects=True,
    )


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


# ---------- form round-trip ----------

def test_add_product_persists_both_links():
    client = login_client(app.test_client(), "pricing")
    resp = _create_product(
        client, "Link Roundtrip Product",
        website_url="https://example.com/drill",
        manufacturer_url="https://maker.example.com/drill",
    )
    assert resp.status_code == 200

    row = _product_row_by_name("Link Roundtrip Product")
    assert row["website_url"] == "https://example.com/drill"
    assert row["manufacturer_url"] == "https://maker.example.com/drill"


def test_add_product_empty_links_store_null():
    client = login_client(app.test_client(), "pricing")
    _create_product(client, "No Links Product")
    row = _product_row_by_name("No Links Product")
    assert row["website_url"] is None
    assert row["manufacturer_url"] is None


def test_edit_product_updates_and_clears_links():
    client = login_client(app.test_client(), "pricing")
    _create_product(
        client, "Editable Link Product",
        website_url="https://old.example.com",
        manufacturer_url="https://old.maker.com",
    )
    product = _product_row_by_name("Editable Link Product")

    resp = client.post(
        f"/pricing/products/{product['id']}/edit",
        data={
            "_csrf_token": _csrf(client),
            "name": "Editable Link Product",
            "category": "Alati",
            "brand": "TestBrand",
            "description": "opis",
            "item_type": "proizvod",
            "website_url": "https://new.example.com",
            "manufacturer_url": "",  # cleared
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    row = _product_row_by_name("Editable Link Product")
    assert row["website_url"] == "https://new.example.com"
    assert row["manufacturer_url"] is None


def test_product_form_renders_both_inputs_on_add_and_edit():
    client = login_client(app.test_client(), "pricing")
    html = client.get("/pricing/products/add").data.decode()
    assert 'name="website_url"' in html
    assert 'name="manufacturer_url"' in html

    _create_product(client, "Form Render Product",
                    website_url="https://render.example.com")
    product = _product_row_by_name("Form Render Product")
    html = client.get(f"/pricing/products/{product['id']}/edit").data.decode()
    assert 'name="website_url"' in html
    assert 'name="manufacturer_url"' in html
    assert "https://render.example.com" in html


# ---------- offer invisibility ----------

def test_links_never_appear_in_offer_form_items_or_snapshot():
    """The whole point of the feature: product links exist ONLY on the
    product. Neither the offer form (product dropdown data-attributes), nor
    the offer items table, nor the item snapshot ever carries them."""
    pricing = login_client(app.test_client(), "pricing")
    offer = login_client(app.test_client(), "offer")

    _create_product(
        pricing, "Offer Invisibility Product",
        website_url="https://secret-site.example.com/prod",
        manufacturer_url="https://secret-maker.example.com/prod",
    )
    product = _product_row_by_name("Offer Invisibility Product")
    pid = product[0]

    # real offer through the real route
    resp = offer.post(
        "/offer/offers/new",
        data={
            "_csrf_token": _csrf(offer),
            "offer_number": "LINK-VIS-001",
            "date": "2026-09-18",
            "client_name": "Link Vis Customer",
            "country": "Srbija",
            "currency": "EUR",
            "vat_percent": "20",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM offers WHERE offer_number = 'LINK-VIS-001';")
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

    # 1. offer form HTML must not carry the links
    form_html = offer.get(f"/offer/offers/{offer_id}/edit").data.decode()
    assert "secret-site.example.com" not in form_html
    assert "secret-maker.example.com" not in form_html

    # 2. item snapshot must not carry the links (name/description/photo only)
    cur.execute(
        "SELECT item_name, item_description FROM offer_items WHERE offer_id = ?;",
        (offer_id,),
    )
    item = cur.fetchone()
    conn.close()
    assert item[0] == "Offer Invisibility Product"
    assert "secret-site.example.com" not in (item[1] or "")
    assert "secret-maker.example.com" not in (item[1] or "")


# ---------- product-facing visibility ----------

def test_links_visible_on_products_list_and_sale_view():
    pricing = login_client(app.test_client(), "pricing")
    admin = login_client(app.test_client(), "admin")

    _create_product(
        pricing, "Visible Link Product",
        website_url="https://visible.example.com",
        manufacturer_url="https://visible-maker.example.com",
    )

    list_html = pricing.get("/pricing/products").data.decode()
    assert "https://visible.example.com" in list_html
    assert "https://visible-maker.example.com" in list_html

    product = _product_row_by_name("Visible Link Product")
    sale_html = admin.get(f"/sale/product/{product['id']}").data.decode()
    assert "https://visible.example.com" in sale_html
    assert "https://visible-maker.example.com" in sale_html
