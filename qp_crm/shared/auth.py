import hashlib
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

DEFAULT_PASSWORDS = {
    "admin": "Admin1",
    "pricing": "Price1",
    "offer": "Offer1",
    "rent": "Rent1"
}

# ---------------------------------------------------------------------------
# Users (Phase 3 step 1): single account table replacing the four legacy
# per-app passwords. The legacy plaintext values -- global_settings
# '{app}_password' rows when present, shared DEFAULT_PASSWORDS otherwise --
# are preserved as the INITIAL passwords of the migrated accounts, but seeded
# directly as werkzeug hashes so no plaintext is ever written at rest.
# admin -> role 'admin'; pricing/offer/rent -> role 'staff' and must change
# their password on first login.
# ---------------------------------------------------------------------------

LEGACY_ACCOUNT_SEEDS = (
    ("admin", "admin"),
    ("pricing", "staff"),
    ("offer", "staff"),
    ("rent", "staff"),
)


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed_users_from_legacy(cur):
    """Create the four accounts from the legacy password sources, idempotently.

    Runs inside admin.init_db (after pricing's global_settings exist). A
    username that already exists is left untouched, so re-running boot or
    restoring old volumes never resets a changed password.
    """
    for username, role in LEGACY_ACCOUNT_SEEDS:
        cur.execute("SELECT id FROM users WHERE username = ?;", (username,))
        if cur.fetchone():
            continue
        cur.execute(
            "SELECT value FROM global_settings WHERE key = ?;",
            (f"{username}_password",),
        )
        row = cur.fetchone()
        legacy = row["value"] if row and row["value"] else DEFAULT_PASSWORDS.get(username)
        if not legacy:
            continue
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role, is_active,
                               must_change_password, created_at)
            VALUES (?, ?, ?, 1, ?, ?);
            """,
            (
                username,
                generate_password_hash(legacy),
                role,
                1 if role != "admin" else 0,
                _utcnow_iso(),
            ),
        )

# ---------- API Key Management ----------

def generate_api_key():
    """
    Generate a new 48-character hex API key and store it in global_settings.
    Returns the generated key.
    """
    new_key = secrets.token_hex(24)  # 48 hex chars
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO global_settings (key, value)
        VALUES ('api_key', ?);
    """, (new_key,))
    conn.commit()
    conn.close()
    return new_key

def get_api_key():
    """
    Retrieve the current API key from global_settings.
    Returns None if no key has been generated yet.
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM global_settings WHERE key = 'api_key';")
        row = cur.fetchone()
    except Exception:
        row = None
    conn.close()
    if row:
        return row["value"]
    return None

def validate_api_key(key):
    """
    Validate that the given API key matches the stored key.
    Returns True if valid, False otherwise.
    """
    if not key:
        return False
    stored = get_api_key()
    if not stored:
        return False
    return secrets.compare_digest(key, stored)

def revoke_api_key():
    """
    Remove the API key from global_settings (revoke access).
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM global_settings WHERE key = 'api_key';")
    conn.commit()
    conn.close()


# ----------
# Per-user API keys (Phase 3 step 7). The raw key exists only at issue time
# (shown once to the issuing admin); storage is sha256(key) + a display
# prefix. resolve_api_identity() checks user keys FIRST, then the legacy
# global key (transition). The key holder's account must be active for the
# key to authenticate -- deactivation revokes access instantly.
# ----------

API_KEY_PREFIX_LEN = 12


def _hash_api_key(raw_key):
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def issue_user_api_key(user_id, label=""):
    """Create a per-user API key. Returns (raw_key, row_id) or (None, error).

    raw_key is returned exactly once -- only its hash is stored.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE id = ? AND is_active = 1;", (user_id,))
    user = cur.fetchone()
    if user is None:
        conn.close()
        return None, "User not found or inactive."
    raw_key = secrets.token_hex(24)  # 48 hex chars, same shape as the global key
    cur.execute(
        """
        INSERT INTO api_keys (user_id, key_hash, key_prefix, label, is_active, created_at)
        VALUES (?, ?, ?, ?, 1, ?);
        """,
        (
            user_id,
            _hash_api_key(raw_key),
            raw_key[:API_KEY_PREFIX_LEN],
            (label or "").strip()[:80],
            _utcnow_iso(),
        ),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return raw_key, row_id


def list_user_api_keys():
    """All per-user keys with their holder's username, newest first."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT k.id, k.user_id, u.username, k.key_prefix, k.label, k.is_active,
               k.created_at, k.last_used
        FROM api_keys k LEFT JOIN users u ON u.id = k.user_id
        ORDER BY k.id DESC;
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def set_user_api_key_active(key_id, active):
    """Revoke (0) or re-enable (1) a per-user key. Returns (ok, error)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM api_keys WHERE id = ?;", (key_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "API key not found."
    cur.execute("UPDATE api_keys SET is_active = ? WHERE id = ?;", (1 if active else 0, key_id))
    conn.commit()
    conn.close()
    return True, None


def resolve_api_identity(raw_key):
    """Map a Bearer key to an identity.

    Returns ('user', username, user_id) for a valid, active per-user key;
    ('user-denied', username, user_id) when the hash matches a key that is
    revoked or whose holder is deactivated (audited as refused, then 403);
    ('global', None, None) for the legacy global api_key (transition);
    None when the key matches nothing. Updates last_used only on success.
    """
    if not raw_key:
        return None
    digest = _hash_api_key(raw_key)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT k.id, k.user_id, u.username, k.is_active AS key_active,
               u.is_active AS user_active
        FROM api_keys k JOIN users u ON u.id = k.user_id
        WHERE k.key_hash = ?;
        """,
        (digest,),
    )
    row = cur.fetchone()
    if row is not None:
        if not row["key_active"] or not row["user_active"]:
            conn.close()
            return ("user-denied", row["username"], row["user_id"])
        cur.execute("UPDATE api_keys SET last_used = ? WHERE id = ?;", (_utcnow_iso(), row["id"]))
        conn.commit()
        conn.close()
        return ("user", row["username"], row["user_id"])
    conn.close()
    # Legacy global key (transition; deprecated -- see API_INSTRUCTIONS.md).
    stored = get_api_key()
    if stored and secrets.compare_digest(raw_key, stored):
        return ("global", None, None)
    return None


def log_api_call(method, path, kind, username, status):
    """Append one row to the api_audit log (per-user attribution for
    kind='user'; username is NULL for kind='global')."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO api_audit (ts, method, path, kind, username, status) VALUES (?, ?, ?, ?, ?, ?);",
        (_utcnow_iso(), method, path, kind, username, status),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Password verification over the users table (Phase 3 step 2).
#
# app_name is the username of the account backing a module login ('admin',
# 'pricing', 'offer', 'rent') -- the same identifiers the legacy per-app
# password gates used, so existing call sites (module login routes, admin
# confirm-password flows) work unchanged, now backed by hashed users rows.
# A row that still carries a LEGACY PLAINTEXT value (e.g. a pre-Phase-3
# database restored over this one) is verified by constant-time compare and
# transparently rehashed on the first successful login.
# ---------------------------------------------------------------------------

WERKZEUG_HASH_METHODS = ("scrypt", "pbkdf2")


def _is_werkzeug_hash(stored):
    """True when stored looks like a werkzeug generate_password_hash output.

    Werkzeug serializes as 'method[:params]$salt$hash' (>= 2 '$' separators;
    e.g. werkzeug 3.1 scrypt -> 'scrypt:32768:8:1$<salt>$<hash>'). A legacy
    plaintext value never starts with a known hash method name.
    """
    if not stored or stored.count("$") < 2:
        return False
    method = stored.split("$", 1)[0].split(":", 1)[0]
    return method in WERKZEUG_HASH_METHODS


def get_user(username, include_inactive=False):
    """Fetch one user row by username (None when missing/inactive)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ?;", (username,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    if not include_inactive and not row["is_active"]:
        return None
    return row


def check_password(app_name, input_password):
    """
    Verify input_password against the account's stored password hash,
    rehashing transparently when the row still holds a legacy plaintext.
    """
    if not input_password:
        return False

    user = get_user(app_name)
    if user is None:
        return False

    stored = user["password_hash"]

    if _is_werkzeug_hash(stored):
        return check_password_hash(stored, input_password)

    # Legacy plaintext row (pre-Phase-3 restore): compare, then upgrade.
    if secrets.compare_digest(stored, input_password):
        set_password(app_name, input_password)
        return True
    return False


def set_password(app_name, new_password):
    """
    Store a fresh werkzeug hash for the given account (username).
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET password_hash = ? WHERE username = ?;",
        (generate_password_hash(new_password), app_name),
    )
    conn.commit()
    conn.close()


def get_user_by_id(user_id):
    """Fetch one ACTIVE user row by id (None when missing/inactive)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ? AND is_active = 1;", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


# ----------
# Login audit + in-process rate limiting / lockout (Phase 3 step 8).
#
# No Redis, no extra services: failure tracking is a module-level dict keyed
# by (ip, username) guarded by a threading.Lock (the WSGI server serves
# requests on threads). Sliding window: LOGIN_WINDOW_SECONDS counts failures;
# at LOGIN_MAX_FAILURES the (ip, username) pair is locked out for
# LOGIN_LOCKOUT_SECONDS. Success clears the pair; stale entries are pruned
# lazily so the dict cannot grow unboundedly.
# ----------

LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_LOCKOUT_SECONDS = 15 * 60

_login_failures = {}  # (ip, username) -> [timestamps of recent failures]
_login_lock = threading.Lock()


def _prune_failures(now, entries):
    return [t for t in entries if now - t < LOGIN_WINDOW_SECONDS]


def is_login_locked(username, ip):
    """(locked, seconds_remaining) for this (ip, username) pair."""
    now = time.time()
    with _login_lock:
        entries = _prune_failures(now, _login_failures.get((ip, username), []))
        _login_failures[(ip, username)] = entries
        if len(entries) >= LOGIN_MAX_FAILURES:
            oldest = entries[0]
            remaining = int(LOGIN_LOCKOUT_SECONDS - (now - oldest))
            return True, max(remaining, 1)
    return False, 0


def register_login_failure(username, ip):
    now = time.time()
    with _login_lock:
        key = (ip, username)
        entries = _prune_failures(now, _login_failures.get(key, []))
        entries.append(now)
        _login_failures[key] = entries[-LOGIN_MAX_FAILURES:]


def clear_login_failures(username, ip):
    with _login_lock:
        _login_failures.pop((ip, username), None)


def log_login_attempt(username, ip, success, detail):
    """Append one row to login_audit (Phase 3 step 8). Never raises."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO login_audit (ts, username, ip, success, detail) VALUES (?, ?, ?, ?, ?);",
            (_utcnow_iso(), username, ip, 1 if success else 0, detail or ""),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # auditing must never break the login response


def attempt_login(username, password):
    """Verify credentials for the unified login; return the user row or None.

    Deactivated and unknown accounts are indistinguishable on purpose (no
    user enumeration). The password verification itself (including the
    transparent legacy-plaintext rehash) lives in check_password; audit and
    lockout happen around this call in the login route, which owns the
    request context (client IP).
    """
    if not username or not password:
        return None
    user = get_user(username)
    if user is None:
        return False
    if not check_password(username, password):
        return None
    conn = get_db()
    conn.execute(
        "UPDATE users SET last_login = ? WHERE id = ?;",
        (_utcnow_iso(), user["id"]),
    )
    conn.commit()
    conn.close()
    return get_user(username)


def change_own_password(user_id, current_password, new_password, confirm_password):
    """Self-service password change. Returns (ok, error_message).

    Requires the CURRENT password (even when the change was forced by
    must_change_password), enforces the same 8-character minimum as the
    admin password flows, and clears the must_change_password flag.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ? AND is_active = 1;", (user_id,))
    user = cur.fetchone()
    if user is None:
        conn.close()
        return False, "Account not found."

    stored = user["password_hash"]
    if _is_werkzeug_hash(stored):
        if not check_password_hash(stored, current_password or ""):
            conn.close()
            return False, "Current password is incorrect."
    elif not secrets.compare_digest(stored, current_password or ""):
        conn.close()
        return False, "Current password is incorrect."

    if not new_password or len(new_password) < 8:
        conn.close()
        return False, "New password must be at least 8 characters."
    if new_password != confirm_password:
        conn.close()
        return False, "New passwords did not match."

    cur.execute(
        "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?;",
        (generate_password_hash(new_password), user_id),
    )
    conn.commit()
    conn.close()
    return True, None


LEGACY_PASSWORD_KEYS = (
    "admin_password",
    "pricing_password",
    "offer_password",
    "rent_password",
)


# ---------------------------------------------------------------------------
# User management (Phase 3 step 6) -- used by the admin Users UI. Sensitive
# actions re-confirm the ACTING admin's own password via
# confirm_current_password(); invariants: nobody deactivates/demotes
# themselves, and the LAST ACTIVE admin cannot be deactivated or demoted
# (lockout protection). Users are deactivated, never deleted.
# ---------------------------------------------------------------------------

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,32}$")
MIN_PASSWORD_LEN = 8


def confirm_current_password(user_id, password):
    """True when the given password matches the ACTING user's own hash."""
    if not password:
        return False
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM users WHERE id = ? AND is_active = 1;", (user_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        return False
    stored = row["password_hash"]
    if _is_werkzeug_hash(stored):
        return check_password_hash(stored, password)
    return secrets.compare_digest(stored, password)


def list_users():
    """All user rows ordered by username (admin Users UI listing)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users ORDER BY username ASC;")
    rows = cur.fetchall()
    conn.close()
    return rows


def count_active_admins():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = 1;")
    row = cur.fetchone()
    conn.close()
    return row["n"]


def create_user(username, password, confirm_password, role="staff"):
    """Create an account. Returns (ok, error_message_or_username).

    New staff accounts must change their password on first login, exactly
    like the migrated ones.
    """
    username = (username or "").strip()
    if not USERNAME_RE.match(username or ""):
        return False, "Username must be 3-32 characters (letters, digits, . _ -)."
    if role not in ("admin", "staff"):
        return False, "Role must be 'admin' or 'staff'."
    if not password or len(password) < MIN_PASSWORD_LEN:
        return False, f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if password != confirm_password:
        return False, "Passwords did not match."

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role, is_active,
                               must_change_password, created_at)
            VALUES (?, ?, ?, 1, ?, ?);
            """,
            (
                username,
                generate_password_hash(password),
                role,
                1 if role != "admin" else 0,
                _utcnow_iso(),
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False, f"Username '{username}' already exists."
    conn.close()
    return True, username


def set_user_active(acting_user_id, target_user_id, active):
    """Activate/deactivate an account. Returns (ok, error_message).

    Guards: nobody deactivates themselves; the last active admin cannot be
    deactivated.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?;", (target_user_id,))
    target = cur.fetchone()
    if target is None:
        conn.close()
        return False, "User not found."
    if not active:
        if target["id"] == acting_user_id:
            conn.close()
            return False, "You cannot deactivate your own account."
        if target["role"] == "admin" and target["is_active"] and count_active_admins() <= 1:
            conn.close()
            return False, "Cannot deactivate the last active admin."
    cur.execute("UPDATE users SET is_active = ? WHERE id = ?;", (1 if active else 0, target_user_id))
    conn.commit()
    conn.close()
    return True, None


def change_user_role(acting_user_id, target_user_id, role):
    """Change an account's role. Returns (ok, error_message).

    Guards: nobody changes their own role; the last active admin cannot be
    demoted to staff.
    """
    if role not in ("admin", "staff"):
        return False, "Role must be 'admin' or 'staff'."
    if target_user_id == acting_user_id:
        return False, "You cannot change your own role."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?;", (target_user_id,))
    target = cur.fetchone()
    if target is None:
        conn.close()
        return False, "User not found."
    if (
        target["role"] == "admin"
        and target["is_active"]
        and role != "admin"
        and count_active_admins() <= 1
    ):
        conn.close()
        return False, "Cannot demote the last active admin."
    cur.execute("UPDATE users SET role = ? WHERE id = ?;", (role, target_user_id))
    conn.commit()
    conn.close()
    return True, None


def admin_reset_user_password(acting_user_id, target_user_id, new_password):
    """Admin-set password for another account. Returns (ok, error_message).

    The target must change the password again on next login -- EXCEPT when
    the admin resets their own password (already authenticated).
    """
    if not new_password or len(new_password) < MIN_PASSWORD_LEN:
        return False, f"Password must be at least {MIN_PASSWORD_LEN} characters."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username FROM users WHERE id = ?;", (target_user_id,))
    target = cur.fetchone()
    if target is None:
        conn.close()
        return False, "User not found."
    must_change = 0 if target_user_id == acting_user_id else 1
    cur.execute(
        "UPDATE users SET password_hash = ?, must_change_password = ? WHERE id = ?;",
        (generate_password_hash(new_password), must_change, target_user_id),
    )
    conn.commit()
    conn.close()
    return True, None


def scrub_legacy_password_keys(cur):
    """Delete the four legacy '{app}_password' rows from global_settings.

    Phase 3 end state: no plaintext passwords at rest anywhere. The values
    only exist as hashed users rows after seeding; the keys must not linger
    (and must not survive a restore of a pre-Phase-3 backup either).
    """
    cur.executemany(
        "DELETE FROM global_settings WHERE key = ?;",
        [(key,) for key in LEGACY_PASSWORD_KEYS],
    )
