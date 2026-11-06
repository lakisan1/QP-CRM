import re
import sqlite3
import unicodedata
from datetime import datetime, timezone

from flask import g, has_request_context

from .config import DATABASE


def _sql_norm(value):
    """SQLite scalar 'norm()' — the fuzzy-search key (2026-09-24 user
    request): casefold + strip diacritics (ć->c, š->s) + punctuation
    dropped (@/+ kept for email/phone) + whitespace squeezed. Registered
    on EVERY connection in get_db(), so any query can write
    norm(column) LIKE ? and match 'Cacak' against 'Čačak', '064 123 456'
    against '064/123-456', 'Beograd...' against 'Beograd'.
    """
    if value is None:
        return ""
    s = " ".join(str(value).split()).casefold()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^\w\s@+]", "", s)
    return " ".join(s.split())


def _audit_now_iso():
    """UTC ISO-8601 timestamp for audit rows. Matches auth._utcnow_iso but
    lives here so db.py does not import auth (auth imports db -> cycle)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    # Increase timeout to 20 seconds to prevent "database is locked" errors
    conn = sqlite3.connect(DATABASE, timeout=20.0)
    conn.row_factory = sqlite3.Row
    # Enforce foreign keys for data integrity
    conn.execute("PRAGMA foreign_keys = ON;")
    # Enable WAL mode for better concurrency (multiple readers + 1 writer)
    conn.execute("PRAGMA journal_mode = WAL;")
    # Set synchronous to NORMAL for better performance with WAL
    conn.execute("PRAGMA synchronous = NORMAL;")
    # Fuzzy-search helper usable in any SQL: norm(col) LIKE '%term%'
    conn.create_function("norm", 1, _sql_norm)
    # Audit context (P-6 User logs): expose the acting user to the AFTER-*
    # audit triggers via scalar functions. Values are captured at connection
    # open; get_db() opens a FRESH connection per call (no pooling), so a
    # value can never leak between requests. Outside a request context
    # (bootstrap, seeds, scripts) they return NULL/'system'.
    if has_request_context():
        user_id = g.get("audit_user_id")
        username = g.get("audit_username")
        source = g.get("audit_source", "web")
    else:
        user_id = None
        username = None
        source = "system"
    conn.create_function("audit_user_id", 0, lambda uid=user_id: uid)
    conn.create_function("audit_username", 0, lambda uname=username: uname)
    conn.create_function("audit_source", 0, lambda src=source: src)
    conn.create_function("audit_now", 0, _audit_now_iso)
    return conn
