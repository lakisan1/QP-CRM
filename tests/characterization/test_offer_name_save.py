"""Offer NAME (offers.offer_number) save path -- user report 2026-11-04.

The offer name was reported as "not saving". The save path had three
independent defects, all pinned here:

* creating an offer with a name that already exists answered HTTP 500
  (UnboundLocalError: current_language in the duplicate-name re-render);
  the same re-render also lacked offer.id / presets_by_cat, so it could not
  render at all;
* the mandatory-field re-render answered HTTP 500 for the same missing
  offer.id (the template's edit-only blocks build
  url_for('offer.offer_pdf', offer_id=offer.id));
* the form's background header save (fetch before "Dodaj u ponudu") treated
  the 302+re-render rejection as success, so a rejected/blank name was
  silently dropped. It now asks for X-Requested-With and gets JSON +
  409 instead, while a normal browser submit keeps the redirect flow.

Also pinned: an EXISTING offer is never behind the musterija gate (its
header stays editable when the row has no directory link, contact_id NULL).
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.db import get_db

BASE_FORM = {
    "action": "update_header",
    "offer_number": "NAME-1",
    "date": "2026-11-04",
    "client_name": "Ime Kupca d.o.o.",
    "client_address": "Ulica 1",
    "client_email": "kupac@example.com",
    "client_phone": "060/111-222",
    "client_pib": "100000001",
    "client_mb": "20000001",
    "country": "Srbija",
    "currency": "EUR",
    "exchange_rate": "117.2",
    "discount_percent": "0",
    "special_discount_percent": "0",
    "third_discount_percent": "0",
    "vat_percent": "20",
    "payment_terms": "",
    "delivery_terms": "",
    "validity_days": "10",
    "notes": "",
    "napomena": "",
    "is_template": "",
}


@pytest.fixture(autouse=True)
def _clean():
    conn = get_db()
    conn.execute("DELETE FROM offer_items")
    conn.execute("DELETE FROM offers")
    conn.execute("DELETE FROM global_settings WHERE key = 'req_client_email'")
    conn.commit()
    try:
        yield
    finally:
        conn.execute("DELETE FROM offer_items")
        conn.execute("DELETE FROM offers")
        conn.execute("DELETE FROM global_settings WHERE key = 'req_client_email'")
        conn.commit()
        conn.close()


def _post(client, path, data=None, ajax=False):
    data = dict(data or {})
    data.setdefault("_csrf_token", csrf_token_for(client))
    headers = {"X-Requested-With": "XMLHttpRequest"} if ajax else {}
    return client.post(path, data=data, headers=headers)


def _create(client, name="NAME-1", **overrides):
    """POST /offer/offers/new and return the new offer id."""
    data = dict(BASE_FORM, offer_number=name)
    data.update(overrides)
    response = _post(client, "/offer/offers/new", data)
    assert response.status_code == 302, response.data[:300]
    return int(response.headers["Location"].split("/offers/")[1].split("/")[0])


def _insert_offer(name="LEGACY-1", contact_id=None):
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO offers (offer_number, date, client_name, contact_id)
           VALUES (?, '2026-11-01', 'Legacy d.o.o.', ?);""",
        (name, contact_id),
    )
    conn.commit()
    offer_id = cur.lastrowid
    conn.close()
    return offer_id


def _name(offer_id):
    conn = get_db()
    row = conn.execute(
        "SELECT offer_number FROM offers WHERE id = ?;", (offer_id,)
    ).fetchone()
    conn.close()
    return row["offer_number"]


def _count_offers():
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM offers;").fetchone()[0]
    conn.close()
    return total


# ---------------------------------------------------------------------------
# new offer: duplicate name must explain itself, not 500
# ---------------------------------------------------------------------------

def test_new_offer_duplicate_name_renders_error_and_keeps_values():
    client = login_client(app.test_client(), "offer")
    _create(client, "NAME-1")

    response = _post(client, "/offer/offers/new", dict(
        BASE_FORM, offer_number="NAME-1", client_name="Drugi Kupac d.o.o."))

    assert response.status_code == 200  # used to be 500 (UnboundLocalError)
    body = response.data.decode()
    assert "Offer name already exists" in body
    assert "Internal Server Error" not in body
    assert _count_offers() == 1  # nothing was created
    # typed values survive the re-render
    assert 'value="NAME-1"' in body
    assert "Drugi Kupac d.o.o." in body


def test_new_offer_duplicate_name_keeps_the_picked_party():
    """The re-render must not reset the musterija picker: the gate would
    close (js) and the customer fields would hide again."""
    from qp_crm.services import contact_service

    ok, cid = contact_service.create_contact(
        "Ponovna Musterija d.o.o.", kind="company", roles=["client"],
        fields={"pib": "100003333"})
    assert ok
    client = login_client(app.test_client(), "offer")

    response = _post(client, "/offer/offers/new", dict(
        BASE_FORM, offer_number="NAME-2", contact_id=str(cid)))
    assert response.status_code == 302

    response = _post(client, "/offer/offers/new", dict(
        BASE_FORM, offer_number="NAME-2", contact_id=str(cid)))
    assert response.status_code == 200
    body = response.data.decode()
    assert "Offer name already exists" in body
    assert f'value="{cid}" selected' in body


def test_new_offer_mandatory_field_error_renders_instead_of_500():
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO global_settings (key, value) "
        "VALUES ('req_client_email', 'true')")
    conn.commit()
    conn.close()

    client = login_client(app.test_client(), "offer")
    data = dict(BASE_FORM, client_email="")
    response = _post(client, "/offer/offers/new", data)

    assert response.status_code == 200  # used to be 500 (UndefinedError: id)
    assert b"Email is required." in response.data
    assert _count_offers() == 0


def test_new_offer_requires_an_offer_name():
    client = login_client(app.test_client(), "offer")
    response = _post(client, "/offer/offers/new", dict(BASE_FORM, offer_number="  "))

    assert response.status_code == 200
    assert b"Offer name is required." in response.data
    assert _count_offers() == 0


# ---------------------------------------------------------------------------
# edit offer: normal submit keeps the redirect flow, name never blank
# ---------------------------------------------------------------------------

def test_edit_offer_saves_the_name():
    client = login_client(app.test_client(), "offer")
    offer_id = _insert_offer("LEGACY-1")

    response = _post(client, f"/offer/offers/{offer_id}/edit",
                     dict(BASE_FORM, offer_number="PREIMENOVANO"))
    assert response.status_code == 302
    assert _name(offer_id) == "PREIMENOVANO"


def test_edit_offer_rejects_blank_name():
    client = login_client(app.test_client(), "offer")
    offer_id = _insert_offer("LEGACY-1")

    response = _post(client, f"/offer/offers/{offer_id}/edit",
                     dict(BASE_FORM, offer_number="   "))
    assert response.status_code == 302  # normal submit -> session message
    assert _name(offer_id) == "LEGACY-1"  # blank never written


# ---------------------------------------------------------------------------
# background header save (fetch): JSON success / visible rejection
# ---------------------------------------------------------------------------

def test_ajax_header_save_returns_json_and_saves():
    client = login_client(app.test_client(), "offer")
    offer_id = _insert_offer("LEGACY-1")

    response = _post(client, f"/offer/offers/{offer_id}/edit",
                     dict(BASE_FORM, offer_number="AJAX-IME"), ajax=True)
    assert response.status_code == 200
    assert response.get_json() == {"ok": True}
    assert _name(offer_id) == "AJAX-IME"


def test_ajax_header_save_duplicate_name_returns_409_not_silent_success():
    client = login_client(app.test_client(), "offer")
    _create(client, "NAME-1")
    offer_id = _create(client, "NAME-2")

    response = _post(client, f"/offer/offers/{offer_id}/edit",
                     dict(BASE_FORM, offer_number="NAME-1"), ajax=True)

    assert response.status_code == 409  # NOT a followed redirect -> 200
    payload = response.get_json()
    assert payload["ok"] is False
    assert "already exists" in payload["error"]
    assert _name(offer_id) == "NAME-2"  # name unchanged, and the JS sees why


def test_ajax_header_save_blank_name_returns_409():
    client = login_client(app.test_client(), "offer")
    offer_id = _insert_offer("LEGACY-1")

    response = _post(client, f"/offer/offers/{offer_id}/edit",
                     dict(BASE_FORM, offer_number=""), ajax=True)

    assert response.status_code == 409
    assert response.get_json()["ok"] is False
    assert _name(offer_id) == "LEGACY-1"


# ---------------------------------------------------------------------------
# musterija gate: new-offer wizard only, never on an existing offer
# ---------------------------------------------------------------------------

def test_new_offer_form_is_gated_but_existing_offer_is_not():
    client = login_client(app.test_client(), "offer")
    new_form = client.get("/offer/offers/new")
    assert b'data-existing-offer="0"' in new_form.data

    # contact_id NULL = legacy free-typed offer: the header (offer name
    # included) must stay editable instead of pointer-events:none.
    legacy_id = _insert_offer("LEGACY-1", contact_id=None)
    edit_form = client.get(f"/offer/offers/{legacy_id}/edit")
    assert b'data-existing-offer="1"' in edit_form.data
    assert b'name="offer_number"' in edit_form.data


def test_header_save_then_add_item_keeps_the_new_name():
    """The exact user sequence: rename the offer, then click "Dodaj u
    ponudu" (the JS saves the header quietly, then submits the item form).
    Before the fix a rejected save left the OLD name behind while the item
    was added anyway."""
    client = login_client(app.test_client(), "offer")
    offer_id = _insert_offer("LEGACY-1")

    saved = _post(client, f"/offer/offers/{offer_id}/edit",
                  dict(BASE_FORM, offer_number="POSLE-DODAVANJA"), ajax=True)
    assert saved.status_code == 200 and saved.get_json() == {"ok": True}

    added = _post(client, f"/offer/offers/{offer_id}/edit", {
        "action": "add_item",
        "product_id": "",
        "item_name": "Rucna stavka",
        "item_description": "",
        "quantity": "1",
        "unit_price": "100",
    })
    assert added.status_code == 302

    assert _name(offer_id) == "POSLE-DODAVANJA"
    conn = get_db()
    items = conn.execute(
        "SELECT COUNT(*) FROM offer_items WHERE offer_id = ?;", (offer_id,)
    ).fetchone()[0]
    conn.close()
    assert items == 1
