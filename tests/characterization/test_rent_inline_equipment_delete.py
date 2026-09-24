"""R-T4/R-T5 (2026-09-24 user request): the standalone /rent/equipment page
is gone; the contract form carries an inline add-to-catalog form, and the
Delete action moved from the contracts list into the contract edit form.

Pinned:

* POST /rent/contracts/contracts/equipment/save... (URL is
  /rent/contracts/equipment/save) creates a rent_equipment row from the
  inline form and redirects back to the contract form with ?eq_id=<new>;
* the redirect target is validated (same-site absolute path only) — a
  hand-crafted return_to falls back to the contracts list;
* an empty name bounces back without inserting;
* /rent/equipment (GET and POST) redirects to the contracts list;
* the rent banner no longer links the equipment page;
* the edit form renders the inline add-to-catalog form (marker strings)
  and the Delete button + confirm modal; the list has neither.
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
    assert resp.headers["Location"].startswith("/rent/contracts/edit/1?eq_id=")
    eq_id = int(resp.headers["Location"].rsplit("=", 1)[1])
    row = get_db().execute(
        "SELECT * FROM rent_equipment WHERE id=?;", (eq_id,)).fetchone()
    assert row["name"] == "Inline Test Masina"
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


def test_edit_form_has_inline_equipment_form_and_delete():
    client = _client()
    conn = get_db()
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
    assert "rent.save_equipment_inline" in html or \
           "/rent/contracts/equipment/save" in html
    assert "Dodaj novu opremu u bazu" in html
    # delete button + modal on the record's own page
    assert f'data-action="/rent/contracts/delete/{cid}"' in html
    assert 'id="deleteModal"' in html
    assert "openDeleteModal" in html


def test_list_has_no_delete_and_no_inline_form():
    client = _client()
    html = client.get("/rent/contracts").data.decode()
    assert "openDeleteModal" not in html
    assert "deleteModal" not in html
    assert "Dodaj novu opremu u bazu" not in html


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


def test_equipment_picker_prefills_from_new_entry():
    """After inline save the edit form preselects the new catalog entry
    (?eq_id=) so one save+fill round-trip completes without a search."""
    client = _client()
    resp = client.post("/rent/contracts/equipment/save", data={
        "name": "Preselect Masina",
        "price": "5000",
        "return_to": "/rent/contracts/edit/1",
        **_csrf(client),
    })
    eq_id = int(resp.headers["Location"].rsplit("=", 1)[1])
    html = client.get(f"/rent/contracts/edit/1?eq_id={eq_id}").data.decode()
    assert f'<option value="{eq_id}" selected>' in html
