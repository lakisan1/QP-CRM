"""Phase 3 step 1: users table + legacy account migration tests.

The temp_db fixture (tests/conftest.py) runs the full boot init sequence,
which since Phase 3 includes admin.init_db -> init_users_table(): the four
legacy accounts are seeded from the legacy password sources (global_settings
'{app}_password' rows when present, shared.auth.DEFAULT_PASSWORDS otherwise).
These tests pin that migration: roles, initial passwords (as hashes --
the legacy plaintext values stay the working passwords), forced password
change on first login for the migrated non-admin accounts, and idempotency.
"""

import sqlite3

from werkzeug.security import check_password_hash

from qp_crm.shared.auth import DEFAULT_PASSWORDS, seed_users_from_legacy
from qp_crm.shared.schema import create_users_table


def _users(conn):
    return {row["username"]: row for row in conn.execute("SELECT * FROM users")}


def test_four_legacy_accounts_seeded_with_roles(conn_factory):
    with conn_factory() as conn:
        users = _users(conn)
    assert set(users) == {"admin", "pricing", "offer", "rent"}
    assert users["admin"]["role"] == "admin"
    assert users["pricing"]["role"] == "staff"
    assert users["offer"]["role"] == "staff"
    assert users["rent"]["role"] == "staff"
    assert all(u["is_active"] == 1 for u in users.values())


def test_seeded_hashes_preserve_legacy_passwords(conn_factory):
    # The legacy plaintext values remain the working passwords of the
    # migrated accounts -- but are stored ONLY as werkzeug hashes.
    with conn_factory() as conn:
        users = _users(conn)
    for username, row in users.items():
        assert row["password_hash"] != DEFAULT_PASSWORDS[username]
        assert check_password_hash(row["password_hash"], DEFAULT_PASSWORDS[username])


def test_non_admin_accounts_must_change_password_on_first_login(conn_factory):
    with conn_factory() as conn:
        users = _users(conn)
    assert users["admin"]["must_change_password"] == 0
    for staff in ("pricing", "offer", "rent"):
        assert users[staff]["must_change_password"] == 1


def test_seeding_is_idempotent(conn_factory):
    with conn_factory() as conn:
        before = _users(conn)
        cur = conn.cursor()
        seed_users_from_legacy(cur)
        after = _users(conn)
    assert before.keys() == after.keys()
    assert {k: v["password_hash"] for k, v in before.items()} == {
        k: v["password_hash"] for k, v in after.items()
    }


def test_legacy_global_settings_password_wins_over_default():
    # An operator who changed e.g. the pricing password via the old admin UI
    # has a '{app}_password' row in global_settings; that value -- not the
    # shared default -- must become the account's initial password.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("CREATE TABLE global_settings (key TEXT PRIMARY KEY, value TEXT);")
    cur.execute("INSERT INTO global_settings VALUES ('pricing_password', 'Custom-Legacy-9');")
    create_users_table(cur)
    seed_users_from_legacy(cur)

    row = cur.execute("SELECT * FROM users WHERE username = 'pricing';").fetchone()
    assert check_password_hash(row["password_hash"], "Custom-Legacy-9")
    assert not check_password_hash(row["password_hash"], DEFAULT_PASSWORDS["pricing"])
    # Untouched accounts still fall back to the shared defaults.
    admin = cur.execute("SELECT * FROM users WHERE username = 'admin';").fetchone()
    assert check_password_hash(admin["password_hash"], DEFAULT_PASSWORDS["admin"])
    conn.close()
