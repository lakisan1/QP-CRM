"""First-login + transparent-rehash flows over HTTP.

The forced /change-password detour is REMOVED (user request: password
changes live exclusively in Admin -> Users, where the admin sets a working
password directly). These tests pin the new contract:

* a seeded staff account logs in and lands straight on the app -- no
  redirect to a change page, and the page itself is gone (404);
* logging in with the legacy plaintext password transparently rehashes the
  row (the stored hash changes; a second login still works).
"""

import secrets

import pytest

from conftest import csrf_token_for
from qp_crm.main import app
from qp_crm.shared.auth import DEFAULT_PASSWORDS, _is_werkzeug_hash, get_db


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


def _row(username):
    conn = get_db()
    row = conn.execute("SELECT must_change_password, password_hash FROM users WHERE username = ?;",
                       (username,)).fetchone()
    conn.close()
    return row


def _login(client, username, password):
    client.get("/login")
    return client.post("/login", data={
        "username": username,
        "password": password,
        "_csrf_token": csrf_token_for(client),
    })


def test_seeded_staff_logs_straight_in_no_forced_change():
    client = app.test_client()
    resp = _login(client, "offer", DEFAULT_PASSWORDS["offer"])
    assert resp.status_code == 302
    assert "change-password" not in resp.headers["Location"]

    # the app is immediately reachable, no detour
    assert client.get("/offer/offers", follow_redirects=True).status_code == 200

    # the self-service page is gone entirely: GET 404s, and even a POST
    # cannot reach anything -- a tokenless one meets the app-level CSRF
    # shield first (400 before routing could ever 404), a properly tokened
    # one proves the route itself no longer exists (404). The token must be
    # minted explicitly: the login handler's session.clear() wiped the one
    # from the login-page render and no page render happens in between.
    assert client.get("/change-password").status_code == 404
    resp = client.post("/change-password", data={"current_password": "x"})
    assert resp.status_code == 400  # CSRF shield answers before routing
    with client.session_transaction() as session:
        session["_csrf_token"] = secrets.token_hex(16)
    resp = client.post("/change-password", data={
        "current_password": "x", "_csrf_token": csrf_token_for(client),
    })
    assert resp.status_code == 404


def test_login_route_triggers_transparent_rehash():
    row = _row("rent")
    assert _is_werkzeug_hash(row["password_hash"])  # canonical state: already hashed

    # force a legacy-plaintext hash as a pre-Phase-3 restore would leave it
    legacy_password = "Rent-Legacy-Plain-1"
    conn = get_db()
    conn.execute("UPDATE users SET password_hash = ? WHERE username = 'rent';", (legacy_password,))
    conn.commit()
    conn.close()
    assert not _is_werkzeug_hash(_row("rent")["password_hash"])

    # login THROUGH the route works with the plaintext...
    client = app.test_client()
    resp = _login(client, "rent", legacy_password)
    assert resp.status_code == 302
    assert client.get("/rent/contracts", follow_redirects=True).status_code == 200

    # ...and the row now carries a werkzeug hash (transparent rehash)
    assert _is_werkzeug_hash(_row("rent")["password_hash"])
    assert _row("rent")["password_hash"] != legacy_password

    # the plaintext no longer matches anything in storage; a NEW login with
    # the same password still works (hash verifies)
    client2 = app.test_client()
    assert _login(client2, "rent", legacy_password).status_code == 302

    # restore the canonical seeded password hash
    from qp_crm.shared.auth import set_password
    set_password("rent", DEFAULT_PASSWORDS["rent"])
