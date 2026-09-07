"""Theme-consistency smoke tests (theme audit card).

The per-browser 'theme' cookie is the single theme store: /settings POST
sets it (1 year, path=/), shared/web.get_theme() reads it with a 'dark'
fallback, and -- after the audit fix -- ONE app-level context processor in
qp_crm/main.py injects it into every rendered screen, so every page follows
the same cookie. Pinned here:

* POST /settings/ (theme=light) sets the 1-year 'theme' cookie;
* the logged-in landing page renders data-theme="light" with the light
  cookie and the dark fallback without one;
* /offer/offers follows the cookie too (offer previously had no context
  processor of its own, so its screens were stuck on the dark fallback);
* the pre-login /login page follows the cookie (no session needed -- the
  cookie is read straight from the request);
* the admin dashboard follows the cookie -- NOT the legacy
  global_settings.theme row, which used to be its only source.
"""

import pytest

import qp_crm.main
from conftest import csrf_token_for, login_client


@pytest.fixture(scope="module", autouse=True)
def _db_ready(temp_db):
    """Guarantee the init sequence ran, even in a theme-only run."""
    yield


def fresh_client():
    """A clean cookie jar -- no session (same helper as the other smokes)."""
    return qp_crm.main.app.test_client()


def test_settings_post_sets_theme_cookie():
    client = fresh_client()
    client.get("/settings/")  # public page; mints the session CSRF token
    token = csrf_token_for(client)
    resp = client.post("/settings/", data={"theme": "light", "_csrf_token": token})
    assert resp.status_code == 302  # saved, redirected to the landing page
    assert "theme=light" in resp.headers.get("Set-Cookie", "")
    assert "Max-Age=31536000" in resp.headers.get("Set-Cookie", "")


def test_landing_follows_theme_cookie():
    # no cookie -> dark fallback (the audit-fix default stays dark)
    client = fresh_client()
    login_client(client, "pricing")
    html = client.get("/").data.decode()
    assert 'data-theme="dark"' in html
    assert 'data-theme="light"' not in html

    # light cookie -> light on the same page
    client2 = fresh_client()
    client2.set_cookie("theme", "light")
    login_client(client2, "pricing")
    html2 = client2.get("/").data.decode()
    assert 'data-theme="light"' in html2
    assert 'data-theme="dark"' not in html2


def test_offer_screens_follow_theme_cookie():
    client = fresh_client()
    login_client(client, "offer")
    html = client.get("/offer/offers").data.decode()
    assert 'data-theme="dark"' in html
    assert 'data-theme="light"' not in html

    client2 = fresh_client()
    client2.set_cookie("theme", "light")
    login_client(client2, "offer")
    html2 = client2.get("/offer/offers").data.decode()
    assert 'data-theme="light"' in html2
    assert 'data-theme="dark"' not in html2


def test_login_page_follows_theme_cookie_before_login():
    # Pre-auth: no session exists yet, but the browser cookie is still sent
    # and read -- the login screen must match the user's chosen theme.
    client = fresh_client()
    assert 'data-theme="dark"' in client.get("/login").data.decode()
    client.set_cookie("theme", "light")
    assert 'data-theme="light"' in client.get("/login").data.decode()


def test_admin_dashboard_follows_cookie_not_db_theme_row():
    # Pin that the dashboard renders the COOKIE: even with a stale
    # global_settings.theme='light' row, no cookie still means dark.
    from qp_crm.shared.auth import get_db

    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO global_settings (key, value)"
                 " VALUES ('theme', 'light');")
    conn.commit()
    conn.close()
    try:
        client = fresh_client()
        login_client(client, "admin")
        html = client.get("/admin/").data.decode()
        assert 'data-theme="dark"' in html, "dashboard must ignore the DB theme row"

        client2 = fresh_client()
        client2.set_cookie("theme", "light")
        login_client(client2, "admin")
        html2 = client2.get("/admin/").data.decode()
        assert 'data-theme="light"' in html2
    finally:
        conn = get_db()
        conn.execute("DELETE FROM global_settings WHERE key = 'theme';")
        conn.commit()
        conn.close()
