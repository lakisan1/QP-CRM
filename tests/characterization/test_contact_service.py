"""P5-pre shared directory (contacts) service tests.

Characterization discipline: these pin the NEW module's intended behavior
(the module is new, so these are spec tests, not quirk capture):

* create requires a display name; kind/roles normalize to the fixed lists;
* roles are rows: several roles per contact, replaced wholesale on update;
* no delete: contacts archive only, rows survive;
* role filter matches ANY of the requested roles;
* person vs company rows coexist in one table (fizičko/pravno lice);
* locations: a contact's sites live in contact_locations (the directory is
  the ONLY party registry -- the deals-spine customers tables are gone);
* linked_documents resolves offers + rent contracts by contact_id.
"""

import pytest

from conftest import login_client
from qp_crm.main import app
from qp_crm.services import contact_service
from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _clean_contacts():
    """Isolate each test: wipe the directory tables. Document rows that
    reference a wiped contact are wiped too (they are this suite's
    fixtures, not user data) -- offers.contact_id / rent_contracts.contact_id
    would otherwise block the wipe (FK)."""
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("DELETE FROM offers;")
    conn.execute("DELETE FROM rent_contracts;")
    conn.execute("DELETE FROM contact_locations;")
    conn.execute("DELETE FROM contact_roles;")
    conn.execute("DELETE FROM contacts;")
    conn.commit()
    yield
    conn.close()


def _company(name, roles=("client",)):
    ok, result = contact_service.create_contact(
        name, kind="company", roles=roles,
        fields={"pib": "100000001", "city": "Beograd"})
    assert ok, result
    return result


def test_create_requires_display_name():
    ok, message = contact_service.create_contact("   ")
    assert not ok
    assert "obavezan" in message.lower()


def test_create_normalizes_kind_and_roles():
    ok, cid = contact_service.create_contact(
        "Firma A", kind="spaceship", roles=["supplier", "bogus_role"])
    assert ok
    contact = contact_service.get_contact(cid)
    assert contact["kind"] == "company"  # unknown kind -> company
    assert contact["roles"] == ["supplier"]  # unknown role ignored


def test_person_and_company_in_one_table():
    ok, company_id = contact_service.create_contact(
        "Firma B", kind="company", roles=["supplier"],
        fields={"pib": "11111111", "mb": "22222222"})
    ok, person_id = contact_service.create_contact(
        "Petar Petrović", kind="person", roles=["external_collaborator"],
        fields={"first_name": "Petar", "last_name": "Petrović",
                "jmbg": "0101990123456"})
    companies = contact_service.list_contacts(kind="company")
    persons = contact_service.list_contacts(kind="person")
    assert [r["id"] for r in companies] == [company_id]
    assert [r["id"] for r in persons] == [person_id]
    person = contact_service.get_contact(person_id)
    assert person["first_name"] == "Petar"
    assert person["last_name"] == "Petrović"


def test_multiple_roles_and_role_filter_any_match():
    cid = _company("Duo Role d.o.o.", roles=("supplier", "client"))
    got = contact_service.contacts_by_role("supplier")
    assert [r["id"] for r in got] == [cid]
    got = contact_service.contacts_by_role("client")
    assert [r["id"] for r in got] == [cid]
    # unknown role never matches
    assert contact_service.contacts_by_role("bogus") == []


def test_update_replaces_roles_and_clears_links():
    cid = _company("Firma C", roles=("supplier",))
    ok, _ = contact_service.update_contact(
        cid, "Firma C preimenovana", kind="company",
        roles=["employee"], fields={"user_id": None, "pib": "999"})
    assert ok
    contact = contact_service.get_contact(cid)
    assert contact["display_name"] == "Firma C preimenovana"
    assert contact["roles"] == ["employee"]
    assert contact["pib"] == "999"


def test_update_empty_name_rejected():
    cid = _company("Firma D")
    ok, message = contact_service.update_contact(cid, "")
    assert not ok
    # unchanged
    assert contact_service.get_contact(cid)["display_name"] == "Firma D"


def test_archive_not_delete():
    cid = _company("Firma E")
    ok, _ = contact_service.set_contact_archived(cid, True)
    assert ok
    conn = get_db()
    row = conn.execute("SELECT * FROM contacts WHERE id = ?;", (cid,)).fetchone()
    conn.close()
    assert row is not None  # row survives
    assert row["archived"] == 1
    # hidden from the default listing, visible with include_archived
    assert all(r["id"] != cid for r in contact_service.list_contacts())
    assert any(r["id"] == cid for r in contact_service.list_contacts(include_archived=True))


def test_search_matches_identity_fields():
    _company("Zebra Trading", roles=("supplier",))
    ok, pid = contact_service.create_contact(
        "Ana Anić", kind="person", roles=["client"],
        fields={"jmbg": "0202000123456", "phone": "064/123-456"})
    assert ok
    by_name = contact_service.list_contacts(search="zebra")
    assert len(by_name) == 1 and by_name[0]["display_name"] == "Zebra Trading"
    by_jmbg = contact_service.list_contacts(search="0202000123456")
    assert len(by_jmbg) == 1 and by_jmbg[0]["id"] == pid
    by_phone = contact_service.list_contacts(search="064")
    assert any(r["id"] == pid for r in by_phone)


def test_contact_locations_crud():
    cid = _company("Firma F", roles=("supplier",))
    ok, location_id = contact_service.create_contact_location(
        cid, "Sajt 1", address="Ulica 1", city="Beograd",
        contact_name="Marko", contact_phone="064/000-000")
    assert ok
    locs = contact_service.list_contact_locations(cid)
    assert len(locs) == 1 and locs[0]["name"] == "Sajt 1"

    # empty name rejected
    ok, message = contact_service.create_contact_location(cid, "  ")
    assert not ok
    assert "obavezan" in message.lower()

    # unknown contact rejected
    ok, message = contact_service.create_contact_location(99999, "X")
    assert not ok

    # update works
    ok, message = contact_service.update_contact_location(
        location_id, "Sajt 1 renamed", city="Novi Sad")
    assert ok
    locs = contact_service.list_contact_locations(cid)
    assert locs[0]["name"] == "Sajt 1 renamed" and locs[0]["city"] == "Novi Sad"


def test_linked_documents_resolves_by_contact():
    cid = _company("Firma G", roles=("client",))
    # no documents yet
    assert contact_service.linked_documents(cid) == []
    # an offer referencing the contact shows up
    conn = get_db()
    conn.execute(
        """
        INSERT INTO offers (offer_number, date, client_name, client_pib,
                            total_net, total_gross, contact_id)
        VALUES ('P-TEST-1', '2026-09-16', 'Firma G', '100000001', 0, 0, ?);
        """, (cid,))
    conn.commit()
    docs = contact_service.linked_documents(cid)
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "offer"
    assert docs[0]["doc_number"] == "P-TEST-1"
    # a rent contract referencing it shows up too
    conn.execute(
        """
        INSERT INTO rent_contracts (contract_number, contract_date, client_name,
                                    contact_id, price)
        VALUES ('Z-TEST-1', '2026-09-16', 'Firma G', ?, 0);
        """, (cid,))
    conn.commit()
    docs = contact_service.linked_documents(cid)
    assert {d["doc_type"] for d in docs} == {"offer", "rent_contract"}
    conn.close()


def test_directory_choices_label():
    cid = _company("Choice Firma", roles=("supplier",))
    choices = contact_service.directory_choices(roles=["supplier"])
    assert choices and choices[0][0] == cid
    assert "Choice Firma" in choices[0][1]
    assert "100000001" in choices[0][1]  # PIB badge keeps entries tellable apart


# ---------------------------------------------------------------------------
# 2026-09-24 model: glavna adresa = podrazumevana lokacija
# ---------------------------------------------------------------------------

def test_location_choices_merges_main_address_and_extras():
    cid = _company("Lok Firma", roles=("client",))
    ok, _ = contact_service.update_contact(
        cid, "Lok Firma", kind="company",
        fields={"billing_address": "Glavna 1", "city": "Beograd"})
    assert ok
    ok, _ = contact_service.create_contact_location(
        cid, "Magacin", address="Magacinska 5", city="Zemun")
    assert ok

    choices = contact_service.location_choices(cid)
    # default FIRST, virtual id 0, resolved live from the contact row
    assert choices[0]["id"] == contact_service.MAIN_LOCATION_ID
    assert choices[0]["label"] == "Glavna adresa"
    assert choices[0]["address"] == "Glavna 1"
    assert choices[0]["city"] == "Beograd"
    # extras after, by real id
    assert choices[1]["label"] == "Magacin"
    assert choices[1]["address"] == "Magacinska 5"

    # single-address contact WITHOUT main address: only extras
    ok, pid = contact_service.create_contact("Bez Adrese", kind="person")
    assert ok
    assert contact_service.location_choices(pid) == []


def test_location_choices_and_crud_carry_postal_and_country():
    cid = _company("Posta Firma", roles=("client",))
    ok, _ = contact_service.update_contact(
        cid, "Posta Firma", kind="company",
        fields={"billing_address": "Glavna 1", "city": "Beograd",
                "country": "Srbija"})
    assert ok

    # main (default) site inherits the contact's country
    main = contact_service.location_choices(cid)[0]
    assert main["postal_code"] == "" and main["country"] == "Srbija"

    ok, extra_id = contact_service.create_contact_location(
        cid, "Magacin", address="Magacinska 5", city="Zemun",
        postal_code="11080", country="Srbija")
    assert ok
    locs = contact_service.list_contact_locations(cid)
    assert locs[0]["postal_code"] == "11080"
    assert locs[0]["country"] == "Srbija"

    # update persists both fields
    ok, _ = contact_service.update_contact_location(
        extra_id, "Magacin", postal_code="11081", country="Crna Gora")
    assert ok
    locs = contact_service.list_contact_locations(cid)
    assert locs[0]["postal_code"] == "11081"
    assert locs[0]["country"] == "Crna Gora"

    # choices expose them
    extra = [c for c in contact_service.location_choices(cid) if c["id"] == extra_id][0]
    assert extra["postal_code"] == "11081" and extra["country"] == "Crna Gora"


def test_resolve_location_default_and_extras():
    cid = _company("Res Firma", roles=("client",))
    ok, _ = contact_service.update_contact(
        cid, "Res Firma", kind="company",
        fields={"billing_address": "Glavna 9", "city": "Novi Sad"})
    assert ok
    ok, extra_id = contact_service.create_contact_location(
        cid, "Dvoriste", address="Bočna 2", city="Novi Sad",
        postal_code="21000", country="Srbija")
    assert ok

    # default: None / "" / 0 all resolve the MAIN billing address
    default = contact_service.resolve_location(cid, None)
    assert default["address"] == "Glavna 9" and default["city"] == "Novi Sad"
    assert contact_service.resolve_location(cid, 0)["address"] == "Glavna 9"
    # extra object resolves its own full address incl. postal + country
    extra = contact_service.resolve_location(cid, extra_id)
    assert extra["address"] == "Bočna 2"
    assert extra["postal_code"] == "21000" and extra["country"] == "Srbija"
    # another contact's site NEVER resolves (no cross-party leak)
    ok, other_cid = contact_service.create_contact("Druga Firma", kind="company")
    assert ok
    assert contact_service.resolve_location(other_cid, extra_id) is None
    # unknown id -> None
    assert contact_service.resolve_location(cid, 99999) is None


def test_offer_autofill_api_exposes_sites():
    client = login_client(app.test_client(), "offer")
    cid = _company("Sajt Firma", roles=("client",))
    ok, _ = contact_service.update_contact(
        cid, "Sajt Firma", kind="company",
        fields={"billing_address": "Glavna 7", "city": "Beograd"})
    assert ok
    ok, _ = contact_service.create_contact_location(
        cid, "Gradiliste", address="Autoput 5", city="Beograd",
        postal_code="11070", country="Srbija")
    assert ok
    resp = client.get(f"/offer/api/contact/{cid}")
    data = resp.get_json()
    assert data["address"] == "Glavna 7"
    sites = data["sites"]
    assert sites[0]["id"] == 0 and sites[0]["label"] == "Glavna adresa"
    site = [s for s in sites if s["label"] == "Gradiliste"][0]
    assert site["postal_code"] == "11070" and site["country"] == "Srbija"


def test_rent_autofill_api_exposes_sites():
    client = login_client(app.test_client(), "offer")
    cid = _company("Rent Sajt Firma", roles=("client",))
    ok, _ = contact_service.update_contact(
        cid, "Rent Sajt Firma", kind="company",
        fields={"billing_address": "Glavna 3"})
    assert ok
    ok, _ = contact_service.create_contact_location(
        cid, "Objekat 2", address="Peta 6")
    assert ok
    resp = client.get(f"/rent/api/client/c{cid}")
    sites = resp.get_json()["sites"]
    assert sites[0]["id"] == 0 and sites[0]["address"] == "Glavna 3"
    assert any(s["label"] == "Objekat 2" for s in sites)
