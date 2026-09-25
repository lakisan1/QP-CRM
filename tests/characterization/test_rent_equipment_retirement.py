"""R-T4/R-T5/R-T7/R-T8 (2026-09-24 user requests): the equipment catalog is
FULLY RETIRED and the contract-list UI was slimmed down.

Final state, pinned here:

* the standalone /rent/equipment page is gone (redirect to the contracts
  list — old bookmarks and the old header link land safely);
* the contract form has NO equipment picker and NO add-to-catalog form —
  section '4. Oprema' is only the free-text equipment_model textarea;
* POST /rent/contracts/equipment/save is gone (404 via CSRF/routing);
* GET /rent/api/equipment/<id> is gone (404);
* a fresh DB never creates rent_equipment (schema retired it); a legacy DB
  that still has the table is tolerated (orphan, no reader/writer);
* the contracts list has NO Actions column and NO Edit button — the
  contract number is the link; no Delete on the list;
* the Delete action lives in the contract EDIT form behind a confirm
  modal.
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
    conn.commit()
    yield
    conn.close()


def _client():
    return login_client(app.test_client(), "rent")


def _csrf(client):
    return {"_csrf_token": csrf_token_for(client)}


# ── R-T8: the catalog is retired ──────────────────────────────────────────────

def test_fresh_schema_does_not_create_rent_equipment():
    conn = get_db()
    row = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' "
        "AND name='rent_equipment';").fetchone()
    conn.close()
    assert row[0] == 0, "rent_equipment must not be created by init anymore"


def test_legacy_rent_equipment_table_is_tolerated():
    """A legacy DB that still carries the (now orphan) table must boot and
    serve the contract form without errors."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rent_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            default_rent_months INTEGER DEFAULT 48,
            default_guarantee_rate REAL DEFAULT 5.0,
            default_downpayment_percent REAL DEFAULT 20.0
        );
    """)
    conn.execute(
        "INSERT INTO rent_equipment (name, price) VALUES ('Legacy Masina', 100);")
    conn.commit()
    conn.close()

    client = _client()
    html = client.get("/rent/contracts/new").data.decode()
    assert 'id="equipment_model"' in html
    # none of the retired catalog UI leaks into the form
    assert "equipSelect" not in html
    assert "Sačuvaj ovu opremu u bazu" not in html
    assert "rent_equipment" not in html

    # drop the simulated legacy table so later tests see fresh-schema state
    conn = get_db()
    conn.execute("DROP TABLE IF EXISTS rent_equipment;")
    conn.commit()
    conn.close()


def test_equipment_save_endpoint_removed():
    client = _client()
    # CSRF layer answers 400 before routing; with a token the route is gone
    resp = client.post("/rent/contracts/equipment/save",
                       data={"name": "X", "_csrf_token": csrf_token_for(client)})
    assert resp.status_code == 404


def test_equipment_autofill_api_removed():
    client = _client()
    resp = client.get("/rent/api/equipment/1")
    assert resp.status_code == 404


def test_equipment_page_redirects_to_contracts():
    client = _client()
    resp = client.get("/rent/equipment")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/rent/contracts")
    # legacy POST (old form bookmarks) also redirects — no more CRUD there
    resp = client.post("/rent/equipment", data={
        "action": "save", "name": "X", **_csrf(client)})
    assert resp.status_code == 302


def test_banner_has_no_equipment_link():
    client = _client()
    html = client.get("/rent/contracts").data.decode()
    assert 'href="/rent/equipment"' not in html


# ── R-T7: the list is slimmed down ────────────────────────────────────────────

def test_list_has_no_actions_column_no_edit_button():
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, status) "
        "VALUES ('EQ-1', 'Eq Firma', 'u_izradi');")
    conn.commit()
    conn.close()

    html = client.get("/rent/contracts").data.decode()
    assert "Akcije" not in html
    assert 'class="btn btn-secondary btn-sm"' not in html
    # the contract number is the edit link
    assert 'href="/rent/contracts/edit/' in html


# ── R-T4/R-T7: edit form carries delete + status, no picker, no catalog ──────

def test_edit_form_has_delete_modal_and_status_but_no_catalog():
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, status) "
        "VALUES ('EQ-2', 'Eq Firma 2', 'u_izradi');")
    conn.commit()
    cid = conn.execute(
        "SELECT id FROM rent_contracts WHERE contract_number='EQ-2';"
    ).fetchone()["id"]
    conn.close()

    html = client.get(f"/rent/contracts/edit/{cid}").data.decode()
    # delete button + modal on the record's own page
    assert f'data-action="/rent/contracts/delete/{cid}"' in html
    assert 'id="deleteModal"' in html
    assert "openDeleteModal" in html
    # status select present (R-T1/R-T2)
    assert 'name="status"' in html
    # retired catalog UI absent
    assert "equipSelect" not in html
    assert "Sačuvaj ovu opremu u bazu" not in html
    assert "/rent/contracts/equipment/save" not in html
    # free-text equipment entry remains
    assert 'id="equipment_model"' in html


def test_list_has_no_delete_and_no_catalog_form():
    client = _client()
    html = client.get("/rent/contracts").data.decode()
    assert "openDeleteModal" not in html
    assert "deleteModal" not in html
    assert "Sačuvaj ovu opremu u bazu" not in html


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


def test_equipment_csv_seed_not_run():
    """The Marikovic Hofmann Rent Oprema.csv seed is retired: even a fresh
    DB has no equipment rows because there is no table and no seed."""
    conn = get_db()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table';").fetchall()}
    assert "rent_equipment" not in tables
    conn.close()
