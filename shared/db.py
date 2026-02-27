import sqlite3
from .config import DATABASE

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
    return conn
