# pyrefly: ignore [missing-import]
from flask import Blueprint, Flask, render_template, request, redirect, url_for, session, flash, send_file
import os
import time
import zipfile
import io
import pathlib
import shutil
import sqlite3

# Directory of the qp_crm package (this file is qp_crm/admin/app.py). Used
# only to seed the System Default PDF template from the filesystem templates
# that moved into the package with the offer module.
PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from qp_crm.shared.config import STATIC_DIR, DATABASE, APP_ASSETS_DIR, IMAGE_DIR
from qp_crm.shared.db import get_db
from qp_crm.shared.auth import check_password, set_password, get_password, get_api_key, generate_api_key, revoke_api_key
from qp_crm.shared.countries import get_country_list
from qp_crm.shared.web import (
    make_auth_hook,
    fetch_mandatory_fields,
    fetch_rent_defaults,
    sort_rent_templates,
    MANDATORY_FIELD_KEYS,
    RENT_DEFAULT_KEYS,
    DEFAULT_RENT_EMAIL,
)

# ---------------------------------------------------------------------------
# Phase 2 stage 1: admin is a Blueprint on the single QP-CRM app -- the last
# classic sub-app, whose port removes DispatcherMiddleware entirely.
#
# The Flask(...) instance, secret key and SESSION_COOKIE_NAME moved to
# main.py (one session/secret/cookie; ADMIN_SECRET_KEY and the admin_session
# cookie are no longer read). The admin_authenticated session flag keeps its
# pre-consolidation name -- it was already module-scoped. Routes keep the
# same URLs via the blueprint's /admin prefix in main.py; endpoints are
# namespaced (admin.index, ...) and templates live under
# admin/templates/admin/.
# ---------------------------------------------------------------------------

bp = Blueprint("admin", __name__, template_folder="templates")

def init_presets_table():
    """DDL lives in shared/schema.py (single source)."""
    from qp_crm.shared.schema import create_admin_tables

    conn = get_db()
    cur = conn.cursor()
    create_admin_tables(cur)
    conn.commit()
    conn.close()

def init_pdf_templates_table():
    """DDL lives in shared/schema.py (single source); the System Default
    row is seeded/refreshed from the filesystem templates as before."""
    from qp_crm.shared.schema import create_admin_tables

    conn = get_db()
    cur = conn.cursor()
    create_admin_tables(cur)
    
    # Try to read current filesystem templates
    # (Phase 2: offer templates are namespaced under offer/templates/offer/;
    # they live inside the qp_crm package since the qp_crm/ package move,
    # while pdf.css stays at the repo root's static/ tree -> STATIC_DIR.)
    templates_dir = os.path.join(PACKAGE_DIR, "offer", "templates", "offer")
    css_path = os.path.join(STATIC_DIR, "css", "pdf.css")
    
    header_html, body_html, footer_html, pdf_css = "", "", "", ""
    try:
        with open(os.path.join(templates_dir, "offer_header_inner.html"), "r") as f:
            header_html = f.read()
        with open(os.path.join(templates_dir, "offer_body_inner.html"), "r") as f:
            body_html = f.read()
        with open(os.path.join(templates_dir, "offer_footer_inner.html"), "r") as f:
            footer_html = f.read()
        with open(css_path, "r") as f:
            pdf_css = f.read()
    except Exception as e:
        print(f"Warning: Could not read templates from filesystem: {e}")

    # Initialize or Update 'System Default' (Read-only)
    cur.execute("SELECT id FROM pdf_templates WHERE name = 'System Default';")
    row = cur.fetchone()
    if not row:
        cur.execute("""
            INSERT INTO pdf_templates (name, header_html, body_html, footer_html, css, is_readonly)
            VALUES (?, ?, ?, ?, ?, 1);
        """, ("System Default", header_html, body_html, footer_html, pdf_css))
    else:
        cur.execute("""
            UPDATE pdf_templates 
            SET header_html=?, body_html=?, footer_html=?, css=?
            WHERE name='System Default';
        """, (header_html, body_html, footer_html, pdf_css))

    # Ensure active_pdf_template_id exists
    cur.execute("SELECT key FROM global_settings WHERE key = 'active_pdf_template_id';")
    if not cur.fetchone():
        cur.execute("INSERT INTO global_settings (key, value) VALUES ('active_pdf_template_id', '0');")
        
    conn.commit()
    conn.close()

def init_rounding_rules_table():
    """DDL lives in shared/schema.py (single source); default rules seeded
    as before."""
    from qp_crm.shared.schema import create_admin_tables

    conn = get_db()
    cur = conn.cursor()
    create_admin_tables(cur)
    
    # Seed if empty
    cur.execute("SELECT COUNT(*) as count FROM price_rounding_rules;")
    if cur.fetchone()["count"] == 0:
        # Default price rules from hardcoded logic
        defaults = [
            ('price', 1000, 50, 'UP'),
            ('price', 10000, 100, 'UP'),
            ('price', 30000, 500, 'UP'),
            ('price', 999999999, 1000, 'UP'),
            # Default discount rules (same as price for now)
            ('discount', 1000, 50, 'UP'),
            ('discount', 10000, 100, 'UP'),
            ('discount', 30000, 500, 'UP'),
            ('discount', 999999999, 1000, 'UP')
        ]
        cur.executemany("""
            INSERT INTO price_rounding_rules (target, limit_val, step_val, method)
            VALUES (?, ?, ?, ?);
        """, defaults)
        
    conn.commit()
    conn.close()

def init_db():
    init_presets_table()
    init_pdf_templates_table()
    init_rounding_rules_table()

# Per-module login hook from shared/web.py (admin_authenticated keeps its
# pre-consolidation module-scoped name).
bp.before_request(make_auth_hook("admin_authenticated", "admin.login"))

def generate_full_backup_zip():
    # Ensure DB is flushed
    conn = get_db()
    conn.commit()
    conn.close()
    
    # Create in-memory zip
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 1. Add Database
        if os.path.exists(DATABASE):
            zf.write(DATABASE, arcname="pricing.db")
            
        # 2. Add Product Images
        # Walk through IMAGE_DIR and add all files
        if os.path.exists(IMAGE_DIR):
            for root, dirs, files in os.walk(IMAGE_DIR):
                for file in files:
                    abs_path = os.path.join(root, file)
                    # rel_path determines the path inside the zip
                    # We want 'product_images/filename.jpg'
                    rel_path = os.path.relpath(abs_path, os.path.dirname(IMAGE_DIR))
                    zf.write(abs_path, arcname=rel_path)

        # 3. Add App Assets (Logos etc)
        if os.path.exists(APP_ASSETS_DIR):
             for root, dirs, files in os.walk(APP_ASSETS_DIR):
                for file in files:
                    abs_path = os.path.join(root, file)
                    # We want 'app_assets/filename.jpg'
                    rel_path = os.path.relpath(abs_path, os.path.dirname(APP_ASSETS_DIR))
                    zf.write(abs_path, arcname=rel_path)
                    
    memory_file.seek(0)
    return memory_file

# Phase 2 stage 5: route groups live in admin/routes/; importing them
# registers their @bp.route functions on the blueprint defined above.
from . import routes  # noqa: E402,F401
