"""P5-pre shared directory (contacts) HTTP-level tests: gating, pages, UI.

Extends the Phase-4 deals smoke discipline to /contacts:

* anonymous visitors redirect to the unified login on every contacts page;
* staff WITHOUT the 'contacts' grant get 403 (landing card hidden too);
* granted staff and admins reach every page;
* a company (dobavljač) and a person (spoljni saradnik / fizičko lice)
  round-trip through the real routes with CSRF;
* the rent contract picker picks up directory clients (c<id> refs).
"""

import secrets

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.auth import (
    get_db,
    get_user_modules,
    set_user_modules,
)

CONTACTS_PAGES = (
    "/contacts/",
    "/contacts/contacts",
    "/contacts/contacts/new",
)


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _restore_grants():
    """Leave the seeded staff grants exactly as found."""
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()
    snapshot = get_user_modules(uid)
    yield
    set_user_modules(uid, snapshot)


@pytest.fixture(autouse=True)
def _clean_contacts():
    """Isolate each test: wipe the directory tables."""
    conn = get_db()
    conn.execute("DELETE FROM contact_locations;")
    conn.execute("DELETE FROM contact_roles;")
    conn.execute("DELETE FROM contacts;")
    conn.commit()
    conn.close()


def _post(client, path, data):
    data = dict(data)
    data["_csrf_token"] = csrf_token_for(client)
    return client.post(path, data=data)


def test_anonymous_redirects_to_login():
    client = app.test_client()
    for path in CONTACTS_PAGES:
        resp = client.get(path)
        assert resp.status_code == 302, path
        assert resp.headers["Location"].startswith("/login"), path


def test_ungranted_staff_gets_403():
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()
    set_user_modules(uid, ["offer"])  # trim contacts off the offer account
    fresh = login_client(app.test_client(), "offer")
    resp = fresh.get("/contacts/contacts")
    assert resp.status_code == 403
    assert b"contacts" in resp.data.lower()  # message names the missing app
    # landing card hidden for the ungranted staff user
    landing = fresh.get("/")
    assert b'href="/contacts/"' not in landing.data


def test_granted_staff_reaches_all_pages():
    client = login_client(app.test_client(), "offer")
    for path in CONTACTS_PAGES:
        resp = client.get(path)
        # /contacts/ is a convenience redirect to the directory list
        if path == "/contacts/":
            assert resp.status_code == 302
            assert resp.headers["Location"].endswith("/contacts/contacts")
        else:
            assert resp.status_code == 200, path


def test_create_company_supplier_and_person_collaborator():
    client = login_client(app.test_client(), "offer")
    resp = _post(client, "/contacts/contacts/new", {
        "display_name": "Test Dobavljač d.o.o.",
        "kind": "company",
        "roles": ["supplier", "client"],
        "pib": "123456789",
        "city": "Novi Sad",
    })
    assert resp.status_code == 302
    company_url = resp.headers["Location"]

    resp = _post(client, "/contacts/contacts/new", {
        "display_name": "Marko Marković",
        "kind": "person",
        "roles": ["external_collaborator", "employee"],
        "first_name": "Marko",
        "last_name": "Marković",
        "jmbg": "0101990123456",
    })
    assert resp.status_code == 302
    person_url = resp.headers["Location"]

    # listing shows both, with role + kind badges
    listing = client.get("/contacts/contacts")
    assert b"Test Dobavlja" in listing.data
    assert b"Marko Markovi" in listing.data

    # role filter isolates the supplier
    only_suppliers = client.get("/contacts/contacts?role=supplier")
    assert b"Test Dobavlja" in only_suppliers.data
    assert b"Marko Markovi" not in only_suppliers.data

    # detail pages render
    assert client.get(company_url).status_code == 200
    assert client.get(person_url).status_code == 200


def test_archive_hides_from_default_listing():
    client = login_client(app.test_client(), "offer")
    resp = _post(client, "/contacts/contacts/new", {
        "display_name": "Arhiva Firma",
        "kind": "company",
        "roles": ["supplier"],
    })
    contact_url = resp.headers["Location"]
    contact_id = contact_url.rstrip("/").rsplit("/", 1)[-1]
    resp = _post(client, f"/contacts/contacts/{contact_id}/archive",
                 {"archive": "1"})
    listing = client.get("/contacts/contacts")
    assert b"Arhiva Firma" not in listing.data
    archived = client.get("/contacts/contacts?archived=1")
    assert b"Arhiva Firma" in archived.data


def test_rent_picker_includes_directory_clients():
    client = login_client(app.test_client(), "offer")
    resp = _post(client, "/contacts/contacts/new", {
        "display_name": "Imenik Zakupac d.o.o.",
        "kind": "company",
        "roles": ["client"],
        "pib": "987654321",
    })
    contact_url = resp.headers["Location"]
    contact_id = contact_url.rstrip("/").rsplit("/", 1)[-1]

    # autofill feed answers for c<id>
    resp = client.get(f"/rent/api/client/c{contact_id}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Imenik Zakupac d.o.o."
    assert data["pib"] == "987654321"

    # contract form lists the directory client
    form = client.get("/rent/contracts/new")
    assert b"Imenik Zakupac d.o.o." in form.data
