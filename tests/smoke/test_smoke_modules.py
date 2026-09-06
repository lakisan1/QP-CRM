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


# ─── header / admin-nav consistency (post-Phase-3 UI cleanup) ────────────────
# Board cards: admin header drift (Users/API Keys/Rent Šabloni missing on
# admin subpages), /admin/rent/templates login loop, logout moved to the
# settings app, "Landing Page" renamed "Home".

ADMIN_SUBPAGES = (
    "/admin/",
    "/admin/pdf_templates",
    "/admin/rounding_rules",
    "/admin/users",
    "/admin/api_keys",
    "/admin/rent/templates",
)


@pytest.mark.parametrize("path", ("/admin/rent/templates",
                                  "/admin/backup_db",
                                  "/admin/backup_full"))
def test_admin_gated_routes_reachable_after_login(admin_client, path):
    """Regression: these routes still carried per-route checks of the
    pre-Phase-3 admin_authenticated session flag (never set since unified
    login), so a LOGGED-IN admin got an endless /login?next=/admin/ loop.
    The blueprint-level require_role("admin") hook is the only gate now."""
    resp = admin_client.get(path)
    assert resp.status_code == 200, \
        f"{path} -> {resp.status_code} {resp.headers.get('Location')}"


@pytest.mark.parametrize("path", ADMIN_SUBPAGES)
def test_admin_pages_share_one_full_header(admin_client, path):
    """Every admin page renders the SAME nav: all six links + Home, and no
    logout button (logout lives in the settings app now)."""
    page = admin_client.get(path)
    assert page.status_code == 200, path
    html = page.data.decode()
    for link in ("/admin/", "/admin/pdf_templates", "/admin/rounding_rules",
                 "/admin/users", "/admin/api_keys", "/admin/rent/templates"):
        assert link in html, f"{path}: missing nav link {link}"
    assert ">Home</a>" in html, f"{path}: missing Home link"
    assert "Logout" not in html, f"{path}: header logout button is gone"


def test_pdf_template_editor_shares_admin_header(admin_client, conn_factory):
    """The PDF template edit page keeps the full admin nav (plus its
    'Edit: <name>' breadcrumb) instead of the old trimmed copy-pasted one."""
    with conn_factory() as conn:
        row = conn.execute("SELECT MIN(id) AS id FROM pdf_templates").fetchone()
    page = admin_client.get(f"/admin/edit_pdf_template/{row['id']}")
    assert page.status_code == 200
    html = page.data.decode()
    assert "/admin/users" in html and "/admin/api_keys" in html
    assert "Edit: " in html


def test_settings_app_carries_logout_and_home():
    """/settings now hosts the logout button (moved out of the page headers)
    next to the renamed Home link."""
    html = fresh_client().get("/settings/").data.decode()
    assert 'href="/logout"' in html
    assert ">Home</a>" in html


@pytest.mark.parametrize("path", ("/pricing/products", "/offer/offers",
                                  "/rent/contracts", "/sale/pricelist"))
def test_business_headers_have_no_logout_and_say_home(admin_client, path):
    """The logout button is gone from every app header (settings app hosts
    it now), and every banner renders the SHARED green Home pill from
    templates/nav_home.html (rent included — no more local 'Početna')."""
    page = admin_client.get(path)  # admin opens every app
    assert page.status_code == 200, path
    html = page.data.decode()
    assert "btn btn-danger" not in html.split("<hr>")[0], \
        f"{path}: header still carries a danger button (logout)"
    assert ("Landing Page" not in html), f"{path}: header still says 'Landing Page'"
    assert 'class="nav-btn-home"' in html, f"{path}: header Home link is not the shared green pill"


def test_every_banner_uses_the_shared_home_include(admin_client):
    """One source for the Home pill: all four business banners + settings
    render the include, so the label ('Home'/'Početna strana') and the
    green style can never drift apart again."""
    for path in ("/pricing/products", "/offer/offers", "/rent/contracts",
                 "/sale/pricelist", "/settings/"):
        html = admin_client.get(path).data.decode()
        assert 'class="nav-btn-home"' in html, f"{path}: missing shared Home pill"

# ─── i18n / a11y debt pass pins ────────────────────────────────────────────────
# Board card: hardcoded Serbian UI strings should render through the _()
# mechanism (both languages covered, sr wording unchanged) and form controls on
# the main flows should carry labels/aria. These run under the default test
# language (no global_settings.language row -> 'en'), plus one sr-mode check.


def test_login_form_controls_have_labels_and_ids():
    html = fresh_client().get("/login").data.decode()
    for pair in (('label for="username"', 'id="username"'),
                 ('label for="password"', 'id="password"')):
        for needle in pair:
            assert needle in html, f"/login: missing {needle}"


def test_pricing_products_search_has_aria_label_and_header_scope():
    client = login_client(fresh_client(), "pricing")
    html = client.get("/pricing/products").data.decode()
    assert 'aria-label="Search by name"' in html
    assert '<th scope="col">' in html


def test_known_hardcoded_serbian_strings_gone_from_en_pages():
    """The moved strings render their EN source (sr wording is dictionary
    covered and stays Serbian); the old hardcoded literals must not leak."""
    client = login_client(fresh_client(), "pricing")
    html = client.get("/pricing/products").data.decode()
    assert "Sync Website" in html, "pricing nav: EN source missing"
    assert "Sync Sajt" not in html, "pricing nav: old literal still present"
    quick = client.get("/pricing/products/quick_update").data.decode()
    assert "Quick Price Update" in quick
    assert "Brzo Ažuriranje Cena" not in quick
    settings_html = fresh_client().get("/settings/").data.decode()
    # audit M4: the date-format control left /settings for the admin dashboard
    # (global_settings row is the single source of truth) -- pin that it is
    # gone here and that the theme control (the page's remaining setting)
    # still renders.
    assert "App theme" in settings_html
    assert 'name="date_format"' not in settings_html


def test_serbian_mode_renders_dictionary_translations():
    """With global_settings.language='sr' the same strings render the Serbian
    wording the app always showed (dictionary values), proving the sr side of
    the i18n pairs is covered."""
    from qp_crm.shared.auth import get_db

    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO global_settings (key, value)"
                 " VALUES ('language', 'sr');")
    conn.commit()
    conn.close()
    try:
        html = fresh_client().get("/login").data.decode()
        for needle in ("Korisničko ime", "Lozinka", "Jedinstvena prijava za sve module"):
            assert needle in html, f"/login (sr): missing {needle}"
        settings_html = fresh_client().get("/settings/").data.decode()
        # audit M4: date format moved to the admin dashboard, so the sr-mode
        # /settings page shows the theme controls and page chrome only.
        for needle in ("Tema aplikacije", "Podešavanja", "Odjavi se"):
            assert needle in settings_html, f"/settings (sr): missing {needle}"
        assert "Format datuma" not in settings_html, "M4: date-format control must not render on /settings"
    finally:
        conn = get_db()
        conn.execute("DELETE FROM global_settings WHERE key = 'language';")
        conn.commit()
        conn.close()
