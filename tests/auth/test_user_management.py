"""Phase 3 step 6: admin Users management UI + self-service password change.

Pinned behavior:

* every Users-UI POST requires the ACTING ADMIN'S OWN password
  (current_password) -- a wrong one is rejected before anything happens;
* create: unique username (3-32 chars), 8+ password, confirm match; new
  staff accounts are forced to change their password on first login;
* deactivate: self-deactivation blocked, last-active-admin protected;
  a deactivated user loses access on their next request;
* role change: own-role change blocked, last-active-admin demotion blocked;
* admin password reset stores a hash and forces a change on the target's
  next login (except when the admin resets their own);
* self-service /change-password requires the CURRENT password, enforces the
  8-character minimum + confirmation, and clears must_change_password.
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.auth import (
    DEFAULT_PASSWORDS,
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
    password, must-change flag on). The temp DB persists across docker
    pytest invocations, so tests that mutate it reset what they touch --
    both before AND after the mutation."""
    conn = get_db()
    conn.execute(
        "UPDATE users SET is_active = 1, must_change_password = 1, password_hash = ? "
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


def test_create_staff_user_forces_first_login_change(admin):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE username = 'newbie';")
    conn.commit()
    conn.close()
    _reset_user("offer")
    resp = _post(admin, "/admin/users/create", {
        "username": "newbie",
        "password": "Newbie-Pass-1",
        "confirm_password": "Newbie-Pass-1",
        "role": "staff",
        "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username='newbie'").fetchone()
    conn.close()
    assert row is not None
    assert row["role"] == "staff"
    assert row["must_change_password"] == 1
    assert _is_werkzeug_hash(row["password_hash"])
    # the new staff account is immediately usable under the role gates
    fresh = login_client(app.test_client(), "newbie", password="Newbie-Pass-1")
    assert fresh.get("/pricing/products").status_code == 200
    conn = get_db()
    conn.execute("DELETE FROM users WHERE username = 'newbie';")
    conn.commit()
    conn.close()


def test_create_user_rejects_duplicate_and_weak_password(admin):
    conn = get_db()
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
    resp = _post(admin, f"/admin/users/{_uid('admin')}/toggle_active", {
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

    # Cleanup for the rest of the suite.
    conn = get_db()
    conn.execute("DELETE FROM users WHERE username IN ('admin2', 'newbie', 'dup');")
    conn.commit()
    conn.close()


def test_deactivated_user_loses_access_via_ui(admin):
    _reset_user("offer")
    resp = _post(admin, f"/admin/users/{_uid('offer')}/toggle_active", {
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
    resp = _post(admin, f"/admin/users/{_uid('offer')}/toggle_active", {
        "active": "1", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    offer = login_client(app.test_client(), "offer")
    assert offer.get("/offer/offers").status_code == 200


# ---------------------------------------------------------------- role change

def test_role_change_self_blocked(admin):
    resp = _post(admin, f"/admin/users/{_uid('admin')}/role", {
        "role": "staff", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    conn = get_db()
    assert conn.execute("SELECT role FROM users WHERE username='admin'").fetchone()[0] == "admin"
    conn.close()


def test_role_change_staff_to_admin_grants_access(admin):
    resp = _post(admin, f"/admin/users/{_uid('rent')}/role", {
        "role": "admin", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    rent = login_client(app.test_client(), "rent")
    assert rent.get("/admin/").status_code == 200
    # restore
    resp = _post(admin, f"/admin/users/{_uid('rent')}/role", {
        "role": "staff", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302


# ------------------------------------------------------------- password reset

def test_admin_reset_forces_change_on_next_login(admin):
    _reset_user("pricing")
    resp = _post(admin, f"/admin/users/{_uid('pricing')}/reset_password", {
        "new_password": "Reset-Pass-99", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302

    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username='pricing'").fetchone()
    conn.close()
    assert row["must_change_password"] == 1
    assert _is_werkzeug_hash(row["password_hash"])
    assert not check_password("pricing", DEFAULT_PASSWORDS["pricing"])

    # The reset user is forced through the change-password page...
    client = app.test_client()
    client.get("/login")
    token = csrf_token_for(client)
    resp = client.post("/login", data={
        "username": "pricing", "password": "Reset-Pass-99", "_csrf_token": token,
    })
    assert resp.status_code == 302
    assert "/change-password" in resp.headers["Location"]
    assert client.get("/pricing/products").status_code == 302  # forced

    # ...and can complete it with the self-service form.
    client.get("/change-password")
    token = csrf_token_for(client)
    resp = client.post("/change-password", data={
        "current_password": "Reset-Pass-99",
        "new_password": "Pricing-New-1",
        "confirm_password": "Pricing-New-1",
        "_csrf_token": token,
    })
    assert resp.status_code == 302
    assert client.get("/pricing/products", follow_redirects=True).status_code == 200
    assert check_password("pricing", "Pricing-New-1")

    # restore the seeded default password + flag for the rest of the suite
    from qp_crm.shared.auth import set_password
    set_password("pricing", DEFAULT_PASSWORDS["pricing"])
    conn = get_db()
    conn.execute("UPDATE users SET must_change_password = 1 WHERE username = 'pricing';")
    conn.commit()
    conn.close()


def test_admin_reset_requires_own_password(admin):
    resp = _post(admin, f"/admin/users/{_uid('rent')}/reset_password", {
        "new_password": "Whatever-Pass-1", "current_password": "WRONG-current-1",
    })
    assert resp.status_code == 302
    assert check_password("rent", DEFAULT_PASSWORDS["rent"])  # unchanged


# ------------------------------------------------------------- self-service

def test_self_service_change_requires_current_and_enforces_minimum():
    _reset_user("offer")
    client = login_client(app.test_client(), "offer")

    # wrong current password
    client.get("/change-password")
    token = csrf_token_for(client)
    resp = client.post("/change-password", data={
        "current_password": "WRONG-current-1",
        "new_password": "Offer-New-Pass-1",
        "confirm_password": "Offer-New-Pass-1",
        "_csrf_token": token,
    })
    body = resp.data.decode()
    assert resp.status_code == 200 and "Current password is incorrect" in body
    assert check_password("offer", DEFAULT_PASSWORDS["offer"])

    # too-short new password
    resp = client.post("/change-password", data={
        "current_password": DEFAULT_PASSWORDS["offer"],
        "new_password": "short",
        "confirm_password": "short",
        "_csrf_token": token,
    })
    assert "at least 8 characters" in resp.data.decode()
    assert check_password("offer", DEFAULT_PASSWORDS["offer"])

    # mismatched confirmation
    resp = client.post("/change-password", data={
        "current_password": DEFAULT_PASSWORDS["offer"],
        "new_password": "Offer-New-Pass-1",
        "confirm_password": "Offer-New-Pass-2",
        "_csrf_token": token,
    })
    assert "did not match" in resp.data.decode()
    assert check_password("offer", DEFAULT_PASSWORDS["offer"])

    # success: hash rotated, user keeps working with the new password
    resp = client.post("/change-password", data={
        "current_password": DEFAULT_PASSWORDS["offer"],
        "new_password": "Offer-New-Pass-1",
        "confirm_password": "Offer-New-Pass-1",
        "_csrf_token": token,
    })
    assert resp.status_code == 302
    assert check_password("offer", "Offer-New-Pass-1")

    # restore for the rest of the suite
    from qp_crm.shared.auth import set_password
    set_password("offer", DEFAULT_PASSWORDS["offer"])
