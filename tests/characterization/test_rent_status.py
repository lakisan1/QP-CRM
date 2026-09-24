"""Rent contract lifecycle status (2026-09-24 user request).

Replaces the is_signed boolean with five fixed statuses
(u_izradi / poslata_ponuda / prihvacena_ponuda / potpisan_ugovor /
zatvoren_ugovor). Pinned behavior:

* legacy DBs: migrate_rent_tables adds the column and translates
  is_signed=1 rows to 'potpisan_ugovor' once — a later user change of
  status survives re-boots (only 'u_izradi' rows are matched);
* the edit form renders a select with all five options, current value
  selected, default 'u_izradi' for a new contract;
* POST persists the status; a value outside the fixed list falls back to
  the default (no 500 on a hand-crafted POST), and a POST without the
  field (legacy callers) saves the default;
* the contracts list shows a read-only badge per status and no longer
  offers the signed/unsigned filter or the toggle endpoint;
* /rent/contracts/toggle_signed/<id> is gone (404) — the UI no longer
  uses it and dead write endpoints do not stay alive.
"""

import sys

import pytest

sys.path.insert(0, "tests")

from conftest import csrf_token_for, login_client  # noqa: E402
from qp_crm.main import app  # noqa: E402
from qp_crm.rent.app import (  # noqa: E402
    CONTRACT_STATUSES,
    STATUS_DEFAULT,
    STATUS_LABELS,
    STATUS_VALUES,
)
from qp_crm.shared.db import get_db  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _clean_contracts():
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


def test_status_constants_are_the_fixed_five():
    assert STATUS_VALUES == (
        "u_izradi", "poslata_ponuda", "prihvacena_ponuda",
        "potpisan_ugovor", "zatvoren_ugovor",
    )
    assert STATUS_DEFAULT == "u_izradi"
    # default is the first tuple entry (dropdown order == lifecycle order)
    assert CONTRACT_STATUSES[0] == (STATUS_DEFAULT, "U izradi")
    assert len(STATUS_LABELS) == 5


def test_edit_form_renders_status_select_with_default():
    client = _client()
    form = client.get("/rent/contracts/new")
    html = form.data.decode()
    assert 'name="status"' in html
    for _value, label in CONTRACT_STATUSES:
        assert label in html, label
    assert '<option value="u_izradi" selected>' in html


def test_new_contract_post_without_status_saves_default():
    client = _client()
    resp = client.post("/rent/contracts/new", data={
        "contract_number": "ST-A", "contract_date": "2026-09-24",
        "client_name": "Status Firma A", "price": "1000", **_csrf(client),
    })
    assert resp.status_code == 302
    row = get_db().execute(
        "SELECT status FROM rent_contracts WHERE contract_number='ST-A';"
    ).fetchone()
    assert row["status"] == STATUS_DEFAULT


def test_edit_post_persists_chosen_status():
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, status) "
        "VALUES ('ST-B', 'Status Firma B', 'u_izradi');")
    conn.commit()
    cid = conn.execute(
        "SELECT id FROM rent_contracts WHERE contract_number='ST-B';"
    ).fetchone()["id"]
    conn.close()

    # GET edit form: current status pre-selected
    html = client.get(f"/rent/contracts/edit/{cid}").data.decode()
    assert '<option value="u_izradi" selected>' in html

    resp = client.post(f"/rent/contracts/edit/{cid}", data={
        "contract_number": "ST-B", "client_name": "Status Firma B",
        "price": "1000", "status": "poslata_ponuda", **_csrf(client),
    })
    assert resp.status_code == 302
    row = get_db().execute(
        "SELECT status FROM rent_contracts WHERE id=?;", (cid,)
    ).fetchone()
    assert row["status"] == "poslata_ponuda"


def test_bogus_status_falls_back_not_500():
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, status) "
        "VALUES ('ST-C', 'Status Firma C', 'potpisan_ugovor');")
    conn.commit()
    cid = conn.execute(
        "SELECT id FROM rent_contracts WHERE contract_number='ST-C';"
    ).fetchone()["id"]
    conn.close()

    resp = client.post(f"/rent/contracts/edit/{cid}", data={
        "contract_number": "ST-C", "client_name": "Status Firma C",
        "price": "1000", "status": "hacked-value", **_csrf(client),
    })
    assert resp.status_code == 302  # no 500
    row = get_db().execute(
        "SELECT status FROM rent_contracts WHERE id=?;", (cid,)
    ).fetchone()
    assert row["status"] == STATUS_DEFAULT


def test_list_shows_read_only_status_badges():
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, status) "
        "VALUES ('ST-D', 'Status Firma D', 'potpisan_ugovor');")
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, status) "
        "VALUES ('ST-E', 'Status Firma E', 'zatvoren_ugovor');")
    conn.commit()
    conn.close()

    html = client.get("/rent/contracts").data.decode()
    assert 'status-badge status-potpisan_ugovor">Potpisan ugovor<' in html
    assert 'status-badge status-zatvoren_ugovor">Zatvoren ugovor<' in html
    # the old interactive UI is gone
    assert "toggle_signed" not in html
    assert 'name="signed"' not in html
    assert "Signature status" not in html
    # actions cell is an Edit link now, no Delete button
    assert ">Edit<" in html or ">Izmeni<" in html
    assert "Delete Contract" not in html


def test_legacy_signed_url_param_is_ignored_gracefully():
    client = _client()
    resp = client.get("/rent/contracts?signed=signed")
    assert resp.status_code == 200


def test_toggle_signed_endpoint_removed():
    """The write endpoint is gone: without a CSRF token the CSRF layer still
    answers 400 (it runs before routing), so assert the handler itself is
    unregistered — a valid-token POST must not find the route."""
    client = _client()
    resp = client.post("/rent/contracts/toggle_signed/1",
                       data={"_csrf_token": csrf_token_for(client)})
    assert resp.status_code == 404


def test_migration_translates_legacy_signed_rows():
    """Simulate a legacy DB row (is_signed=1, no status) meeting the new
    migrate_rent_tables — signed rows translate once, unsigned rows land on
    the default, and a later status edit survives a re-run."""
    from qp_crm.shared.schema import migrate_rent_tables

    conn = get_db()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("DELETE FROM rent_contract_documents;")
    conn.execute("DELETE FROM rent_contracts;")
    conn.commit()
    # raw legacy-style insert (is_signed only)
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, is_signed) "
        "VALUES ('ST-MIG-S', 'Mig Signed', 1);")
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, client_name, is_signed) "
        "VALUES ('ST-MIG-U', 'Mig Unsigned', 0);")
    conn.commit()
    conn.close()

    conn = get_db()
    cur = conn.cursor()
    migrate_rent_tables(cur)
    conn.commit()
    rows = {r["contract_number"]: r["status"] for r in conn.execute(
        "SELECT contract_number, status FROM rent_contracts;")}
    assert rows["ST-MIG-S"] == "potpisan_ugovor"
    assert rows["ST-MIG-U"] == STATUS_DEFAULT
    conn.close()

    # user later closes the signed contract; reboot (re-run) must not undo it
    conn = get_db()
    conn.execute(
        "UPDATE rent_contracts SET status='zatvoren_ugovor' "
        "WHERE contract_number='ST-MIG-S';")
    conn.commit()
    migrate_rent_tables(conn.cursor())
    conn.commit()
    row = conn.execute(
        "SELECT status FROM rent_contracts WHERE contract_number='ST-MIG-S';"
    ).fetchone()
    conn.close()
    assert row["status"] == "zatvoren_ugovor"
