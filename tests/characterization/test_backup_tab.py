"""Admin -> Backup tab: quick backups (local restore points).

Pins the update-system + backup-tab contract (user decisions, board cards):

* POST /admin/backup_quick writes a WAL-safe quick-<ts>.db snapshot into
  BACKUP_DIR (the server-side 'backups/' folder) — the SAME mechanism the
  admin download used and deploy.sh's pre-deploy snapshot uses;
* /admin/backup lists quick-*, pre-deploy-* and pre-rollback-* snapshots
  (newest first) with kind, timestamp and size — the restore-point table;
* download serves the exact stored bytes; restore replaces the live DB via
  sqlite3.backup() and re-runs the auth init (a restored file may predate
  the users table); BOTH restore and delete require the acting admin's
  password (the DB carries the user accounts);
* restore takes its own 'pre-restore-<ts>.db' safety snapshot FIRST — a
  restore is itself undoable;
* retention: the 30 newest quick-* are kept; deploy.sh/rollback.sh snapshots
  are never pruned by the app (their scripts own their retention);
* path traversal on the <name> segment is rejected (400);
* the old DB-only download/upload pair (backup_db / restore_db) is REMOVED —
  the quick backup is the DB-only backup, server-side and listable.
"""

import os
import sqlite3
import time

import pytest

from qp_crm.shared.config import BACKUP_DIR, DATABASE


def _backup_names():
    if not os.path.isdir(BACKUP_DIR):
        return []
    return sorted(n for n in os.listdir(BACKUP_DIR) if n.endswith(".db"))


@pytest.fixture()
def clean_backup_dir():
    """Point the tests at an empty backup dir (whatever BACKUP_DIR is patched
    to) and clean up afterwards."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for n in os.listdir(BACKUP_DIR):
        os.remove(os.path.join(BACKUP_DIR, n))
    yield BACKUP_DIR
    for n in os.listdir(BACKUP_DIR):
        try:
            os.remove(os.path.join(BACKUP_DIR, n))
        except OSError:
            pass


def _csrf(client):
    with client.session_transaction() as session:
        if not session.get("_csrf_token"):
            import secrets
            session["_csrf_token"] = secrets.token_hex(16)
        return session["_csrf_token"]


def test_backup_page_lists_snapshots_by_kind(admin_client, clean_backup_dir):
    """The page shows quick + update-system snapshots, newest first, with kind."""
    ts = time.strftime("%Y%m%d-%H%M%S")
    for name in (f"quick-{ts}.db", f"pre-deploy-{ts}.db", f"pre-rollback-{ts}.db"):
        sqlite3.connect(os.path.join(clean_backup_dir, name)).close()

    page = admin_client.get("/admin/backup")
    assert page.status_code == 200
    html = page.data.decode()
    assert "quick-" in html and "pre-deploy-" in html and "pre-rollback-" in html
    # kind labels distinguish app-made restore points from update-system ones
    assert "pre-deploy (update)" in html


def test_backup_quick_creates_wal_safe_snapshot(admin_client, clean_backup_dir):
    resp = admin_client.post("/admin/backup_quick",
                             data={"_csrf_token": _csrf(admin_client)})
    assert resp.status_code == 302
    names = [n for n in _backup_names() if n.startswith("quick-")]
    assert len(names) == 1
    # the snapshot is a valid SQLite file with the users table
    conn = sqlite3.connect(os.path.join(clean_backup_dir, names[0]))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "users" in tables


def test_backup_quick_download_serves_exact_bytes(admin_client, clean_backup_dir):
    src = os.path.join(clean_backup_dir, "quick-test.db")
    sqlite3.connect(src).execute("CREATE TABLE t(x)").close()  # marker table
    expected = open(src, "rb").read()

    resp = admin_client.get("/admin/backup_quick/quick-test.db/download")
    assert resp.status_code == 200
    assert resp.data == expected


def test_backup_quick_download_rejects_traversal(admin_client):
    assert admin_client.get(
        "/admin/backup_quick/..%2F..%2Fapp_data%2Fpricing.db/download").status_code == 400
    assert admin_client.get(
        "/admin/backup_quick/not-a-backup.txt/download").status_code == 400


def test_backup_quick_restore_requires_password(admin_client, clean_backup_dir):
    admin_client.post("/admin/backup_quick", data={"_csrf_token": _csrf(admin_client)})
    name = next(n for n in _backup_names() if n.startswith("quick-"))

    # wrong password → redirect, DB untouched
    resp = admin_client.post(f"/admin/backup_quick/{name}/restore",
                             data={"_csrf_token": _csrf(admin_client),
                                   "current_admin_password": "wrong"})
    assert resp.status_code == 302
    assert not any(n.startswith("pre-restore-") for n in _backup_names())


def test_backup_quick_restore_swaps_db_and_takes_safety_snapshot(
        admin_client, clean_backup_dir, conn_factory):
    # make a quick backup, then mutate the live DB afterwards
    admin_client.post("/admin/backup_quick", data={"_csrf_token": _csrf(admin_client)})
    name = next(n for n in _backup_names() if n.startswith("quick-"))

    with conn_factory() as conn:
        conn.execute(
            "INSERT INTO global_settings (key, value) VALUES ('backup_tab_marker', 'after-backup')")

    # restore → the marker disappears, a pre-restore snapshot appears
    resp = admin_client.post(f"/admin/backup_quick/{name}/restore",
                             data={"_csrf_token": _csrf(admin_client),
                                   "current_admin_password": "Admin1"})
    assert resp.status_code == 302

    with conn_factory() as conn:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key='backup_tab_marker'").fetchone()
    assert row is None, "restore did not roll the DB back to the quick backup"

    safety = [n for n in _backup_names() if n.startswith("pre-restore-")]
    assert len(safety) == 1, "restore must snapshot the CURRENT state first"


def test_backup_quick_retention_keeps_30(admin_client, clean_backup_dir):
    # seed 32 old quick backups; the POST prunes to the 30 newest + makes one
    for i in range(32):
        sqlite3.connect(os.path.join(
            clean_backup_dir, f"quick-2026010{i % 10}-0000{i:02d}.db")).close()
    admin_client.post("/admin/backup_quick", data={"_csrf_token": _csrf(admin_client)})
    quicks = [n for n in _backup_names() if n.startswith("quick-")]
    assert len(quicks) == 30


def test_backup_quick_delete_requires_password_and_works(admin_client, clean_backup_dir):
    src = os.path.join(clean_backup_dir, "quick-doomed.db")
    sqlite3.connect(src).close()

    resp = admin_client.post("/admin/backup_quick/quick-doomed.db/delete",
                             data={"_csrf_token": _csrf(admin_client),
                                   "current_admin_password": "wrong"})
    assert resp.status_code == 302
    assert os.path.isfile(src), "wrong password must not delete"

    resp = admin_client.post("/admin/backup_quick/quick-doomed.db/delete",
                             data={"_csrf_token": _csrf(admin_client),
                                   "current_admin_password": "Admin1"})
    assert resp.status_code == 302
    assert not os.path.isfile(src)


def test_removed_db_only_routes_are_gone(admin_client):
    """The DB-only download/upload pair was removed (user decision): the
    quick backup IS the DB-only backup — server-side and listable."""
    assert admin_client.get("/admin/backup_db").status_code == 404
    assert admin_client.get("/admin/restore_db").status_code == 404
