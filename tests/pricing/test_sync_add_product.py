"""Product Sync: 'Add to CRM' saves and opens the new product in edit.

User request (2026-11-06): after clicking «Dodaj u CRM» in the sync modal,
the Save button must create the product AND take the user straight to that
product's edit form. The API returns `edit_url` (built with url_for, so the
JS never hard-codes the route) and the page JS navigates to it.

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


def test_add_to_crm_returns_edit_url_and_opens_edit_form(client):
    name = "ZZSYNC AddToCrm 1"
    _cleanup(name)
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO site_products (id, name, url) VALUES (?, ?, ?);",
        (SITE_ID, "Sajt proizvod", "https://example.com/p"),
    )
    conn.commit()
    conn.close()
    try:
        resp = client.post("/api/v1/sync/add_product", json={
            "site_id": SITE_ID,
            "name": name,
            "description": "Opis sa sajta",
            "brand": "",
            "category": "",
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
            "SELECT site_product_id FROM products WHERE id = ?;", (product_id,)
        ).fetchone()
        conn.close()
        assert row["site_product_id"] == SITE_ID
    finally:
        _cleanup(name)


def test_product_sync_js_redirects_after_add(client):
    """The modal's success handler navigates to edit_url instead of just
    reloading the comparison table."""
    html = client.get("/pricing/products/product_sync").data.decode()
    assert "edit_url" in html
    assert "window.location.href = target" in html
