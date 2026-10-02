import re
import sqlite3
import unicodedata

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
    return conn
