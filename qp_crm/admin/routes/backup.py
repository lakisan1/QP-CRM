"""Database backup/restore, quick backups (restore points) and factory reset routes.

Auth is enforced once at the blueprint level (bp.before_request
require_role("admin") in admin/app.py); the per-route
session['admin_authenticated'] checks removed here were pre-Phase-3
leftovers that read a flag unified login never sets, so even a logged-in
admin's backup download was redirected to /admin/login.

Admin -> Backup tab (this module's /backup page) replaces the old
dashboard-embedded Backup card:

* "Quick backup" — a WAL-safe DB snapshot saved ON THE SERVER into
  BACKUP_DIR (root 'backups/'). Same sqlite3.backup() mechanism the admin
  download and deploy.sh's pre-deploy snapshot use. These are the local
  restore points; the deploy scripts use the same folder.
* "Full system backup (.zip)" — the generate_full_backup_zip download for
  MANUAL backups on other servers / data migration (DB + images + assets).
* Restore from quick backup (one click, password-confirmed) and restore
  from an uploaded .zip.

The old "DB-only download/upload" pair was removed (user decision): the
quick backup IS the DB-only backup — but saved server-side and listable —
and the full .zip already covers everything the DB-only upload did.
"""

from flask import request, redirect, url_for, flash, send_file, abort, render_template
import os
import time
import zipfile
import io
import shutil
import sqlite3

from qp_crm.shared.config import (
    STATIC_DIR, DATABASE, APP_ASSETS_DIR, IMAGE_DIR, BACKUP_DIR,
)

from ..app import bp, get_db, check_password, generate_full_backup_zip

# How many quick backups (restore points) to keep on the server. The oldest
# are pruned after every new quick backup; deploy.sh's pre-deploy snapshots
# keep their own 10-file policy independently.
QUICK_BACKUP_KEEP = 30


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _quick_backup_dir():
    """Ensure BACKUP_DIR exists and return its path."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return BACKUP_DIR


def _list_quick_backups():
    """All quick backups + pre-deploy snapshots, newest first.

    Every entry is a (filename, size_bytes, mtime) tuple. Quick backups are
    named quick-<ts>.db, pre-deploy snapshots pre-deploy-<ts>.db (deploy.sh),
    pre-rollback snapshots pre-rollback-<ts>.db (rollback.sh).
    """
    backup_dir = _quick_backup_dir()
    entries = []
    for name in os.listdir(backup_dir):
        if not name.endswith(".db"):
            continue
        path = os.path.join(backup_dir, name)
        if not os.path.isfile(path):
            continue
        st = os.stat(path)
        entries.append((name, st.st_size, st.st_mtime))
    entries.sort(key=lambda e: e[2], reverse=True)
    return entries


def _wal_safe_snapshot(dest_path):
    """Snapshot DATABASE into dest_path via sqlite3.backup() (WAL-safe)."""
    src = sqlite3.connect(DATABASE)
    dst = sqlite3.connect(dest_path)
    src.backup(dst)
    dst.close()
    src.close()


def _format_size(num_bytes):
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.1f} {unit}" if unit != "B" else f"{num_bytes} B"
        num_bytes /= 1024
    return f"{num_bytes} B"


# ---------------------------------------------------------------------------
# page + full-zip routes (Admin -> Backup tab)
# ---------------------------------------------------------------------------

@bp.route("/backup")
def backup_page():
    """Admin -> Backup: local restore points + manual full-system backup."""
    entries = [
        {
            "name": name,
            "size": _format_size(size),
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime)),
            "kind": (
                "pre-deploy" if name.startswith("pre-deploy-")
                else "pre-rollback" if name.startswith("pre-rollback-")
                else "quick"
            ),
        }
        for (name, size, mtime) in _list_quick_backups()
    ]
    return render_template("admin/backups.html", backups=entries)


@bp.route("/backup_full")
def backup_full():
    """Manual full-system backup (.zip: DB + product images + assets) —
    for keeping copies on OTHER servers / migrations. Not stored locally."""
    memory_file = generate_full_backup_zip()
    date_str = time.strftime("%Y-%m-%d")
    return send_file(
        memory_file,
        as_attachment=True,
        download_name=f"FULL_SYSTEM_BACKUP_{date_str}.zip",
        mimetype="application/zip"
    )


# ---------------------------------------------------------------------------
# quick backups (local restore points)
# ---------------------------------------------------------------------------

@bp.route("/backup_quick", methods=["POST"])
def backup_quick():
    """Create a local restore point (WAL-safe DB snapshot in BACKUP_DIR)."""
    try:
        backup_dir = _quick_backup_dir()
        dest = os.path.join(backup_dir, f"quick-{time.strftime('%Y%m%d-%H%M%S')}.db")
        _wal_safe_snapshot(dest)
        os.chmod(dest, 0o600)
        # prune the oldest quick-* beyond the keep count (snapshots written
        # by deploy.sh/rollback.sh are NOT pruned here — their scripts own
        # their retention)
        quicks = sorted(
            (n for n in os.listdir(backup_dir) if n.startswith("quick-") and n.endswith(".db")),
            reverse=True,
        )
        for old in quicks[QUICK_BACKUP_KEEP:]:
            try:
                os.remove(os.path.join(backup_dir, old))
            except OSError:
                pass
        flash(f"Quick backup created: {os.path.basename(dest)}", "success")
    except Exception as e:
        flash(f"Error creating quick backup: {e}", "error")
    return redirect(url_for("admin.backup_page"))


@bp.route("/backup_quick/<path:name>/download")
def backup_quick_download(name):
    """Download a stored quick backup / snapshot (.db)."""
    if "/" in name or ".." in name or not name.endswith(".db"):
        abort(400)
    path = os.path.join(_quick_backup_dir(), name)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=name,
                     mimetype="application/octet-stream")


@bp.route("/backup_quick/<path:name>/restore", methods=["POST"])
def backup_quick_restore(name):
    """Restore a local restore point. Password-confirmed (the DB carries the
    user accounts — restoring one replaces them all)."""
    current_admin_pass = request.form.get("current_admin_password")
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password. Restore aborted.", "error")
        return redirect(url_for("admin.backup_page"))

    if "/" in name or ".." in name or not name.endswith(".db"):
        abort(400)
    src_path = os.path.join(_quick_backup_dir(), name)
    if not os.path.isfile(src_path):
        flash(f"Backup file not found: {name}", "error")
        return redirect(url_for("admin.backup_page"))

    # Safety net: snapshot the CURRENT state before overwriting it, so a
    # restore is itself undoable.
    try:
        safety = os.path.join(_quick_backup_dir(),
                              f"pre-restore-{time.strftime('%Y%m%d-%H%M%S')}.db")
        _wal_safe_snapshot(safety)
        os.chmod(safety, 0o600)
    except Exception as snap_e:
        flash(f"Restore aborted — could not snapshot current state first: {snap_e}", "error")
        return redirect(url_for("admin.backup_page"))

    try:
        # G30: verify the source is a valid SQLite file, then swap via
        # sqlite3.backup() under the live connection — same mechanism the
        # upload-restore route always used.
        conn = sqlite3.connect(src_path)
        conn.execute("PRAGMA integrity_check;")
        conn.close()

        src_conn = sqlite3.connect(src_path)
        dst_conn = sqlite3.connect(DATABASE)
        src_conn.backup(dst_conn)
        dst_conn.commit()
        dst_conn.close()
        src_conn.close()

        # The restored file may predate the users table (or carry legacy
        # plaintext password keys) — re-run the auth init so the accounts
        # are seeded/migrated and the legacy keys are scrubbed.
        try:
            from ..app import init_users_table
            init_users_table()
        except Exception as auth_e:
            flash(f"Database restored, but auth re-init failed: {auth_e}", "warning")

        flash(f"Restored {name}. Pre-restore safety snapshot: {os.path.basename(safety)}", "success")
    except Exception as e:
        flash(f"Error restoring backup: {e}", "error")

    return redirect(url_for("admin.backup_page"))


@bp.route("/backup_quick/<path:name>/delete", methods=["POST"])
def backup_quick_delete(name):
    """Delete a stored restore point. Password-confirmed (destructive)."""
    current_admin_pass = request.form.get("current_admin_password")
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password. Delete aborted.", "error")
        return redirect(url_for("admin.backup_page"))

    if "/" in name or ".." in name or not name.endswith(".db"):
        abort(400)
    path = os.path.join(_quick_backup_dir(), name)
    if os.path.isfile(path):
        try:
            os.remove(path)
            flash(f"Deleted backup: {name}", "success")
        except Exception as e:
            flash(f"Error deleting backup: {e}", "error")
    else:
        flash(f"Backup file not found: {name}", "error")
    return redirect(url_for("admin.backup_page"))


# ---------------------------------------------------------------------------
# restore from uploaded full backup (.zip) + factory reset
# ---------------------------------------------------------------------------

@bp.route("/restore_full", methods=["POST"])
def restore_full():
    current_admin_pass = request.form.get("current_admin_password")

    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("admin.backup_page"))

    f = request.files.get("backup_file")
    if not f or not f.filename:
        flash("No file selected.", "error")
        return redirect(url_for("admin.backup_page"))

    if not f.filename.endswith(".zip"):
        flash("Invalid file extension. Please upload a .zip file.", "error")
        return redirect(url_for("admin.backup_page"))

    try:
        # Check if zip is valid
        with zipfile.ZipFile(f) as zf:
            # Check for pricing.db
            if "pricing.db" not in zf.namelist():
                flash("Invalid Backup: pricing.db not found in archive.", "error")
                return redirect(url_for("admin.backup_page"))

            # 1. Restore Database
            # We enforce the target to be DATABASE path
            with open(DATABASE, 'wb') as db_out:
                db_out.write(zf.read("pricing.db"))

            # 2. Restore Images and Assets
            # We iterate and extract only if path starts with product_images/ or app_assets/
            for member in zf.namelist():
                if member.startswith("product_images/") or member.startswith("app_assets/"):
                    # Prevent path traversal (simple check)
                    if ".." in member or member.startswith("/"):
                        continue

                    # Determine target directory base
                    target_abs_path = None

                    if member.startswith("product_images/"):
                        # Remove prefix
                        rel = member[len("product_images/"):]
                        if not rel: continue # Directory entry
                        target_abs_path = os.path.join(IMAGE_DIR, rel)

                    elif member.startswith("app_assets/"):
                        rel = member[len("app_assets/"):]
                        if not rel: continue
                        target_abs_path = os.path.join(APP_ASSETS_DIR, rel)

                    if target_abs_path:
                        # Ensure dir exists
                        os.makedirs(os.path.dirname(target_abs_path), exist_ok=True)
                        with open(target_abs_path, "wb") as out_f:
                            out_f.write(zf.read(member))

        # Phase 3: same auth re-init as the quick-restore — the restored
        # pricing.db may predate the users table or carry legacy plaintext
        # password keys.
        try:
            from ..app import init_users_table
            init_users_table()
        except Exception as auth_e:
            flash(f"Backup restored, but auth re-init failed: {auth_e}", "warning")

        flash("Full System Restore successful.", "success")

    except Exception as e:
        flash(f"Error restoring backup: {e}", "error")
        print(f"Restore Error: {e}")

    return redirect(url_for("admin.backup_page"))

@bp.route("/factory_reset", methods=["POST"])
def factory_reset():
    current_admin_pass = request.form.get("current_admin_password")

    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password. Factory reset aborted.", "error")
        return redirect(url_for("admin.backup_page"))

    # 1. Create FULL Backup in memory using the helper
    try:
        memory_file = generate_full_backup_zip()
    except Exception as e:
        flash(f"Error creating backup before reset: {e}", "error")
        return redirect(url_for("admin.backup_page"))

    # 2. Reset Database
    try:
        # Re-open or use existing? Better re-open to be sure.
        conn = get_db()
        cur = conn.cursor()

        # Disable Foreign Keys for deletion
        cur.execute("PRAGMA foreign_keys = OFF;")

        # Truncate tables
        tables_to_clear = [
            "products", "prices", "offers", "offer_items", "brands",
            "category_pricing_defaults", "text_presets", "price_rounding_rules",
            "rent_clients", "rent_equipment", "rent_contracts",
            "rent_contract_documents", "rent_templates",
            # P5-unification: the shared directory resets too (children
            # first -- locations and roles reference contacts)
            "contact_locations", "contact_roles", "contacts",
        ]
        # G31: Use parameterized queries — table names come from a fixed allow-list
        allowed_tables = set(tables_to_clear)
        for table in tables_to_clear:
            if table in allowed_tables:
                cur.execute(f"DELETE FROM {table};")

        # Reset PDF Templates (keep only 'System Default' and make it read-only)
        cur.execute("DELETE FROM pdf_templates WHERE name != 'System Default';")
        cur.execute("UPDATE pdf_templates SET is_readonly = 1 WHERE name = 'System Default';")

        # Reset Global Settings to Defaults
        defaults = {
            'date_format': 'YYYY-MM-DD',
            'theme': 'dark',
            'allow_duplicate_names': 'false',
            'enable_product_discount': 'true',
            'language': 'en',
            'default_vat_percent': '20',
            'default_validity_days': '10',
            'default_country': 'Srbija',
            'email_offer_subject': 'Ponuda br. {offer_number}',
            'email_offer_body': 'Postovani,\n\nU prilogu vam saljemo ponudu br. {offer_number}.\n\nSrdacan pozdrav,\nVas Tim',
            'default_items_per_page': '25',
            'active_pdf_template_id': '0',
            'rent_default_interest_rate': '14.0',
            'rent_default_insurance_rate': '1.13',
            'rent_default_guarantee_rate': '5.0',
            'rent_default_admin_fee': '50.0',
            'rent_default_vat_percent': '20.0',
            'rent_default_salvage_value_percent': '20.0',
            'rent_default_downpayment_percent': '20.0',
            'rent_default_period_months': '48',
        }

        for key, value in defaults.items():
            cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?);", (key, value))

        # Re-seed rent templates from JSON defaults
        try:
            from qp_crm.rent.import_templates import seed_templates
            seed_templates(conn)
        except Exception as seed_e:
            print(f"[factory_reset] Warning: Could not re-seed rent templates: {seed_e}")

        # Re-seed the default price rounding rules -- a fresh boot seeds them
        # when the table is empty (admin.init_rounding_rules_table), so a
        # 'factory reset' must end in the same state (Phase 3: caught by the
        # auth test suite running a reset on the shared test DB).
        try:
            from ..app import init_rounding_rules_table
            init_rounding_rules_table()
        except Exception as rules_e:
            print(f"[factory_reset] Warning: Could not re-seed rounding rules: {rules_e}")

        # Phase 3 + per-user app access: reset user accounts to the four
        # hashed defaults AND materialize their module grants (the same
        # contract as admin.init_users_table), so post-reset staff keep all
        # three apps until the admin trims them again.
        try:
            from qp_crm.shared.auth import (
                scrub_legacy_password_keys,
                seed_default_user_modules,
                seed_users_from_legacy,
            )
            from qp_crm.shared.schema import migrate_users
            cur.execute("DELETE FROM user_modules;")
            cur.execute("DELETE FROM api_keys;")
            cur.execute("DELETE FROM users;")
            migrate_users(cur)
            seed_users_from_legacy(cur)
            seed_default_user_modules(cur)
            scrub_legacy_password_keys(cur)
        except Exception as users_e:
            print(f"[factory_reset] Warning: Could not reset user accounts: {users_e}")

        # Re-enable Foreign Keys
        cur.execute("PRAGMA foreign_keys = ON;")

        conn.commit()
    except Exception as e:
        flash(f"Error resetting database: {e}", "error")
        # conn.rollback()? Sqlite usually doesn't need it if we used commit/close carefully but safer.
    finally:
        if conn: conn.close()

    # 3. Clear Product Images
    try:
        if os.path.exists(IMAGE_DIR):
            for filename in os.listdir(IMAGE_DIR):
                file_path = os.path.join(IMAGE_DIR, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print(f'Failed to delete {file_path}. Reason: {e}')
    except Exception as e:
        flash(f"Warning: Database reset but error clearing images: {e}", "warning")

    # 4. Reset Branding Images
    try:
        defaults_dir = os.path.join(APP_ASSETS_DIR, "defaults")
        if os.path.exists(defaults_dir):
            # 1. Restore Logo to static/img/
            logo_src = os.path.join(defaults_dir, "logo_company.jpg")
            logo_dst_static = os.path.join(STATIC_DIR, "img", "logo_company.jpg")
            logo_dst_assets = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")

            if os.path.exists(logo_src):
                os.makedirs(os.path.dirname(logo_dst_static), exist_ok=True)
                shutil.copy2(logo_src, logo_dst_static)
                shutil.copy2(logo_src, logo_dst_assets)

            # 2. Restore Favicon
            favicon_src = os.path.join(defaults_dir, "favicon.png")
            favicon_dst = os.path.join(APP_ASSETS_DIR, "favicon.png")
            if os.path.exists(favicon_src):
                shutil.copy2(favicon_src, favicon_dst)

            # 3. Restore Footer Image
            footer_src = os.path.join(defaults_dir, "pdf_footer_image.png")
            footer_dst = os.path.join(APP_ASSETS_DIR, "pdf_footer_image.png")
            if os.path.exists(footer_src):
                shutil.copy2(footer_src, footer_dst)
    except Exception as e:
        flash(f"Warning: Database reset but error restoring branding: {e}", "warning")

    # 5. Return the backup ZIP as download
    memory_file.seek(0)
    date_str = time.strftime("%Y-%m-%d_%H%M%S")

    return send_file(
        memory_file,
        as_attachment=True,
        download_name=f"FACTORY_RESET_BACKUP_{date_str}.zip",
        mimetype="application/zip"
    )
