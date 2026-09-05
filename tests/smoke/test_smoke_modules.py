"""P1-T7 smoke tests, updated for Phase 3 unified auth (step 3).

These run against qp_crm.main.application -- the single Flask app exactly as
gunicorn serves it -- with the throwaway fixture DB from conftest (fresh
schemas, seeded defaults, the four legacy accounts migrated into the users
table with DEFAULT_PASSWORDS as their initial passwords).

Pinned behavior after Phase 3 step 3:
* ONE unified login at /login (+ /logout); the per-app login/logout URLs
  (/pricing/login, /offer/login, ...) remain alive as REDIRECTS so old
  bookmarks keep working;
* pricing/offer/rent/admin gate every page behind the unified login;
* sale and settings stay public (role gates land in step 4);
* a wrong password re-renders the login page (200) and stays locked out.
"""

import pytest
from werkzeug.test import Client

import qp_crm.main
from conftest import login_client
from qp_crm.shared.auth import DEFAULT_PASSWORDS

GATED_MODULES = ("pricing", "offer", "rent", "admin")  # modules with a same-name user account
GATED_ANON_MODULES = ("pricing", "offer", "rent", "sale", "admin")  # login-redirect coverage only


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    """Guarantee the init sequence ran, even in a smoke-only run.

    Without this, DB-touching pages 500 on the empty schema (discovered the
    hard way: sale.list_sale SELECTs global_settings unguarded). The full
    suite masks it because characterization tests trigger temp_db first.
    """
    yield


def fresh_client():
    """A clean cookie jar -- no session.

    Flask's test client (itself a werkzeug Client) over the same application
    gunicorn serves; since Phase 2 removed DispatcherMiddleware the app is a
    plain Flask instance, so session_transaction() works for the unified
    login flow (the raw Client from Phase 1 could not provide it).
    """
    return qp_crm.main.app.test_client()


def test_landing_redirects_anonymous_to_login():
    # Anonymous visitors see ONLY the login page (never the app menu).
    response = fresh_client().get("/")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_landing_shows_only_accessible_apps():
    from conftest import csrf_token_for, login_client

    # staff with all grants: three business cards + public cards, no admin
    client = fresh_client()
    login_client(client, "pricing")
    page = client.get("/").data.decode()
    for link in ("/pricing/", "/offer/", "/rent/", "/sale/pricelist", "/settings/"):
        assert link in page, link
    assert "/admin/" not in page

    # trim grants to pricing-only: menu follows instantly
    from qp_crm.shared.auth import get_db, set_user_modules
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='pricing'").fetchone()["id"]
    conn.close()
    set_user_modules(uid, ["pricing"])
    # re-login on a fresh client to prove it works for a new session too
    client2 = fresh_client()
    login_client(client2, "pricing")
    page = client2.get("/").data.decode()
    assert "/pricing/" in page
    assert "/offer/" not in page and "/rent/" not in page
    assert "/sale/pricelist" not in page  # v2: sale is grantable per user too
    assert "/admin/" not in page

    # restore for the rest of the suite
    from qp_crm.shared.auth import MODULE_CHOICES
    set_user_modules(uid, list(MODULE_CHOICES))

    # admin sees everything including the Admin Panel card
    admin_client = fresh_client()
    login_client(admin_client, "admin")
    admin_page = admin_client.get("/").data.decode()
    for link in ("/pricing/", "/offer/", "/rent/", "/sale/pricelist", "/admin/"):
        assert link in admin_page, link


def test_unified_login_page_renders():
    assert fresh_client().get("/login").status_code == 200


@pytest.mark.parametrize("module", GATED_ANON_MODULES)
def test_gated_module_redirects_to_unified_login(module):
    response = fresh_client().get(f"/{module}/")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


@pytest.mark.parametrize("module", GATED_ANON_MODULES)
def test_old_login_url_redirects_to_unified_login(module):
    # Old bookmarks: /<module>/login (GET) now redirects to /login.
    response = fresh_client().get(f"/{module}/login")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


GATED_PAGES = {
    "pricing": "/pricing/products",
    "offer": "/offer/offers",
    "rent": "/rent/contracts",
    "admin": "/admin/",
}


@pytest.mark.parametrize("module", GATED_MODULES)
def test_old_logout_url_clears_session(module):
    client = login_client(fresh_client(), module)
    # logged in: an auth-required page is reachable
    assert client.get(GATED_PAGES[module]).status_code == 200
    # old logout URL routes through the unified logout; follow the redirect
    # chain to the end (the session is cleared at /logout itself)
    resp = client.get(f"/{module}/logout", follow_redirects=True)
    assert resp.status_code == 200  # ends on the unified login page
    assert client.get(GATED_PAGES[module]).status_code == 302  # locked again


def _session_token(client):
    with client.session_transaction() as session:
        return session.get("_csrf_token")


def test_wrong_password_stays_locked_out():
    client = fresh_client()
    client.get("/login")                     # establish the session CSRF token
    token = _session_token(client)
    response = client.post(
        "/login",
        data={"username": "admin", "password": "definitely-wrong-42",
              "_csrf_token": token},
    )
    assert response.status_code == 200                   # login page re-rendered
    assert client.get("/admin/").status_code == 302      # still locked out


def test_unknown_username_stays_locked_out():
    client = fresh_client()
    client.get("/login")
    token = _session_token(client)
    response = client.post(
        "/login",
        data={"username": "no-such-user", "password": "whatever-1",
              "_csrf_token": token},
    )
    assert response.status_code == 200
    assert client.get("/pricing/").status_code == 302


@pytest.mark.parametrize("module", GATED_MODULES)
def test_login_reaches_main_page(module):
    # Unified login POST followed through the redirect lands on a 200.
    client = login_client(fresh_client(), module)
    response = client.get(f"/{module}/", follow_redirects=True)
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/pricing/products", "/offer/offers", "/rent/contracts", "/admin/"])
def test_main_pages_200_after_unified_login(path):
    module = path.split("/")[1]
    client = login_client(fresh_client(), module)
    assert client.get(path).status_code == 200


def test_sale_redirects_to_pricelist_when_logged_in():
    # /sale/ is still a plain redirect to the pricelist, but the pricelist
    # itself is per-user gated now (v2 module rollout).
    client = login_client(fresh_client(), "pricing")
    root = client.get("/sale/")
    assert root.status_code == 302
    assert root.headers["Location"].endswith("/sale/pricelist")
    assert client.get("/sale/pricelist").status_code == 200


def test_settings_needs_no_login():
    assert fresh_client().get("/settings/").status_code == 200


def test_unknown_module_prefix_404s():
    assert fresh_client().get("/nope/").status_code == 404
