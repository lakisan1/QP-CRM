"""Phase 3 step 7 + legacy-key retirement (2026-09-16): per-user API keys for /api/v1.

Pinned behavior:

* issue_user_api_key returns the raw key exactly once; storage is its
  SHA-256 hash + a display prefix (the raw key is NEVER stored);
* resolve_api_identity accepts ONLY per-user keys — the legacy global
  api_key fallback ('global', None, None) was REMOVED, an old global key
  authenticates NOTHING;
* a revoked key or a key whose holding user is deactivated -> 403;
  missing Bearer header -> 401; unknown key -> 403;
* every authenticated API request lands one row in api_audit: kind='user'
  with the holder's username (kind='global' no longer occurs);
* same-origin session fallback: a logged-in user with the pricing grant
  may call /api/v1 without a Bearer header (product_sync page JS);
* admin UI: issue + revoke require the acting admin's own password.
"""

import hashlib

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.auth import (
    DEFAULT_PASSWORDS,
    delete_user_api_key,
    generate_api_key,
    get_db,
    issue_user_api_key,
    resolve_api_identity,
    set_user_api_key_active,
)


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


def _bearer(client, path, key, method="get", json=None, data=None):
    headers = {"Authorization": f"Bearer {key}"}
    if method == "get":
        return client.get(path, headers=headers)
    return client.post(path, headers=headers, json=json, data=data)


def _last_audit():
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM api_audit ORDER BY id DESC LIMIT 1;"
    ).fetchone()
    conn.close()
    return row


# ------------------------------------------------------------------ service

def test_issue_returns_raw_key_once_stores_hash_only():
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()
    raw, key_id = issue_user_api_key(uid, "webshop sync")
    assert raw and len(raw) == 48
    conn = get_db()
    row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    conn.close()
    assert row["key_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert row["key_prefix"] == raw[:12]
    assert row["label"] == "webshop sync"
    assert row["is_active"] == 1
    # the raw key appears NOWHERE in storage
    conn = get_db()
    blobs = " ".join(
        r[0] for r in conn.execute("SELECT key_hash FROM api_keys").fetchall()
    )
    conn.close()
    assert raw not in blobs


def test_resolve_prefers_user_keys_and_stamps_last_used():
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='pricing'").fetchone()["id"]
    conn.close()
    raw, _ = issue_user_api_key(uid)
    identity = resolve_api_identity(raw)
    assert identity == ("user", "pricing", uid)
    conn = get_db()
    last_used = conn.execute("SELECT last_used FROM api_keys WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    assert last_used["last_used"] is not None


def test_resolve_rejects_global_key_and_unknown_keys():
    # The global-key fallback is retired: a key that is NOT a per-user key
    # (including any leftover global_settings 'api_key' value) matches nothing.
    assert resolve_api_identity("totally-unknown-key") is None
    assert resolve_api_identity("") is None
    # generate_api_key() raises: the legacy lifecycle is closed.
    with pytest.raises(NotImplementedError):
        generate_api_key()


# --------------------------------------------------------------------- HTTP

def test_api_v1_accepts_user_key_end_to_end():
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()
    raw, _ = issue_user_api_key(uid, "e2e")
    client = app.test_client()
    resp = _bearer(client, "/api/v1/products", raw)
    assert resp.status_code == 200
    # the request is audited with the holder's username
    row = _last_audit()
    assert row["kind"] == "user"
    assert row["username"] == "offer"
    assert row["status"] == 200


def test_api_v1_rejects_revoked_key_and_deactivated_holder():
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='rent'").fetchone()["id"]
    conn.close()
    raw, key_id = issue_user_api_key(uid)
    client = app.test_client()

    assert _bearer(client, "/api/v1/products", raw).status_code == 200
    set_user_api_key_active(key_id, 0)
    resp = _bearer(client, "/api/v1/products", raw)
    assert resp.status_code == 403
    # a REFUSED key (revoked / deactivated holder) is still audited, with
    # the holder's username -- a security signal
    row = _last_audit()
    assert row["kind"] == "user-denied" and row["username"] == "rent" and row["status"] == 403

    # re-enabled but holder deactivated -> still 403
    set_user_api_key_active(key_id, 1)
    conn = get_db()
    conn.execute("UPDATE users SET is_active = 0 WHERE id = ?;", (uid,))
    conn.commit()
    conn.close()
    assert _bearer(client, "/api/v1/products", raw).status_code == 403
    # restore
    conn = get_db()
    conn.execute("UPDATE users SET is_active = 1 WHERE id = ?;", (uid,))
    conn.commit()
    conn.close()
    set_user_api_key_active(key_id, 0)  # leave the test key revoked


def test_api_v1_auth_error_codes():
    client = app.test_client()
    # missing header entirely
    assert client.get("/api/v1/products").status_code == 401
    # malformed header
    assert client.get("/api/v1/products", headers={"Authorization": "Basic abc"}).status_code == 401
    # unknown key
    assert _bearer(client, "/api/v1/products", "no-such-key-123456").status_code == 403
    # unauthenticated requests are NOT audited
    conn = get_db()
    before = conn.execute("SELECT COUNT(*) FROM api_audit").fetchone()[0]
    conn.close()
    client.get("/api/v1/products")  # 401
    conn = get_db()
    after = conn.execute("SELECT COUNT(*) FROM api_audit").fetchone()[0]
    conn.close()
    assert before == after


def test_api_v1_session_fallback_for_logged_in_pricing_user():
    """Same-origin page JS (product_sync) calls /api/v1 without a Bearer
    header: a logged-in user WITH the pricing grant is authenticated as
    themselves; anonymous and grant-less sessions are 401/403."""
    client = login_client(app.test_client(), "pricing")
    resp = client.get("/api/v1/products")
    assert resp.status_code == 200
    row = _last_audit()
    assert row["kind"] == "user" and row["username"] == "pricing" and row["status"] == 200

    # staff WITHOUT the pricing grant: 403
    from qp_crm.shared.auth import set_user_modules, MODULE_CHOICES
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()
    set_user_modules(uid, ["offer"])
    try:
        offer_client = login_client(app.test_client(), "offer")
        assert offer_client.get("/api/v1/products").status_code == 403
    finally:
        set_user_modules(uid, list(MODULE_CHOICES))

    # anonymous: 401 (not a redirect — this is an API)
    anon = app.test_client()
    assert anon.get("/api/v1/products").status_code == 401


# ----------------------------------------------------------------- admin UI

def _post(client, path, data):
    data["_csrf_token"] = csrf_token_for(client)
    return client.post(path, data=data)


def test_admin_api_keys_page_and_issue_flow():
    admin = login_client(app.test_client(), "admin")
    assert admin.get("/admin/api_keys").status_code == 200

    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='offer'").fetchone()["id"]
    conn.close()

    # wrong admin password: no key issued
    resp = _post(admin, "/admin/api_keys/issue", {
        "user_id": uid, "label": "ui-test", "current_password": "WRONG-current-1",
    })
    assert resp.status_code == 302
    conn = get_db()
    n = conn.execute("SELECT COUNT(*) FROM api_keys WHERE label='ui-test'").fetchone()[0]
    conn.close()
    assert n == 0

    # correct password: key issued, raw key flashed exactly once
    resp = _post(admin, "/admin/api_keys/issue", {
        "user_id": uid, "label": "ui-test", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    with admin.session_transaction() as session:
        flashes = session.get("_flashes", [])
    raw_keys = [msg for cat, msg in flashes if "shown only once" in msg]
    assert len(raw_keys) == 1
    raw = raw_keys[0].rsplit(": ", 1)[1]

    # the flashed raw key authenticates against the API
    client = app.test_client()
    assert _bearer(client, "/api/v1/products", raw).status_code == 200

    # The flash rendered ON the first page load after issue IS the
    # show-once mechanism; every SUBSEQUENT load shows only the prefix.
    admin.get("/admin/api_keys")  # consumes the flash
    page = admin.get("/admin/api_keys").data.decode()
    assert raw not in page
    assert raw[:12] in page

    # revoke via UI (with own-password confirmation)
    conn = get_db()
    key_id = conn.execute("SELECT id FROM api_keys WHERE label='ui-test'").fetchone()["id"]
    conn.close()
    resp = _post(admin, f"/admin/api_keys/{key_id}/toggle", {
        "active": "0", "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    client2 = app.test_client()
    assert _bearer(client2, "/api/v1/products", raw).status_code == 403


def test_delete_revoked_key_service_and_ui():
    """Hard-delete exists for REVOKED keys only; active keys are refused."""
    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username='pricing'").fetchone()["id"]
    conn.close()
    raw, key_id = issue_user_api_key(uid, "delete-probe")

    # ACTIVE key: service refuses
    ok, error = delete_user_api_key(key_id)
    assert not ok and "revoke it first" in error

    # UI delete on an ACTIVE key: flashed error, row still there
    admin = login_client(app.test_client(), "admin")
    resp = _post(admin, f"/admin/api_keys/{key_id}/delete", {
        "current_password": DEFAULT_PASSWORDS["admin"],
    })
    assert resp.status_code == 302
    conn = get_db()
    assert conn.execute("SELECT COUNT(*) FROM api_keys WHERE id=?", (key_id,)).fetchone()[0] == 1
    conn.close()

    # revoke, then delete succeeds and the row is GONE
    set_user_api_key_active(key_id, 0)
    ok, error = delete_user_api_key(key_id)
    assert ok and error is None
    conn = get_db()
    assert conn.execute("SELECT COUNT(*) FROM api_keys WHERE id=?", (key_id,)).fetchone()[0] == 0
    conn.close()
    # a deleted key authenticates nothing (no row -> unknown key)
    client = app.test_client()
    assert _bearer(client, "/api/v1/products", raw).status_code == 403

    # UI: wrong password on delete is bounced with an error flash
    raw2, key_id2 = issue_user_api_key(uid, "delete-probe-2")
    set_user_api_key_active(key_id2, 0)
    resp = _post(admin, f"/admin/api_keys/{key_id2}/delete", {
        "current_password": "WRONG-password",
    })
    assert resp.status_code == 302
    conn = get_db()
    assert conn.execute("SELECT COUNT(*) FROM api_keys WHERE id=?", (key_id2,)).fetchone()[0] == 1
    conn.close()
    # cleanup via the service (revoked -> deletable)
    assert delete_user_api_key(key_id2) == (True, None)

    # revoked rows show the 🗑 delete button on the page; active ones do not
    raw3, key_id3 = issue_user_api_key(uid, "ui-delete-btn")
    page = admin.get("/admin/api_keys").data.decode()
    assert "/admin/api_keys/%d/delete" % key_id3 not in page  # active: no delete
    set_user_api_key_active(key_id3, 0)
    page = admin.get("/admin/api_keys").data.decode()
    assert "/admin/api_keys/%d/delete" % key_id3 in page      # revoked: delete shown
    assert delete_user_api_key(key_id3) == (True, None)


def test_api_keys_page_admin_only():
    client = login_client(app.test_client(), "pricing")
    assert client.get("/admin/api_keys").status_code == 403
