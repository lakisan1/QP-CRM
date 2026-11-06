"""Product Sync: 'Add to CRM' — required brand/category + open edit form.

User requests (2026-11-06):
* after clicking «Dodaj u CRM» in the sync modal, the Save button creates the
  product AND takes the user straight to that product's edit form (the API
  returns `edit_url` built with url_for, so the JS never hard-codes a route);
* brand and category are MANDATORY in that dialog — an unclassified product
  cannot be saved. The modal checks it client-side and the API enforces it
  server-side (a bypassed/blocked JS must not get around the rule).

Rows created here use a ZZSYNC prefix / fixed site id and are cleaned up so
the shared session temp DB catalogue is not polluted.
"""

import pytest

from conftest import login_client
from qp_crm.main import app
from qp_crm.shared.db import get_db

SITE_ID = 990001


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


@pytest.fixture(scope="module")
def client():
    return login_client(app.test_client(), "pricing")


def _cleanup(name):
    conn = get_db()
    row = conn.execute("SELECT id FROM products WHERE name = ?;", (name,)).fetchone()
    if row is not None:
        conn.execute("DELETE FROM prices WHERE product_id = ?;", (row["id"],))
        conn.execute("DELETE FROM products WHERE id = ?;", (row["id"],))
    conn.execute("DELETE FROM site_products WHERE id = ?;", (SITE_ID,))
    conn.commit()
    conn.close()


def _site_row():
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO site_products (id, name, url) VALUES (?, ?, ?);",
        (SITE_ID, "Sajt proizvod", "https://example.com/p"),
    )
    conn.commit()
    conn.close()


def _product_exists(name):
    conn = get_db()
    row = conn.execute("SELECT id FROM products WHERE name = ?;", (name,)).fetchone()
    conn.close()
    return row is not None


def test_add_to_crm_returns_edit_url_and_opens_edit_form(client):
    name = "ZZSYNC AddToCrm 1"
    _cleanup(name)
    _site_row()
    try:
        resp = client.post("/api/v1/sync/add_product", json={
            "site_id": SITE_ID,
            "name": name,
            "description": "Opis sa sajta",
            "brand": "ZZTEST BREND",
            "category": "ZZTEST KATEGORIJA",
            "image_url": "",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        product_id = data["data"]["product_id"]
        # the API tells the page WHERE to go — url_for, not a JS literal
        assert data["data"]["edit_url"] == f"/pricing/products/{product_id}/edit"
        # that target is a real, reachable edit page (the redirect works)
        assert client.get(data["data"]["edit_url"]).status_code == 200
        # and the product really is linked to the site product (1:1)
        conn = get_db()
        row = conn.execute(
            "SELECT site_product_id, brand, category FROM products WHERE id = ?;",
            (product_id,),
        ).fetchone()
        conn.close()
        assert row["site_product_id"] == SITE_ID
        assert row["brand"] == "ZZTEST BREND"
        assert row["category"] == "ZZTEST KATEGORIJA"
    finally:
        _cleanup(name)


def test_add_to_crm_rejects_missing_brand(client):
    name = "ZZSYNC NoBrand"
    _cleanup(name)
    _site_row()
    try:
        resp = client.post("/api/v1/sync/add_product", json={
            "site_id": SITE_ID,
            "name": name,
            "description": "",
            "brand": "",
            "category": "ZZTEST KATEGORIJA",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Brand is required."
        assert not _product_exists(name)
    finally:
        _cleanup(name)


def test_add_to_crm_rejects_missing_category(client):
    name = "ZZSYNC NoCat"
    _cleanup(name)
    _site_row()
    try:
        resp = client.post("/api/v1/sync/add_product", json={
            "site_id": SITE_ID,
            "name": name,
            "description": "",
            "brand": "ZZTEST BREND",
            "category": "",
        })
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "Category is required."
        assert not _product_exists(name)
    finally:
        _cleanup(name)


def test_product_sync_js_redirects_and_requires_brand_category(client):
    """The modal's success handler navigates to edit_url instead of just
    reloading the table, and the save handler refuses a blank brand/category
    before any request is made."""
    html = client.get("/pricing/products/product_sync").data.decode()
    assert "edit_url" in html
    assert "window.location.href = target" in html
    assert "Brend je obavezan" in html
    assert "Kategorija je obavezna" in html
    assert 'id="add-brand" required' in html
    assert 'id="add-cat" required' in html
