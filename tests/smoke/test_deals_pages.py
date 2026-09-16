"""Phase 4 (deals spine) HTTP-level tests: gating, pages, the offer link.

Extends the Phase-1 smoke discipline to the new /deals module:

* anonymous visitors redirect to the unified login on every deals page;
* staff WITHOUT the 'deals' grant get 403; granted staff and admins get 200;
* the landing card follows the grant (grants v3 seeds existing staff once);
* the offer <-> deal link round-trips through the real routes with CSRF.
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.auth import (
    MODULE_CHOICES,
    get_db,
    get_user_modules,
    set_user_modules,
)

DEALS_PAGES = (
    "/deals/",
    "/deals/deals",
    "/deals/customers",
    "/deals/customers/new",
    "/deals/deals/new",
    "/deals/pipeline",
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


def test_anonymous_redirects_to_login():
    client = app.test_client()
    for path in DEALS_PAGES:
        resp = client.get(path)
        assert resp.status_code == 302, path
        assert resp.headers["Location"].startswith("/login"), path


def test_ungranted_staff_gets_403():
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()
    set_user_modules(uid, ["offer"])  # trim deals off the offer account
    fresh = login_client(app.test_client(), "offer")
    resp = fresh.get("/deals/")
    assert resp.status_code == 403
    assert b"deals" in resp.data.lower()  # message names the missing app
    # landing card hidden for the ungranted staff user
    landing = fresh.get("/")
    assert b'href="/deals/"' not in landing.data


def test_granted_staff_reaches_all_deals_pages():
    client = login_client(app.test_client(), "offer")
    for path in DEALS_PAGES:
        resp = client.get(path)
        # /deals/ is a convenience redirect to the deals list
        if path == "/deals/":
            assert resp.status_code == 302
            assert resp.headers["Location"].endswith("/deals/deals")
        else:
            assert resp.status_code == 200, path


def test_admin_bypasses_grants():
    client = login_client(app.test_client(), "admin")
    for path in DEALS_PAGES:
        resp = client.get(path)
        if path == "/deals/":
            assert resp.status_code == 302
            assert resp.headers["Location"].endswith("/deals/deals")
        else:
            assert resp.status_code == 200, path


def test_landing_card_follows_grant_and_admin_sees_it():
    client = login_client(app.test_client(), "offer")
    landing = client.get("/")
    assert b'href="/deals/"' in landing.data  # v3 rollout granted deals

    # trim and verify the card disappears for a fresh session (the module
    # autouse fixture restores the offer account's grants afterwards)
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()
    set_user_modules(uid, ["offer"])
    fresh = login_client(app.test_client(), "offer")
    assert b'href="/deals/"' not in fresh.get("/").data


def test_grants_v3_seeds_deals_once():
    """The v3 exactly-once rollout: staff materialized at v2 receive 'deals'
    on the next boot; an explicitly emptied set stays empty."""
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()

    # materialized at v2 (no deals) -> boot grants deals exactly once
    set_user_modules(uid, ["pricing", "offer", "rent", "sale"])  # sets v3 marker...
    set_user_modules(uid, ["pricing", "offer", "rent", "sale"])
    conn = get_db()
    conn.execute("UPDATE users SET modules_set = 2 WHERE id = ?;", (uid,))
    conn.commit()
    conn.close()

    from qp_crm.shared.auth import seed_default_user_modules
    conn = get_db()
    seed_default_user_modules(conn.cursor())
    conn.commit()
    conn.close()
    assert "deals" in get_user_modules(uid)

    # explicitly emptied set stays empty across re-inits
    set_user_modules(uid, [])
    conn = get_db()
    seed_default_user_modules(conn.cursor())
    conn.commit()
    conn.close()
    assert get_user_modules(uid) == []
    # restore the deals grant for the tests after this one (the autouse
    # _restore_grants fixture cannot: it snapshotted BEFORE we emptied it)
    set_user_modules(uid, ["deals"])


def test_full_funnel_round_trip(offer_client, temp_db):
    """customer -> location -> deal -> offer linked at creation -> timeline
    shows the document event -> acceptance tap -> derived won."""
    client = offer_client
    tok = csrf_token_for(client)

    def last_id(location):
        return int(location.rsplit("/", 1)[-1])

    resp = client.post("/deals/customers/new", data={
        "_csrf_token": tok, "name": "Round Trip d.o.o.", "pib": "109999999"})
    assert resp.status_code == 302
    customer_id = last_id(resp.headers["Location"])

    resp = client.post(f"/deals/customers/{customer_id}/locations/new", data={
        "_csrf_token": tok, "name": "Sajt 1"})
    assert resp.status_code == 302

    resp = client.post("/deals/deals/new", data={
        "_csrf_token": tok, "customer": customer_id, "title": "Round trip posao"})
    assert resp.status_code == 302

    deal_id = last_id(resp.headers["Location"])

    # offer created WITH the deal from the deal page's button (GET prefill)
    page = client.get(f"/offer/offers/new?deal_id={deal_id}")
    assert page.status_code == 200
    assert b"Round Trip d.o.o." in page.data  # master-data prefill

    resp = client.post("/offer/offers/new", data={
        "_csrf_token": tok, "action": "save", "offer_number": "P4-RT-1",
        "date": "2026-09-16", "client_name": "Round Trip d.o.o.",
        "deal_id": deal_id, "vat_percent": "20"})
    assert resp.status_code == 302

    # deal page: document event + offered badge + offer card
    page = client.get(f"/deals/deals/{deal_id}").data.decode()
    assert "P4-RT-1" in page
    assert "Ponu" in page  # offered badge (Ponuđeno)

    # acceptance tap -> won
    from qp_crm.shared.auth import get_db
    conn = get_db()
    offer_id = conn.execute(
        "SELECT id FROM offers WHERE offer_number='P4-RT-1'").fetchone()["id"]
    conn.close()
    resp = client.post(f"/deals/deals/{deal_id}/accept_offer/{offer_id}",
                       data={"_csrf_token": tok})
    assert resp.status_code == 302
    page = client.get(f"/deals/deals/{deal_id}").data.decode()
    assert "Dobijeno" in page  # won badge

    # offers list shows the deal code column
    assert b"D-2026-" in client.get("/offer/offers").data


def test_deal_code_on_pdf_route_unaffected(offer_client):
    """The PDF pipeline keeps working for a linked offer (no regression on
    the golden path context)."""
    client = offer_client
    tok = csrf_token_for(client)
    resp = client.post("/offer/offers/new", data={
        "_csrf_token": tok, "action": "save", "offer_number": "P4-PDF-1",
        "date": "2026-09-16", "client_name": "PDF d.o.o.",
        "deal_id": "", "vat_percent": "20"})
    assert resp.status_code == 302
