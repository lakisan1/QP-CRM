"""R-T4/R-T5 + same-day follow-up (2026-09-24 user requests): the standalone
/rent/equipment page is gone; the contract form carries an inline
add-to-catalog form; the equipment PICKER is removed too (user: equipment
is typed directly into the contract now — the catalog form only saves
defaults for reuse); the Delete action moved from the contracts list into
the contract edit form; and the list's Edit button is gone (the contract
number is the link).

Pinned:

* POST /rent/contracts/equipment/save creates a rent_equipment row from
  the inline form and redirects back to return_to (no eq_id preselect —
  the picker no longer exists);
* the redirect target is validated (same-site absolute path only) — a
  hand-crafted return_to falls back to the contracts list;
* an empty name bounces back without inserting;
* /rent/equipment (GET and POST) redirects to the contracts list;
* the rent banner no longer links the equipment page;
* the edit form has NO equipment picker (no equipSelect, no options list)
  and no autofill fetch — section 4. Oprema is the free-text
  equipment_model textarea plus the add-to-catalog form;
* GET /rent/api/equipment/<id> is gone (404);
* the list table has no Actions column / Edit button; the contract
  number cell is the edit link;
* the edit form renders the Delete button + confirm modal; the list has
  neither.
"""

import sys

import pytest

sys.path.insert(0, "tests")

from conftest import csrf_token_for, login_client  # noqa: E402
from qp_crm.main import app  # noqa: E402
from qp_crm.shared.db import get_db  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _clean():
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("DELETE FROM rent_contract_documents;")
    conn.execute("DELETE FROM rent_contracts;")
    conn.execute("DELETE FROM rent_equipment;")
    conn.commit()
    yield
    conn.close()


def _client():
    return login_client(app.test_client(), "rent")


def _csrf(client):
    return {"_csrf_token": csrf_token_for(client)}


def test_inline_equipment_save_creates_row_and_redirects_back():
    client = _client()
    resp = client.post("/rent/contracts/equipment/save", data={
        "name": "Inline Test Masina",
        "price": "9999.5",
        "default_rent_months": "36",
        "default_guarantee_rate": "7",
        "default_downpayment_percent": "25",
        "return_to": "/rent/contracts/edit/1",
        **_csrf(client),
    })
    assert resp.status_code == 302
    # plain redirect back — the picker is gone, no ?eq_id= preselect
    assert resp.headers["Location"] == "/rent/contracts/edit/1"
    row = get_db().execute(
        "SELECT * FROM rent_equipment WHERE name='Inline Test Masina';"
    ).fetchone()
    assert row is not None
    assert row["price"] == 9999.5
    assert row["default_rent_months"] == 36
    assert row["default_guarantee_rate"] == 7.0
    assert row["default_downpayment_percent"] == 25.0


def test_inline_save_redirect_validates_return_to():
    client = _client()
    resp = client.post("/rent/contracts/equipment/save", data={
        "name": "Open Redirect Masina",
        "return_to": "//evil.example.com/x",
        **_csrf(client),
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/rent/contracts"), \
        "cross-site return_to must fall back to the contracts list"


def test_inline_save_empty_name_bounces_without_insert():
    client = _client()
    resp = client.post("/rent/contracts/equipment/save", data={
        "name": "   ",
        "return_to": "/rent/contracts/new",
        **_csrf(client),
    })
    assert resp.status_code == 302
    count = get_db().execute(
        "SELECT COUNT(*) c FROM rent_equipment;").fetchone()["c"]
    assert count == 0


def test_equipment_page_redirects_to_contracts():
    client = _client()
    resp = client.get("/rent/equipment")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/rent/contracts")
    # legacy POST (old form bookmarks) also redirects — no more CRUD there
    resp = client.post("/rent/equipment", data={
        "action": "save", "name": "X", **_csrf(client)})
    assert resp.status_code == 302
    count = get_db().execute(
        "SELECT COUNT(*) c FROM rent_equipment WHERE name='X';").fetchone()["c"]
    assert count == 0


def test_banner_has_no_equipment_link():
    client = _client()
    html = client.get("/rent/contracts").data.decode()
    assert 'href="/rent/equipment"' not in html


def test_edit_form_inline_catalog_and_delete_but_no_picker():
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_equipment (name, price) VALUES ('Katalog Masina', 100);")
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, status) "
        "VALUES ('EQ-1', 'Eq Firma', 'u_izradi');")
    conn.commit()
    cid = conn.execute(
        "SELECT id FROM rent_contracts WHERE contract_number='EQ-1';"
    ).fetchone()["id"]
    conn.close()

    html = client.get(f"/rent/contracts/edit/{cid}").data.decode()
    # inline catalog form markers
    assert "/rent/contracts/equipment/save" in html
    assert "Sačuvaj ovu opremu u bazu" in html
    # the PICKER is gone: no select of catalog entries, no autofill fetch
    assert 'id="equipSelect"' not in html
    assert "/rent/api/equipment/" not in html
    assert "Katalog Masina" not in html
    # free-text equipment entry remains
    assert 'id="equipment_model"' in html
    # delete button + modal on the record's own page
    assert f'data-action="/rent/contracts/delete/{cid}"' in html
    assert 'id="deleteModal"' in html
    assert "openDeleteModal" in html


def test_list_has_no_delete_no_inline_form_no_edit_button():
    client = _client()
    html = client.get("/rent/contracts").data.decode()
    assert "openDeleteModal" not in html
    assert "deleteModal" not in html
    assert "Sačuvaj ovu opremu u bazu" not in html
    # the Actions column is gone; the contract number is the edit link
    assert "Akcije" not in html
    assert 'class="btn btn-secondary btn-sm"' not in html


def test_equipment_autofill_api_removed():
    client = _client()
    resp = client.get("/rent/api/equipment/1")
    assert resp.status_code == 404


def test_delete_from_edit_still_works():
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, status) "
        "VALUES ('EQ-DEL', 'Del Firma', 'u_izradi');")
    conn.commit()
    cid = conn.execute(
        "SELECT id FROM rent_contracts WHERE contract_number='EQ-DEL';"
    ).fetchone()["id"]
    conn.close()

    resp = client.post(f"/rent/contracts/delete/{cid}", data=_csrf(client))
    assert resp.status_code == 302
    row = get_db().execute(
        "SELECT COUNT(*) c FROM rent_contracts WHERE id=?;", (cid,)
    ).fetchone()
    assert row["c"] == 0
