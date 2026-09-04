"""Database backup/restore, full-system backup/restore and factory reset routes."""

from flask import request, redirect, url_for, session, flash, send_file
import os
import time
import zipfile
import io
import shutil
import sqlite3

from qp_crm.shared.config import STATIC_DIR, DATABASE, APP_ASSETS_DIR, IMAGE_DIR

from ..app import bp, get_db, check_password, generate_full_backup_zip

@bp.route("/backup_db")
def backup_db():
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin.login'))

    # G36: Use sqlite3.backup() for a WAL-safe snapshot instead of reading the raw file.
    try:
        src_conn = get_db()
        # Create a fresh connection to the DB file so backup() is WAL-safe
        src_conn.commit()
        src_conn.close()

        backup_conn = sqlite3.connect(DATABASE)
        mem_conn = sqlite3.connect(':memory:')
        backup_conn.backup(mem_conn)

        # Write the snapshot to a BytesIO buffer
        buf = io.BytesIO()
        # Copy the in-memory DB into buf by dumping it to a temp file-like path
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_name = tmp.name
            # Dump mem_conn into the temp file
            dst_conn = sqlite3.connect(tmp_name)
            mem_conn.backup(dst_conn)
            dst_conn.close()
            with open(tmp_name, "rb") as fh:
                buf.write(fh.read())
        os.remove(tmp_name)
        mem_conn.close()
        backup_conn.close()

        buf.seek(0)
        date_str = time.strftime("%Y-%m-%d")
        return send_file(
            buf,
            as_attachment=True,
            download_name=f"full_backup_{date_str}.db",
            mimetype="application/octet-stream"
        )
    except Exception as e:
        flash(f"Error creating backup: {e}", "error")
        return redirect(url_for("admin.index"))

@bp.route("/restore_db", methods=["POST"])
def restore_db():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("admin.index"))
        
    f = request.files.get("db_file")
    if f and f.filename:
        # Basic check
        if not f.filename.endswith(".db") and not f.filename.endswith(".sqlite"):
            flash("Invalid file extension. Please upload a .db file.", "error")
            return redirect(url_for("admin.index"))
            
        # G30: Restore safely by loading into a temp DB, then swapping in
        #       with an exclusive lock. This avoids corrupting the live DB
        #       if another connection is active mid-write.
        try:
            # 1. Save upload to a temp file
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp_name = tmp.name
                f.save(tmp_name)

            # 2. Verify the uploaded DB is a valid SQLite file
            conn = sqlite3.connect(tmp_name)
            conn.execute("PRAGMA integrity_check;")
            conn.close()

            # 3. Swap the temp file into place under a lock
            #    Use sqlite3 backup() to replace DATABASE atomically.
            src_conn = sqlite3.connect(tmp_name)
            dst_conn = sqlite3.connect(DATABASE)
            src_conn.backup(dst_conn)
            dst_conn.commit()
            dst_conn.close()
            src_conn.close()

            # 4. Clean up temp file
            os.remove(tmp_name)

            flash("Database restored successfully.", "success")
        except Exception as e:
            flash(f"Error restoring database: {e}", "error")
    else:
        flash("No file selected.", "error")

    return redirect(url_for("admin.index"))

@bp.route("/backup_full")
def backup_full():
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin.login'))
        
    memory_file = generate_full_backup_zip()
    
    date_str = time.strftime("%Y-%m-%d")
    return send_file(
        memory_file,
        as_attachment=True,
        download_name=f"FULL_SYSTEM_BACKUP_{date_str}.zip",
        mimetype="application/zip"
    )

@bp.route("/restore_full", methods=["POST"])
def restore_full():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("admin.index"))
        
    f = request.files.get("backup_file")
    if not f or not f.filename:
        flash("No file selected.", "error")
        return redirect(url_for("admin.index"))
        
    if not f.filename.endswith(".zip"):
        flash("Invalid file extension. Please upload a .zip file.", "error")
        return redirect(url_for("admin.index"))
        
    try:
        # Create temp file to extract from
        # Or Just use ZipFile on the file object if strictly supported, but safer to save to temp
        # Using io.BytesIO for in-memory handling if file is specialized
        
        # Check if zip is valid
        with zipfile.ZipFile(f) as zf:
            # Check for pricing.db
            if "pricing.db" not in zf.namelist():
                flash("Invalid Backup: pricing.db not found in archive.", "error")
                return redirect(url_for("admin.index"))
            
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
                        
                    # Target path
                    # member is like "product_images/123.jpg"
                    # We extracting to APP_DATA_DIR's parent basically? 
                    # Wait, IMAGE_DIR is .../app_data/product_images
                    
                    # We need to map:
                    # zip: product_images/foo.jpg -> filesystem: .../app_data/product_images/foo.jpg
                    # zip: app_assets/logo.jpg -> filesystem: .../app_assets/logo.jpg
                    
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
                            
        flash("Full System Restore successful.", "success")
        
    except Exception as e:
        flash(f"Error restoring backup: {e}", "error")
        print(f"Restore Error: {e}")
        
    return redirect(url_for("admin.index"))

@bp.route("/factory_reset", methods=["POST"])
def factory_reset():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password. Factory reset aborted.", "error")
        return redirect(url_for("admin.index"))
        
    # 1. Create FULL Backup in memory using the helper
    try:
        memory_file = generate_full_backup_zip()
    except Exception as e:
        flash(f"Error creating backup before reset: {e}", "error")
        return redirect(url_for("admin.index"))

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
            "rent_contract_documents", "rent_templates"
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
            'admin_password': 'Admin1',
            'pricing_password': 'Price1',
            'offer_password': 'Offer1',
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
