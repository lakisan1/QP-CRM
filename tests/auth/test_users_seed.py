"""Legacy-account seeding tests (admin-only bootstrap contract).

temp_db boots the full production init sequence, which since the "no
default users beyond admin" change seeds exactly ONE account: `admin`
(from the legacy `admin_password` source when present, the
DEFAULT_PASSWORDS fallback otherwise). The three staff accounts the auth
suite needs are provisioned by conftest.staff_accounts, NOT by
production seeding. These tests therefore run against isolated in-memory
DBs and pin the production contract:

* an empty DB is seeded with exactly {admin} (role admin);
* staff usernames are never auto-created;
* deleting a (legacy) staff row is NOT undone by a later seed run — the
  live-DB scenario that motivated the change;
* admin's initial password comes from the legacy `admin_password`
  global_settings row when set, else DEFAULT_PASSWORDS['admin'], stored
  only as a werkzeug hash, with no forced-change flag.
"""

import sqlite3

from werkzeug.security import check_password_hash

from qp_crm.shared.auth import DEFAULT_PASSWORDS, seed_users_from_legacy
from qp_crm.shared.schema import create_users_table


def _new_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE global_settings (key TEXT PRIMARY KEY, value TEXT);")
    create_users_table(conn.cursor())
    return conn


def _users(conn):
    return {row["username"]: row for row in conn.execute("SELECT * FROM users")}


def test_empty_db_seeds_only_admin():
    conn = _new_conn()
    seed_users_from_legacy(conn.cursor())
    users = _users(conn)
    assert set(users) == {"admin"}
    assert users["admin"]["role"] == "admin"
    assert users["admin"]["is_active"] == 1
    conn.close()


def test_staff_accounts_are_never_auto_created():
    conn = _new_conn()
    seed_users_from_legacy(conn.cursor())
    for username in ("pricing", "offer", "rent"):
        row = conn.execute(
            "SELECT 1 FROM users WHERE username = ?;", (username,)
        ).fetchone()
        assert row is None, f"{username} must not be auto-seeded"
    conn.close()


def test_seeding_does_not_resurrect_deleted_staff():
    """The live-DB scenario: staff rows deleted by an admin stay deleted
    across subsequent boot seed runs."""
    conn = _new_conn()
    cur = conn.cursor()
    seed_users_from_legacy(cur)  # admin only
    # Simulate a pre-change legacy staff row, then the admin deleting it.
    cur.execute(
        "INSERT INTO users (username, password_hash, role, is_active, must_change_password, created_at)"
        " VALUES ('pricing', 'x', 'staff', 1, 0, datetime('now'));"
    )
    cur.execute("DELETE FROM users WHERE username = 'pricing';")
    conn.commit()

    seed_users_from_legacy(cur)  # next boot
    users = _users(conn)
    assert set(users) == {"admin"}
    conn.close()


def test_seeded_admin_hash_preserves_default_password():
    conn = _new_conn()
    seed_users_from_legacy(conn.cursor())
    admin = _users(conn)["admin"]
    assert admin["password_hash"] != DEFAULT_PASSWORDS["admin"]  # not plaintext
    assert check_password_hash(admin["password_hash"], DEFAULT_PASSWORDS["admin"])
    conn.close()


def test_legacy_admin_password_row_wins_over_default():
    # An operator who changed the admin password via the old admin UI has an
    # 'admin_password' row in global_settings; that value -- not the shared
    # default -- becomes the bootstrap account's initial password.
    conn = _new_conn()
    conn.execute("INSERT INTO global_settings VALUES ('admin_password', 'Custom-Legacy-9');")
    seed_users_from_legacy(conn.cursor())
    admin = _users(conn)["admin"]
    assert check_password_hash(admin["password_hash"], "Custom-Legacy-9")
    assert not check_password_hash(admin["password_hash"], DEFAULT_PASSWORDS["admin"])
    conn.close()


def test_seeded_admin_has_no_forced_change_flag():
    conn = _new_conn()
    seed_users_from_legacy(conn.cursor())
    assert _users(conn)["admin"]["must_change_password"] == 0
    conn.close()


def test_seeding_is_idempotent():
    conn = _new_conn()
    cur = conn.cursor()
    seed_users_from_legacy(cur)
    before = _users(conn)
    seed_users_from_legacy(cur)
    after = _users(conn)
    assert before.keys() == after.keys()
    assert before["admin"]["password_hash"] == after["admin"]["password_hash"]
    conn.close()
