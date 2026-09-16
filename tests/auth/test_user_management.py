"""Phase 3 step 6: admin Users management UI (password changes live here).

Pinned behavior (the self-service /change-password page and the forced
first-login detour are REMOVED by user request -- an admin sets a working
password directly in Admin -> Users, must_change_password stays 0):

* every Users-UI POST requires the ACTING ADMIN'S OWN password
  (current_password) -- a wrong one is rejected before anything happens;
* create: unique username (3-32 chars), 8+ password, confirm match; new
  staff accounts log straight in (no forced change, flag stays 0);
* deactivate: self-deactivation blocked, last-active-admin protected;
  a deactivated user loses access on their next request;
* role change: own-role change blocked, last-active-admin demotion blocked;
* admin password reset stores a hash that works on the target's very next
  login (also how the admin changes their own password);
* the old self-service /change-password page answers 404 (tokenless POSTs
  meet the CSRF shield's 400 first).
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.auth import (
    DEFAULT_PASSWORDS,
    MODULE_CHOICES,
    _is_werkzeug_hash,
    check_password,
    generate_password_hash,
    get_db,
)


def _uid(username):
    conn = get_db()
    row = conn.execute("SELECT id FROM users WHERE username = ?;", (username,)).fetchone()
    conn.close()
    return row["id"]


def _reset_user(username):
    """Restore a seeded account to its canonical state (active, default
    password, must_change_password 0). The temp DB persists across docker
    pytest invocations, so tests that mutate it reset what they touch --
    both before AND after the mutation."""
    conn = get_db()
    conn.execute(
        "UPDATE users SET is_active = 1, must_change_password = 0, password_hash = ? "
        "WHERE username = ?;",
        (generate_password_hash(DEFAULT_PASSWORDS[username]), username),
    )
    conn.commit()
    conn.close()


def _post(client, path, data):
    data["_csrf_token"] = csrf_token_for(client)
    return client.post(path, data=data)


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


@pytest.fixture()
def admin():
    return login_client(app.test_client(), "admin")


# ------------------------------------------------------------------ listing

def test_users_page_lists_all_accounts(admin):
    resp = admin.get("/admin/users")
    assert resp.status_code == 200
    body = resp.data.decode()
    for username in ("admin", "pricing", "offer", "rent"):
        assert username in body


def test_users_page_admin_only():
    client = login_client(app.test_client(), "pricing")
    assert client.get("/admin/users").status_code == 403


# ------------------------------------------------------- create (with confirm)

def test_create_user_requires_admins_own_password(admin):
    resp = _post(admin, "/admin/users/create", {
        "username": "newbie",
        "password": "Newbie-Pass-1",
        "confirm_password": "Newbie-Pass-1",
        "role": "staff",
        "current_password": "WRONG-current-1",
    })
    assert resp.status_code == 302  # back to the users page with an error
    conn = get_db()
    assert conn.execute("SELECT COUNT(*) FROM users WHERE username='newbie'").fetchone()[0] == 0
    conn.close()


def test_created_staff_logs_straight_in_no_forced_change(admin):
    """A freshly created staff account is immediately usable: hashed
    password, must_change_password stays 0 (the forced first-login detour
    is retired), first login lands straight on the app."""
    conn = get_db()
    conn.execute("DELETE FROM user_modules WHERE user_id IN (SELECT id FROM users WHERE username = 'newbie');")
    conn.execute("DELETE FROM users WHERE username = 'newbie';")
    conn.commit()
    conn.close()
    _reset_user("offer")
    resp = _post(admin, "/admin/users/create", {
        "username": "newbie",
        "password": "Newbie-Pass-1",
        "confirm_password": "Newbie-Pass-1",
        "role": "staff",
        # the UI create form ships with all app checkboxes pre-checked
        "modules": ["pricing", "offer", "rent"],
        "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username='newbie'").fetchone()
    conn.close()
    assert row is not None
    assert row["role"] == "staff"
    assert row["must_change_password"] == 0  # forced change retired
    assert _is_werkzeug_hash(row["password_hash"])
    # the new staff account is immediately usable under the role gates
    fresh = login_client(app.test_client(), "newbie", password="Newbie-Pass-1")
    assert fresh.get("/pricing/products").status_code == 200
    conn = get_db()
    conn.execute("DELETE FROM user_modules WHERE user_id IN (SELECT id FROM users WHERE username = 'newbie');")
    conn.execute("DELETE FROM users WHERE username = 'newbie';")
    conn.commit()
    conn.close()


def test_create_user_rejects_duplicate_and_weak_password(admin):
    conn = get_db()
    conn.execute("DELETE FROM user_modules WHERE user_id IN (SELECT id FROM users WHERE username IN ('dup', 'mismatch', 'no-such'));")
    conn.execute("DELETE FROM users WHERE username IN ('dup', 'mismatch', 'no-such');")
    conn.commit()
    conn.close()
    _post(admin, "/admin/users/create", {
        "username": "dup", "password": "Dup-Pass-123", "confirm_password": "Dup-Pass-123",
        "role": "staff", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    for data in (
        {"username": "dup", "password": "Dup-Pass-123", "confirm_password": "Dup-Pass-123",
         "role": "staff", "current_password": DEFAULT_PASSWORDS["admin"]},
        {"username": "no-such", "password": "short", "confirm_password": "short",
         "role": "staff", "current_password": DEFAULT_PASSWORDS["admin"]},
        {"username": "mismatch", "password": "Mismatch-Pass-1",
         "confirm_password": "Mismatch-Pass-2", "role": "staff",
         "current_password": DEFAULT_PASSWORDS["admin"]},
    ):
        resp = _post(admin, "/admin/users/create", data)
        assert resp.status_code == 302
    conn = get_db()
    names = [r[0] for r in conn.execute("SELECT username FROM users").fetchall()]
    conn.close()
    assert "mismatch" not in names and "no-such" not in names
    # 'dup' was created once; the duplicate attempt was rejected
    assert names.count("dup") == 1


# --------------------------------------------------------- deactivate / guards

def test_admin_cannot_deactivate_self(admin):
    resp = _post(admin, f"/admin/users/{_uid('admin')}/save", {
        "modules": list(MODULE_CHOICES), "has_modules": "1",
        "active": "0", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    conn = get_db()
    assert conn.execute("SELECT is_active FROM users WHERE username='admin'").fetchone()[0] == 1
    conn.close()


def test_last_active_admin_cannot_be_deactivated_or_demoted():
    """Service-level invariant (Phase 3 step 6).

    Through the UI this guard is unreachable by construction -- the ACTING
    admin is always active themselves, so at least one other active admin
    exists whenever the action is admitted at all. It still protects the
    service layer (races, future callers): when exactly ONE active admin
    remains, they can be deactivated or demoted by nobody.
    """
    from qp_crm.shared.auth import create_user, change_user_role, set_user_active

    # Fresh second admin (the temp DB persists across pytest invocations).
    conn = get_db()
    conn.execute("DELETE FROM user_modules WHERE user_id IN (SELECT id FROM users WHERE username = 'admin2');")
    conn.execute("DELETE FROM users WHERE username = 'admin2';")
    conn.commit()
    conn.close()
    ok, err = create_user("admin2", "Admin2-Pass-1", "Admin2-Pass-1", "admin")
    assert ok, err

    # admin2 is then deactivated (allowed: 'admin' stays active, so admin2
    # is not the last one).
    ok, _ = set_user_active(_uid("admin"), _uid("admin2"), False)
    assert ok, "deactivating the second admin must work while another is active"

    # Now 'admin' is the LAST active admin. An inactive second admin (or any
    # caller) must not be able to deactivate or demote them.
    ok, err = set_user_active(_uid("admin2"), _uid("admin"), False)
    assert not ok and err == "Cannot deactivate the last active admin."
    conn = get_db()
    assert conn.execute("SELECT is_active FROM users WHERE username='admin'").fetchone()[0] == 1
    conn.close()

    ok, err = change_user_role(_uid("admin2"), _uid("admin"), "staff")
    assert not ok and err == "Cannot demote the last active admin."
    conn = get_db()
    assert conn.execute("SELECT role FROM users WHERE username='admin'").fetchone()[0] == "admin"
    conn.close()

    # Cleanup for the rest of the suite (module rows first: FK).
    conn = get_db()
    conn.execute("DELETE FROM user_modules WHERE user_id IN (SELECT id FROM users WHERE username IN ('admin2', 'newbie', 'dup'));")
    conn.execute("DELETE FROM users WHERE username IN ('admin2', 'newbie', 'dup');")
    conn.commit()
    conn.close()


def test_deactivated_user_loses_access_via_ui(admin):
    _reset_user("offer")
    resp = _post(admin, f"/admin/users/{_uid('offer')}/save", {
        "modules": list(MODULE_CHOICES), "has_modules": "1",
        "active": "0", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302

    # A deactivated account cannot even LOG IN (shared.auth.get_user only
    # returns active rows), and any still-open session dies on the next
    # request (require_role re-reads the users row -- pinned in step 4).
    client = app.test_client()
    client.get("/login")
    token = csrf_token_for(client)
    resp = client.post("/login", data={
        "username": "offer", "password": DEFAULT_PASSWORDS["offer"], "_csrf_token": token,
    })
    assert resp.status_code == 200  # login form re-renders: access refused

    # reactivate for the rest of the suite: login works again immediately
    resp = _post(admin, f"/admin/users/{_uid('offer')}/save", {
        "modules": list(MODULE_CHOICES), "has_modules": "1",
        "active": "1", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    offer = login_client(app.test_client(), "offer")
    assert offer.get("/offer/offers").status_code == 200


# ---------------------------------------------------------------- role change

def test_role_change_self_blocked(admin):
    resp = _post(admin, f"/admin/users/{_uid('admin')}/save", {
        "role": "staff", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    conn = get_db()
    assert conn.execute("SELECT role FROM users WHERE username='admin'").fetchone()[0] == "admin"
    conn.close()


def test_role_change_staff_to_admin_grants_access(admin):
    resp = _post(admin, f"/admin/users/{_uid('rent')}/save", {
        "modules": list(MODULE_CHOICES), "has_modules": "1",
        "role": "admin", "active": "1", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    rent = login_client(app.test_client(), "rent")
    assert rent.get("/admin/").status_code == 200
    # restore
    resp = _post(admin, f"/admin/users/{_uid('rent')}/save", {
        "modules": list(MODULE_CHOICES), "has_modules": "1",
        "role": "staff", "active": "1", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302


# ------------------------------------------------------------- password reset

def test_admin_sets_password_directly_no_forced_change(admin):
    """Passwords are set HERE (Admin -> Users): the new password works on
    the very next login -- no forced change-on-next-login detour (the
    self-service /change-password page is removed entirely)."""
    _reset_user("pricing")
    resp = _post(admin, f"/admin/users/{_uid('pricing')}/save", {
        "modules": list(MODULE_CHOICES), "has_modules": "1",
        "new_password": "Reset-Pass-99", "active": "1", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302

    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username='pricing'").fetchone()
    conn.close()
    assert row["must_change_password"] == 0  # forced change retired
    assert _is_werkzeug_hash(row["password_hash"])
    assert not check_password("pricing", DEFAULT_PASSWORDS["pricing"])

    # the new password works immediately and lands on the app
    client = app.test_client()
    client.get("/login")
    token = csrf_token_for(client)
    resp = client.post("/login", data={
        "username": "pricing", "password": "Reset-Pass-99", "_csrf_token": token,
    })
    assert resp.status_code == 302
    assert "change-password" not in resp.headers.get("Location", "")
    assert client.get("/pricing/products", follow_redirects=True).status_code == 200

    # restore the seeded default password for the rest of the suite
    from qp_crm.shared.auth import set_password
    set_password("pricing", DEFAULT_PASSWORDS["pricing"])


def test_admin_reset_requires_own_password(admin):
    resp = _post(admin, f"/admin/users/{_uid('rent')}/save", {
        "modules": list(MODULE_CHOICES), "has_modules": "1",
        "new_password": "Whatever-Pass-1", "current_password": "WRONG-current-1",
    })
    assert resp.status_code == 302
    assert check_password("rent", DEFAULT_PASSWORDS["rent"])  # unchanged


# ------------------------------------------------------- retired self-service

def test_own_row_save_has_a_real_form_element(admin):
    """Regression: the own row's Save button must submit a real <form>.

    The template renders one <form id="user-form-{id}"> per user ROW and the
    Save button + password inputs join it via the HTML5 form= attribute. A
    Phase-3 regression wrapped that form element in
    {% if user.id != current_user_id %}, so the OWN row's Save referenced a
    form id that did not exist and the browser submitted nothing -- the admin
    could not change their own password (reported: "clicking save does
    nothing"). Pin that every rendered row id (own included) has exactly one
    matching <form id> on the page, and that the own-row endpoint accepts a
    password change."""
    own_id = _uid("admin")
    resp = admin.get("/admin/users")
    body = resp.data.decode()
    # the own row's Save button and password fields point at user-form-{own_id}
    assert f'form="user-form-{own_id}"' in body
    # and that form element must actually exist on the page
    assert f'<form id="user-form-{own_id}"' in body
    # the full flow: changing your own password via the row endpoint works
    resp = _post(admin, f"/admin/users/{own_id}/save", {
        "current_password": DEFAULT_PASSWORDS["admin"],
        "new_password": "Admin-Temp-Pass-1",
    })
    assert resp.status_code == 302
    assert check_password("admin", "Admin-Temp-Pass-1")
    # restore the seeded default so later tests keep authenticating
    _reset_user("admin")
    assert check_password("admin", DEFAULT_PASSWORDS["admin"])


def test_self_service_change_password_page_is_removed():
    """The /change-password page is GONE: password changes happen only in
    Admin -> Users, where the admin sets a working password directly."""
    _reset_user("offer")
    client = login_client(app.test_client(), "offer")
    assert client.get("/change-password").status_code == 404
    resp = client.post("/change-password", data={
        "current_password": DEFAULT_PASSWORDS["offer"],
        "new_password": "Offer-New-Pass-1",
        "confirm_password": "Offer-New-Pass-1",
        "_csrf_token": csrf_token_for(client),
    })
    assert resp.status_code == 404
    assert check_password("offer", DEFAULT_PASSWORDS["offer"])  # unchanged
