"""Musterija-first UX (P5-unification, user request 2026-09-22).

The shared directory is the ONLY place a new musterija is created; the
offer and rent document forms keep just the search picker plus a
'Dodaj novu musteriju' shortcut. The document forms gate the rest of the
client fields behind the picker (frontend-only enforcement -- no server
validation change, legacy free-typed documents keep working).

Pinned here:

* both document forms link /contacts/contacts/new with ?return_to= back
  to themselves;
* the contacts create form carries return_to through the POST (hidden
  field) and, after saving, redirects back to the DOCUMENT with
  ?contact_id=<new> so the party is already picked;
* return_to is validated: only same-site /offer/* and /rent/* paths pass;
  anything else (//host, /admin, empty) falls back to the normal detail
  redirect;
* the gate wrappers (musterija-rest) render hidden on fresh forms and
  the picker JS unhides them (script presence pinned by marker strings).
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _clean_contacts():
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


def _post(client, path, data):
    data = dict(data)
    data["_csrf_token"] = csrf_token_for(client)
    return client.post(path, data=data)


def test_offer_form_links_new_contact_with_return_to():
    client = login_client(app.test_client(), "offer")
    form = client.get("/offer/offers/new")
    assert b'href="/contacts/contacts/new?return_to=/offer/offers/new"' in form.data
    assert b"+ Dodaj novu musteriju" in form.data


def test_rent_form_links_new_contact_with_return_to():
    client = login_client(app.test_client(), "rent")
    form = client.get("/rent/contracts/new")
    assert b'href="/contacts/contacts/new?return_to=/rent/contracts/new"' in form.data
    assert b"+ Dodaj novu musteriju" in form.data


def test_offer_form_gate_wrapper_hidden_until_picked():
    """Fresh form: the musterija field block renders inside the hidden
    wrapper; the picker JS (applyGate) unhides it on selection."""
    client = login_client(app.test_client(), "offer")
    form = client.get("/offer/offers/new")
    assert b'id="musterija-rest" style="display: none;"' in form.data
    assert b'id="musterija-step"' in form.data


def test_rent_form_gate_wrapper_hidden_until_picked():
    client = login_client(app.test_client(), "rent")
    form = client.get("/rent/contracts/new")
    assert b'id="musterija-rest" style="display: none;"' in form.data
    assert b'id="musterija-step"' in form.data
    # picker JS re-applies the gate on every change
    assert b"applyMusterijaGate" in form.data


def test_return_to_carries_through_post_back_to_document():
    client = login_client(app.test_client(), "offer")
    # hidden field echoes the validated return target on GET
    cform = client.get("/contacts/contacts/new?return_to=/rent/contracts/new")
    assert b'name="return_to" value="/rent/contracts/new"' in cform.data

    resp = _post(client, "/contacts/contacts/new", {
        "display_name": "Povratna Firma d.o.o.",
        "kind": "company",
        "roles": ["client"],
        "pib": "100007777",
        "return_to": "/rent/contracts/new",
    })
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert location.startswith("/rent/contracts/new?contact_id=")
    new_id = location.rsplit("=", 1)[1]

    # the rent picker now offers the new party (c-ref)...
    rform = client.get("/rent/contracts/new")
    assert b"Povratna Firma d.o.o." in rform.data
    # ...and the offer prefill path fills musterija fields from it
    prefill = client.get(f"/offer/offers/new?contact_id={new_id}")
    assert b"Povratna Firma d.o.o." in prefill.data


def test_return_to_offer_variant():
    client = login_client(app.test_client(), "offer")
    resp = _post(client, "/contacts/contacts/new", {
        "display_name": "Ponudna Firma d.o.o.",
        "kind": "company",
        "roles": ["client"],
        "return_to": "/offer/offers/new",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/offer/offers/new?contact_id=")


@pytest.mark.parametrize("bad", [
    "//evil.example.com/x",
    "/admin/",
    "/contacts/contacts",
    "http://evil.example.com/x",
    "",
])
def test_unsafe_return_to_falls_back_to_detail(bad):
    client = login_client(app.test_client(), "offer")
    resp = _post(client, "/contacts/contacts/new", {
        "display_name": f"Bez Povratka {bad[:12]!r} d.o.o.",
        "kind": "company",
        "return_to": bad,
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/contacts/contacts/")


def test_without_return_to_normal_detail_redirect():
    """The plain 'Novi kontakt' flow is unchanged."""
    client = login_client(app.test_client(), "offer")
    resp = _post(client, "/contacts/contacts/new", {
        "display_name": "Običan Unos d.o.o.",
        "kind": "company",
        "roles": ["client"],
    })
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/contacts/contacts/")
