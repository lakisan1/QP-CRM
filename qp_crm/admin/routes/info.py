"""Admin -> About: software version and runtime info in one place.

Read-only page. Sources of truth:
- APP_VERSION (shared/config.py) — bumped with every release tag
- APP_BUILD_COMMIT (env QP_BUILD_COMMIT) — injected by CI at image build
- backups/last-deployed-tag — the image tag deploy.sh last recorded
  (absent on bare-metal/dev runs)
- live DB counts — quick health-at-a-glance numbers
"""

import os
import shutil
import sqlite3
import sys

from flask import render_template

from qp_crm.shared.config import APP_VERSION, APP_BUILD_COMMIT, DATABASE, BACKUP_DIR

from ..app import bp, get_db


def _running_image_tag():
    """The image tag deploy.sh recorded at the last deploy (or None).

    deploy.sh writes backups/last-deployed-tag AFTER a successful deploy,
    so it reflects what is actually running (not what is merely pulled).
    """
    path = os.path.join(BACKUP_DIR, "last-deployed-tag")
    try:
        with open(path, encoding="utf-8") as f:
            tag = f.read().strip()
            return tag or None
    except OSError:
        return None


def _db_counts():
    """Row counts for the at-a-glance numbers; tolerant of a fresh DB."""
    counts = {}
    tables = {
        "users": "Users",
        "products": "Products",
        "offers": "Offers",
        "contracts": "Rent contracts",
        "contacts": "Contacts",
    }
    db = get_db()
    for table, label in tables.items():
        try:
            row = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[label] = row[0] if row else 0
        except sqlite3.Error:
            counts[label] = 0  # table not migrated yet (fresh install)
    return counts


@bp.route("/about", methods=["GET"])
def about_page():
    short_commit = APP_BUILD_COMMIT[:12] if APP_BUILD_COMMIT else None
    return render_template(
        "admin/about.html",
        active="about",
        app_version=APP_VERSION,
        build_commit=short_commit,
        image_tag=_running_image_tag(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        db_size_mb=round(os.path.getsize(DATABASE) / (1024 * 1024), 1)
        if os.path.exists(DATABASE) else 0,
        db_engine="SQLite (WAL)",
        counts=_db_counts(),
    )
