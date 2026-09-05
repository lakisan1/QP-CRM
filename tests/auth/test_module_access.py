"""Per-user app access (post-Phase-3 user request).

Pinned behavior:

* one-time boot migration: every staff user without materialized grants
  gets ALL business modules (nobody loses access in the transition), and
  the users.modules_set marker makes it truly one-time;
* an explicitly EMPTIED grant set stays empty across re-inits;
* staff WITHOUT a module grant get 403 on that app but keep the others;
  admins bypass module gates entirely;
* Admin -> Users saves grants per user (own-password confirmed, CSRF);
  changes take effect on the user's next request;
* user creation accepts a module subset.
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.auth import (
    DEFAULT_PASSWORDS,
    MODULE_CHOICES,
    get_db,
    get_user_modules,
    set_user_modules,
)


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


def _uid(username):
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE username = ?;", (username,)).fetchone()
    conn.close()
    return row["id"]


def _set_flag(username, value):
    conn = get_db()
    conn.execute("UPDATE users SET must_change_password = ? WHERE username = ?;", (value, username))
    conn.commit()
    conn.close()


def _post(client, path, data):
    data["_csrf_token"] = csrf_token_for(client)
    return client.post(path, data=data)


@pytest.fixture(autouse=True)
def _restore_grants():
    """Every test leaves the seeded staff grants exactly as found."""
    snapshot = {u: get_user_modules(_uid(u)) for u in ("pricing", "offer", "rent")}
    yield
    for username, modules in snapshot.items():
        set_user_modules(_uid(username), modules)


def test_boot_migration_grants_all_modules_once():
    for username in ("pricing", "offer", "rent"):
        assert get_user_modules(_uid(username)) == sorted(MODULE_CHOICES)
    conn = get_db()
    marks = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role='staff' AND modules_set = 0;"
    ).fetchone()[0]
    conn.close()
    assert marks == 0  # all materialized


def test_explicitly_emptied_grants_survive_reinit():
    uid = _uid("offer")
    ok, _ = set_user_modules(uid, [])
    assert ok
    # simulate the next boot's admin.init_users_table
    from qp_crm.admin.app import init_users_table
    init_users_table()
    assert get_user_modules(uid) == []
    # restore for the rest of the suite
    set_user_modules(uid, sorted(MODULE_CHOICES))


def test_staff_without_module_gets_403_but_keeps_others():
    set_user_modules(_uid("offer"), ["pricing"])  # offer account: only pricing
    offer = login_client(app.test_client(), "offer")
    resp = offer.get("/offer/offers")
    assert resp.status_code == 403
    assert "offer" in resp.data.decode()  # message names the missing app
    assert offer.get("/pricing/products").status_code == 200


def test_admin_bypasses_module_gates():
    set_user_modules(_uid("admin"), [])  # admins need no grant rows
    admin = login_client(app.test_client(), "admin")
    for path in ("/pricing/products", "/offer/offers", "/rent/contracts"):
        assert admin.get(path).status_code == 200


def test_module_gate_redirects_anonymous_to_login():
    client = app.test_client()
    resp = client.get("/rent/contracts")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_ui_saves_module_grants_with_own_password():
    admin = login_client(app.test_client(), "admin")
    uid = _uid("rent")

    # wrong own password: grants unchanged
    resp = _post(admin, f"/admin/users/{uid}/save", {
        "modules": ["pricing"], "active": "1", "current_password": "WRONG-current-1",
    })
    assert resp.status_code == 302
    assert get_user_modules(uid) == sorted(MODULE_CHOICES)

    # correct password: grants saved, page shows the new checkbox state
    resp = _post(admin, f"/admin/users/{uid}/save", {
        "modules": ["pricing"], "active": "1", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    assert get_user_modules(uid) == ["pricing"]

    rent = login_client(app.test_client(), "rent")
    _set_flag("rent", 0)
    assert rent.get("/rent/contracts").status_code == 403
    assert rent.get("/pricing/products", follow_redirects=True).status_code == 200

    page = admin.get("/admin/users").data.decode()
    assert 'value="rent"' in page and 'value="pricing"' in page  # checkboxes render

    # re-grant everything for the rest of the suite
    resp = _post(admin, f"/admin/users/{uid}/save", {
        "modules": list(MODULE_CHOICES), "active": "1", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    assert get_user_modules(uid) == sorted(MODULE_CHOICES)


def test_create_user_with_module_subset():
    admin = login_client(app.test_client(), "admin")
    conn = get_db()
    conn.execute("DELETE FROM user_modules WHERE user_id IN (SELECT id FROM users WHERE username = 'partial');")
    conn.execute("DELETE FROM users WHERE username = 'partial';")
    conn.commit()
    conn.close()

    resp = _post(admin, "/admin/users/create", {
        "username": "partial",
        "password": "Partial-Pass-1",
        "confirm_password": "Partial-Pass-1",
        "role": "staff",
        "modules": ["pricing"],
        "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302

    partial = login_client(app.test_client(), "partial", password="Partial-Pass-1")
    assert partial.get("/pricing/products").status_code == 200
    assert partial.get("/offer/offers").status_code == 403
    assert partial.get("/rent/contracts").status_code == 403
    assert partial.get("/sale/pricelist").status_code == 403  # v2: sale is grantable too

    # cleanup for the rest of the suite (module rows first: FK)
    conn = get_db()
    conn.execute("DELETE FROM user_modules WHERE user_id IN (SELECT id FROM users WHERE username = 'partial');")
    conn.execute("DELETE FROM users WHERE username = 'partial';")
    conn.commit()
    conn.close()
