"""Phase 3 step 2: werkzeug hashing, transparent legacy rehash, and the
'no plaintext passwords at rest' end-state guarantee.

Login verification now runs against the users table (shared.auth.check_password
kept its legacy signature so the per-module login routes and admin
confirm-password flows work unchanged). These tests pin:

* legacy plaintext rows (e.g. from a pre-Phase-3 restored DB) verify by
  constant-time compare and are rehashed transparently on first successful
  login;
* werkzeug-hash rows verify without any rewrite;
* deactivated accounts cannot log in;
* after the full boot init the DB holds NO plaintext passwords anywhere --
  the four legacy '{app}_password' keys are scrubbed from global_settings on
  every boot and every users.password_hash is a werkzeug serialization;
* restoring a pre-Phase-3 style database (legacy keys, no users table) and
  re-running the auth init migrates + scrubs it;
* factory reset re-seeds the four hashed default accounts instead of writing
  plaintext password keys.
"""

import sqlite3

from werkzeug.security import check_password_hash
from werkzeug.test import Client

import qp_crm.main
import qp_crm.shared.db as shared_db
from qp_crm.shared.auth import (
    DEFAULT_PASSWORDS,
    LEGACY_PASSWORD_KEYS,
    _is_werkzeug_hash,
    check_password,
    get_db,
    set_password,
)


def _fetch_user(username):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?;", (username,))
    row = cur.fetchone()
    conn.close()
    return row


def test_werkzeug_hash_rows_verify_without_rewrite(conn_factory):
    with conn_factory() as conn:
        before = _fetch_user("admin")["password_hash"]
    assert check_password("admin", DEFAULT_PASSWORDS["admin"]) is True
    assert check_password("admin", "wrong") is False
    after = _fetch_user("admin")["password_hash"]
    assert before == after  # verified as a hash: no rewrite happened


def test_legacy_plaintext_row_is_rehashed_transparently(conn_factory):
    # Simulate a pre-Phase-3 row restored over this DB.
    conn = get_db()
    conn.execute(
        "UPDATE users SET password_hash = 'Legacy-Plain-7' WHERE username = 'rent';"
    )
    conn.commit()
    conn.close()

    # First successful login verifies the plaintext...
    assert check_password("rent", "Legacy-Plain-7") is True

    # ...and transparently upgrades the row to a werkzeug hash.
    row = _fetch_user("rent")
    assert _is_werkzeug_hash(row["password_hash"])
    assert check_password_hash(row["password_hash"], "Legacy-Plain-7")

    # A failed login on a plaintext row must NOT rewrite anything.
    conn = get_db()
    conn.execute(
        "UPDATE users SET password_hash = 'Legacy-Plain-8' WHERE username = 'rent';"
    )
    conn.commit()
    conn.close()
    assert check_password("rent", "not-the-password") is False
    assert _fetch_user("rent")["password_hash"] == "Legacy-Plain-8"

    # Restore the seeded default for the rest of the suite.
    set_password("rent", DEFAULT_PASSWORDS["rent"])
    assert check_password("rent", DEFAULT_PASSWORDS["rent"]) is True


def test_deactivated_account_cannot_login(conn_factory):
    conn = get_db()
    conn.execute("UPDATE users SET is_active = 0 WHERE username = 'offer';")
    conn.commit()
    conn.close()
    assert check_password("offer", DEFAULT_PASSWORDS["offer"]) is False
    conn = get_db()
    conn.execute("UPDATE users SET is_active = 1 WHERE username = 'offer';")
    conn.commit()
    conn.close()


def test_set_password_stores_only_hashes(conn_factory):
    set_password("rent", "Brand-New-99")
    row = _fetch_user("rent")
    assert row["password_hash"] != "Brand-New-99"
    assert check_password("rent", "Brand-New-99") is True
    set_password("rent", DEFAULT_PASSWORDS["rent"])


def test_no_plaintext_passwords_at_rest_after_full_init(conn_factory):
    """The card's end-state scan: no legacy keys, no plaintext values."""
    conn = get_db()
    cur = conn.cursor()
    legacy_keys = [
        r["key"]
        for r in cur.execute("SELECT key FROM global_settings;")
        if r["key"].endswith("_password")
    ]
    users = cur.execute("SELECT * FROM users;").fetchall()
    conn.close()

    assert legacy_keys == []  # no '{app}_password' keys survive init
    for user in users:
        stored = user["password_hash"]
        assert _is_werkzeug_hash(stored), f"{user['username']} not hashed"
        for plaintext in DEFAULT_PASSWORDS.values():
            assert plaintext not in stored


def test_legacy_keys_scrubbed_even_without_new_seeding(conn_factory):
    # A users table can already be complete (e.g. a step-1-era build) while
    # the plaintext keys linger from a restore -- the boot scrub must remove
    # them regardless of whether any new account was seeded.
    conn = get_db()
    cur = conn.cursor()
    for key in LEGACY_PASSWORD_KEYS:
        cur.execute(
            "INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?);",
            (key, "Plaintext-Leak"),
        )
    conn.commit()
    conn.close()

    from qp_crm.admin.app import init_users_table

    init_users_table()  # seeds nothing new, but scrubs

    conn = get_db()
    cur = conn.cursor()
    rows = [
        r["key"]
        for r in cur.execute("SELECT key FROM global_settings;")
        if r["key"].endswith("_password")
    ]
    conn.close()
    assert rows == []


def test_pre_phase3_db_migrates_on_auth_reinit(tmp_path, monkeypatch):
    """The restore_db / restore_full code path: pointing the auth init at a
    pre-Phase-3 database file (legacy plaintext keys, no users table) must
    seed hashed accounts and scrub the keys."""
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("CREATE TABLE global_settings (key TEXT PRIMARY KEY, value TEXT);")
    cur.execute("INSERT INTO global_settings VALUES ('date_format', 'YYYY-MM-DD');")
    for key in LEGACY_PASSWORD_KEYS:
        cur.execute(
            "INSERT INTO global_settings (key, value) VALUES (?, ?);",
            (key, "Old-Secret-" + key.split("_")[0]),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(shared_db, "DATABASE", db_path)
    from qp_crm.admin.app import init_users_table

    init_users_table()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    usernames = {r["username"] for r in cur.execute("SELECT username FROM users;")}
    leftover = [
        r["key"]
        for r in cur.execute("SELECT key FROM global_settings;")
        if r["key"].endswith("_password")
    ]
    admin_hash = cur.execute(
        "SELECT password_hash FROM users WHERE username = 'admin';"
    ).fetchone()["password_hash"]
    conn.close()

    assert usernames == {"admin", "pricing", "offer", "rent"}
    assert leftover == []
    # The legacy '{app}_password' values win over the shared defaults (the
    # step-1 seeding contract): the admin account must open with the value
    # from the restored DB, hashed.
    assert check_password_hash(admin_hash, "Old-Secret-admin")


def test_factory_reset_resets_hashed_accounts_without_plaintext_keys():
    """factory_reset used to write admin/pricing/offer plaintext passwords
    into global_settings; now it re-seeds the four hashed default accounts
    and leaves no '{app}_password' keys behind."""
    client = Client(qp_crm.main.application)
    # unified login (the old /admin/login URLs are plain redirects now)
    resp = client.post(
        "/login",
        data={"username": "admin", "password": DEFAULT_PASSWORDS["admin"]},
    )
    assert resp.status_code == 302

    resp = client.post(
        "/admin/factory_reset", data={"current_admin_password": DEFAULT_PASSWORDS["admin"]}
    )
    assert resp.status_code == 200  # backup zip download

    conn = get_db()
    cur = conn.cursor()
    leftover = [
        r["key"]
        for r in cur.execute("SELECT key FROM global_settings;")
        if r["key"].endswith("_password")
    ]
    users = {r["username"]: r for r in cur.execute("SELECT * FROM users;")}
    conn.close()

    assert leftover == []
    assert set(users) == {"admin", "pricing", "offer", "rent"}
    for username, user in users.items():
        assert _is_werkzeug_hash(user["password_hash"])
        assert check_password_hash(user["password_hash"], DEFAULT_PASSWORDS[username])
