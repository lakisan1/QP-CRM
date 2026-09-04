"""Phase 3 step 9: end-to-end first-login + rehash flows over HTTP.

The service-level pieces are pinned elsewhere (test_users_seed: flag at
seed time; test_password_hashing: transparent rehash). These two tests pin
the FULL HTTP flow through the unified login:

* a seeded staff account with must_change_password=1 is redirected to
  /change-password on EVERY page until the change completes, then works
  normally and the flag is gone;
* logging in with the legacy plaintext password transparently rehashes the
  row (the stored hash changes; a second login still works).
"""

import pytest

from conftest import csrf_token_for
from qp_crm.main import app
from qp_crm.shared.auth import DEFAULT_PASSWORDS, _is_werkzeug_hash, get_db


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


def _flag(username):
    conn = get_db()
    row = conn.execute("SELECT must_change_password, password_hash FROM users WHERE username = ?;",
                       (username,)).fetchone()
    conn.close()
    return row


def _set_flag(username, value):
    conn = get_db()
    conn.execute("UPDATE users SET must_change_password = ? WHERE username = ?;", (value, username))
    conn.commit()
    conn.close()


def _login(client, username, password):
    client.get("/login")
    return client.post("/login", data={
        "username": username,
        "password": password,
        "_csrf_token": csrf_token_for(client),
    })


def test_seeded_first_login_forced_change_end_to_end():
    _set_flag("offer", 1)
    client = app.test_client()

    resp = _login(client, "offer", DEFAULT_PASSWORDS["offer"])
    assert resp.status_code == 302
    assert "/change-password" in resp.headers["Location"]

    # every business page is blocked until the change completes
    resp = client.get("/pricing/products", follow_redirects=False)
    assert resp.status_code == 302 and "/change-password" in resp.headers["Location"]

    # complete the change (current == seeded default)
    client.get("/change-password")
    resp = client.post("/change-password", data={
        "current_password": DEFAULT_PASSWORDS["offer"],
        "new_password": "Offer-First-Login-1",
        "confirm_password": "Offer-First-Login-1",
        "_csrf_token": csrf_token_for(client),
    })
    assert resp.status_code == 302

    # flag cleared in DB and the user can work now
    assert _flag("offer")["must_change_password"] == 0
    assert client.get("/offer/offers", follow_redirects=True).status_code == 200

    # restore canonical state for the rest of the suite
    from qp_crm.shared.auth import set_password
    set_password("offer", DEFAULT_PASSWORDS["offer"])
    _set_flag("offer", 0)


def test_login_route_triggers_transparent_rehash():
    row = _flag("rent")
    assert _is_werkzeug_hash(row["password_hash"])  # canonical state: already hashed

    # force a legacy-plaintext hash as a pre-Phase-3 restore would leave it
    legacy_password = "Rent-Legacy-Plain-1"
    conn = get_db()
    conn.execute("UPDATE users SET password_hash = ? WHERE username = 'rent';", (legacy_password,))
    conn.commit()
    conn.close()
    assert not _is_werkzeug_hash(_flag("rent")["password_hash"])

    # login THROUGH the route works with the plaintext...
    client = app.test_client()
    resp = _login(client, "rent", legacy_password)
    assert resp.status_code == 302
    assert client.get("/rent/contracts", follow_redirects=True).status_code == 200

    # ...and the row now carries a werkzeug hash (transparent rehash)
    assert _is_werkzeug_hash(_flag("rent")["password_hash"])
    assert _flag("rent")["password_hash"] != legacy_password

    # the plaintext no longer matches anything in storage; a NEW login with
    # the same password still works (hash verifies)
    client2 = app.test_client()
    assert _login(client2, "rent", legacy_password).status_code == 302

    # restore the canonical seeded password hash + flag
    from qp_crm.shared.auth import set_password
    set_password("rent", DEFAULT_PASSWORDS["rent"])
    _set_flag("rent", 0)
