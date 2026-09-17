"""P5-unification tests: one shared party base (Zajednički imenik).

Pins the unification behavior:

* boot backfill copies legacy rent_clients into contacts exactly once
  (PIB/MB merge-aware), tracked by migrated_contact_id;
* /rent/clients redirects to the directory (GET), translates legacy POSTs;
* the rent contract picker feeds ONLY from the directory and the saved
  contract links contact_id while keeping its printed snapshot;
* the offer form party picker pre-fills musterija fields from a company
  AND a person contact; the saved offer links contact_id.
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.services import contact_service
from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _clean_directory():
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("DELETE FROM contact_links;")
    conn.execute("DELETE FROM contact_roles;")
    conn.execute("DELETE FROM contacts;")
    conn.execute("UPDATE rent_clients SET migrated_contact_id = NULL;")
    conn.commit()
    yield
    conn.close()


def _seed_legacy_client(name="Legacy Rent d.o.o.", pib="100000777", mb="200000777"):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO rent_clients (name, mb, pib, account, address,
                                  representative, email, rent_address, guarantor)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (name, mb, pib, "160-777", "Sedišta 1", "Potpisnik P.",
         "legacy@rent.example", "Zakupa 9", "Jemac J."),
    )
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


def _run_backfill():
    from qp_crm.shared.schema import backfill_rent_clients_into_contacts
    conn = get_db()
    cur = conn.cursor()
    backfill_rent_clients_into_contacts(cur)
    conn.commit()
    conn.close()


def test_backfill_copies_legacy_client_once():
    lid = _seed_legacy_client()
    _run_backfill()
    clients = contact_service.list_contacts(roles=["client"])
    assert any(r["display_name"] == "Legacy Rent d.o.o." for r in clients)
    contact = [r for r in clients if r["display_name"] == "Legacy Rent d.o.o."][0]
    # legacy fields mapped, nothing dropped
    assert contact["pib"] == "100000777"
    assert contact["mb"] == "200000777"
    assert contact["account"] == "160-777"
    assert contact["billing_address"] == "Sedišta 1"
    assert contact["job_title"] == "Potpisnik P."
    assert contact["email"] == "legacy@rent.example"
    assert "Adresa zakupa: Zakupa 9" in (contact["notes"] or "")
    assert "Jemac: Jemac J." in (contact["notes"] or "")
    # marker set: re-running backfill does NOT duplicate
    _run_backfill()
    names = [r["display_name"] for r in contact_service.list_contacts(roles=["client"])]
    assert names.count("Legacy Rent d.o.o.") == 1
    conn = get_db()
    marker = conn.execute(
        "SELECT migrated_contact_id FROM rent_clients WHERE id = ?;", (lid,)
    ).fetchone()["migrated_contact_id"]
    conn.close()
    assert marker == contact["id"]


def test_backfill_merges_by_pib_mb():
    ok, cid = contact_service.create_contact(
        "Already There d.o.o.", kind="company", roles=["client"],
        fields={"pib": "100000888", "mb": "200000888"})
    assert ok
    _seed_legacy_client(name="Already There d.o.o. (kopija)",
                        pib="100000888", mb="200000888")
    _run_backfill()
    # no duplicate: legacy row LINKS to the existing contact
    names = [r["display_name"] for r in contact_service.list_contacts(roles=["client"])]
    assert names.count("Already There d.o.o. (kopija)") == 0
    conn = get_db()
    marker = conn.execute(
        "SELECT migrated_contact_id FROM rent_clients WHERE pib = '100000888';"
    ).fetchone()["migrated_contact_id"]
    conn.close()
    assert marker == cid


def test_rent_clients_redirects_to_directory():
    client = login_client(app.test_client(), "offer")
    resp = client.get("/rent/clients")
    assert resp.status_code == 302
    assert "role=client" in resp.headers["Location"]
    # the directory page it lands on renders
    assert client.get(resp.headers["Location"]).status_code == 200


def test_rent_legacy_post_translates_to_directory():
    client = login_client(app.test_client(), "offer")
    resp = client.post("/rent/clients", data={
        "_csrf_token": csrf_token_for(client),
        "action": "save",
        "name": "Iz Legacy Forme d.o.o.",
        "mb": "200000999",
        "pib": "100000999",
        "address": "Forme 3",
    })
    assert resp.status_code == 302
    assert "role=client" in resp.headers["Location"]
    clients = contact_service.list_contacts(roles=["client"])
    saved = [r for r in clients if r["display_name"] == "Iz Legacy Forme d.o.o."]
    assert len(saved) == 1
    assert saved[0]["pib"] == "100000999"
    assert saved[0]["billing_address"] == "Forme 3"


def test_rent_contract_picker_and_link_roundtrip():
    client = login_client(app.test_client(), "offer")
    ok, cid = contact_service.create_contact(
        "Ugovornik d.o.o.", kind="company", roles=["client"],
        fields={"pib": "100001111", "city": "Kragujevac"})
    assert ok

    # picker lists the directory entry (c-ref), no legacy source
    form = client.get("/rent/contracts/new")
    assert f'value="c{cid}"'.encode() in form.data

    # autofill answers for the c-ref
    resp = client.get(f"/rent/api/client/c{cid}")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Ugovornik d.o.o."

    # POST the contract with the link; snapshot fields stay as typed
    resp = client.post("/rent/contracts/new", data={
        "_csrf_token": csrf_token_for(client),
        "contract_number": "",
        "contract_date": "2026-09-17",
        "contact_id": str(cid),
        "client_name": "Ugovornik d.o.o. (štampano)",
        "client_pib": "100001111",
        "price": "1000", "vat_percent": "20", "period_months": "48",
        "downpayment_percent": "20", "salvage_value_percent": "20",
        "interest_rate": "14", "insurance_rate": "1.13",
        "guarantee_rate": "5", "admin_fee": "50",
    })
    assert resp.status_code == 302
    conn = get_db()
    row = conn.execute(
        "SELECT contact_id, client_name FROM rent_contracts "
        "WHERE client_name LIKE 'Ugovornik%' ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    conn.close()
    assert row["contact_id"] == cid  # link saved
    assert row["client_name"] == "Ugovornik d.o.o. (štampano)"  # snapshot kept


def test_offer_party_picker_roundtrip():
    client = login_client(app.test_client(), "offer")
    ok, cid = contact_service.create_contact(
        "Musterija iz Imenika", kind="company", roles=["client"],
        fields={"pib": "100002222", "billing_address": "Imenik 12",
                "email": "musterija@example.com", "phone": "011/222-333"})
    assert ok

    # picker present on new-offer form
    form = client.get("/offer/offers/new")
    assert b'contact-select' in form.data
    assert f'value="{cid}"'.encode() in form.data

    # prefill page fills musterija fields from the directory
    prefill = client.get(f"/offer/offers/new?contact_id={cid}")
    assert b"Imenik 12" in prefill.data
    assert b"musterija@example.com" in prefill.data

    # POST with the link saves the snapshot AND the link
    resp = client.post("/offer/offers/new", data={
        "_csrf_token": csrf_token_for(client),
        "offer_number": "OFF-UNI-1",
        "date": "2026-09-17",
        "contact_id": str(cid),
        "client_name": "Musterija iz Imenika",
        "client_address": "Imenik 12",
        "country": "Srbija",
        "currency": "EUR",
        "exchange_rate": "117",
        "vat_percent": "20",
        "validity_days": "10",
    })
    assert resp.status_code == 302
    conn = get_db()
    row = conn.execute(
        "SELECT contact_id, client_name, client_address FROM offers "
        "WHERE offer_number = 'OFF-UNI-1';"
    ).fetchone()
    conn.close()
    assert row["contact_id"] == cid
    assert row["client_name"] == "Musterija iz Imenika"  # snapshot
    assert row["client_address"] == "Imenik 12"


def test_offer_person_prefill_uses_full_name():
    client = login_client(app.test_client(), "offer")
    ok, cid = contact_service.create_contact(
        "Pero Perić", kind="person", roles=["client"],
        fields={"first_name": "Pero", "last_name": "Perić",
                "jmbg": "0111985771234", "phone": "065/555-123"})
    assert ok
    prefill = client.get(f"/offer/offers/new?contact_id={cid}")
    assert "Pero Perić".encode() in prefill.data
