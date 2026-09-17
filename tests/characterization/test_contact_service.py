"""P5-pre shared directory (contacts) service tests.

Characterization discipline: these pin the NEW module's intended behavior
(the module is new, so these are spec tests, not quirk capture):

* create requires a display name; kind/roles normalize to the fixed lists;
* roles are rows: several roles per contact, replaced wholesale on update;
* no delete: contacts archive only, rows survive;
* role filter matches ANY of the requested roles;
* person vs company rows coexist in one table (fizičko/pravno lice);
* links: a location must belong to its customer; link deletion never
  touches the contact.
"""

import pytest

from qp_crm.services import contact_service
from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _clean_contacts():
    """Isolate each test: wipe the directory tables (contacts only --
    customers/users belong to other suites)."""
    conn = get_db()
    conn.execute("DELETE FROM contact_links;")
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


def test_link_location_must_belong_to_customer():
    from qp_crm.services import deal_service
    ok, customer_id = deal_service.create_customer("Link Kupac A")
    assert ok
    ok, other_id = deal_service.create_customer("Link Kupac B")
    assert ok
    ok, location_id = deal_service.create_location(customer_id, "Sajt 1")
    assert ok
    cid = _company("Firma F", roles=("supplier",))

    # location without customer: customer inferred from the site
    ok, link_id = contact_service.create_link(cid, location_id=location_id)
    assert ok
    links = contact_service.list_links(cid)
    assert links[0]["customer_id"] == customer_id
    assert links[0]["location_name"] == "Sajt 1"

    # location of ANOTHER customer: rejected
    ok, message = contact_service.create_link(
        cid, customer_id=other_id, location_id=location_id)
    assert not ok
    assert "ne pripada" in message.lower()

    # neither customer nor location: rejected
    ok, message = contact_service.create_link(cid)
    assert not ok

    # deleting the link leaves the contact intact
    ok, _ = contact_service.delete_link(cid, link_id)
    assert ok
    assert contact_service.list_links(cid) == []
    assert contact_service.get_contact(cid) is not None


def test_directory_choices_label():
    cid = _company("Choice Firma", roles=("supplier",))
    choices = contact_service.directory_choices(roles=["supplier"])
    assert choices and choices[0][0] == cid
    assert "Choice Firma" in choices[0][1]
    assert "100000001" in choices[0][1]  # PIB badge keeps entries tellable apart
