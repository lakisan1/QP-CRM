# pyrefly: ignore [missing-import]
from flask import Blueprint, Flask, render_template, request, redirect, url_for, session, flash, send_file
import os
import sys
import time
import zipfile
import io
import pathlib
import shutil
import sqlite3

# Ensure we can import 'shared' from parent dir
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from shared.config import STATIC_DIR, DATABASE, APP_ASSETS_DIR, IMAGE_DIR
from shared.db import get_db
from shared.auth import check_password, set_password, get_password, get_api_key, generate_api_key, revoke_api_key
from shared.countries import get_country_list

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
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS text_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, -- 'delivery', 'note', 'extra'
            name TEXT NOT NULL,
            content TEXT,
            is_default INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()

def init_pdf_templates_table():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdf_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            header_html TEXT,
            body_html TEXT,
            footer_html TEXT,
            css TEXT,
            is_readonly INTEGER DEFAULT 0
        );
    """)
    
    # Try to read current filesystem templates
    # (Phase 2: offer templates are namespaced under offer/templates/offer/)
    templates_dir = os.path.join(PARENT_DIR, "offer", "templates", "offer")
    css_path = os.path.join(PARENT_DIR, "static", "css", "pdf.css")
    
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
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS price_rounding_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT NOT NULL, -- 'price' or 'discount'
            limit_val REAL NOT NULL,
            step_val REAL NOT NULL,
            method TEXT DEFAULT 'UP' -- 'UP', 'DOWN', 'NEAREST'
        );
    """)
    
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

@bp.before_request
def check_auth():
    if request.endpoint in ('admin.login',):
        return None
    if not session.get('admin_authenticated'):
        return redirect(url_for('admin.login'))

@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pwd = request.form.get("password")
        # Check against 'admin' password
        if check_password("admin", pwd):
            session['admin_authenticated'] = True
            return redirect(url_for('admin.index'))
        else:
            error = "Invalid Admin Password"
    return render_template("admin/admin_login.html", error=error)

@bp.route("/logout")
def logout():
    session.pop('admin_authenticated', None)
    return redirect('/')

@bp.route("/")
def index():
    conn = get_db()
    cur = conn.cursor()
    
    # Get current settings
    cur.execute("SELECT value FROM global_settings WHERE key = 'date_format';")
    row = cur.fetchone()
    current_date_format = row["value"] if row else "YYYY-MM-DD"

    cur.execute("SELECT value FROM global_settings WHERE key = 'theme';")
    row = cur.fetchone()
    current_theme = row["value"] if row else "dark"
    
    cur.execute("SELECT value FROM global_settings WHERE key = 'allow_duplicate_names';")
    row = cur.fetchone()
    allow_duplicate_names = row["value"] if row else "false"

    cur.execute("SELECT value FROM global_settings WHERE key = 'enable_product_discount';")
    row = cur.fetchone()
    enable_product_discount = row["value"] if row else "true"

    cur.execute("SELECT value FROM global_settings WHERE key = 'language';")
    row = cur.fetchone()
    current_language = row["value"] if row else "en"

    cur.execute("SELECT value FROM global_settings WHERE key = 'default_vat_percent';")
    row = cur.fetchone()
    default_vat_percent = row["value"] if row else "20"

    cur.execute("SELECT value FROM global_settings WHERE key = 'default_validity_days';")
    row = cur.fetchone()
    default_validity_days = row["value"] if row else "10"

    cur.execute("SELECT value FROM global_settings WHERE key = 'default_country';")
    row = cur.fetchone()
    default_country = row["value"] if row else "Srbija"

    cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_subject';")
    row = cur.fetchone()
    email_offer_subject = row["value"] if row else "Ponuda br. {offer_number}"

    cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_body';")
    row = cur.fetchone()
    email_offer_body = row["value"] if row else "Postovani,\n\nU prilogu vam saljemo ponudu br. {offer_number}.\n\nSrdacan pozdrav,\nVas Tim"

    cur.execute("SELECT value FROM global_settings WHERE key = 'default_items_per_page';")
    row = cur.fetchone()
    default_items_per_page = row["value"] if row else "25"

    # Fetch rent module defaults
    rent_defaults = {}
    rent_keys = {
        'rent_default_interest_rate': '14.0',
        'rent_default_insurance_rate': '1.13',
        'rent_default_guarantee_rate': '5.0',
        'rent_default_admin_fee': '50.0',
        'rent_default_vat_percent': '20.0',
        'rent_default_salvage_value_percent': '20.0',
        'rent_default_downpayment_percent': '20.0',
        'rent_default_period_months': '48',
    }
    for key, default in rent_keys.items():
        cur.execute("SELECT value FROM global_settings WHERE key = ?;", (key,))
        row = cur.fetchone()
        rent_defaults[key] = row["value"] if row else default

    # Fetch rent email preset
    _DEFAULT_RENT_EMAIL = (
        "Poštovani,\n\n"
        "U prilogu Vam dostavljamo sva dokumenta vezana za zakup opreme.\n\n"
        "Ukoliko ste saglasni, molimo Vas da to potvrdite emailom, kako bismo Vam "
        "poštom poslali potpisane primerke ugovora koje nam na dan ugradnje opreme "
        "vraćate sa Vašim potpisom. Svaki prilog ide u 4 primerka – 2 za Vas i 2 za nas.\n\n"
        "Molimo Vas da popunite i meničko ovlašćenje.\n\n"
        "Uplatu avansa izvršite na osnovu Instrukcija za uplatu avansa, "
        "a nakon toga pratite Plan plaćanja.\n\n"
        "Srdačan pozdrav,\nMarinković-Hofmann d.o.o."
    )
    cur.execute("SELECT value FROM global_settings WHERE key = 'rent_email_preset';")
    row = cur.fetchone()
    rent_email_preset = row["value"] if row else _DEFAULT_RENT_EMAIL

    # Fetch all presets and group by category
    cur.execute("SELECT * FROM text_presets ORDER BY name ASC;")
    all_presets = cur.fetchall()
    presets_by_cat = {'delivery': [], 'payment': [], 'note': [], 'extra': []}
    for p in all_presets:
        if p['category'] in presets_by_cat:
            presets_by_cat[p['category']].append(p)

    # Fetch mandatory fields settings
    mandatory_fields = {}
    for field in ['req_client_address', 'req_client_email', 'req_client_phone', 'req_client_pib', 'req_client_mb']:
        cur.execute("SELECT value FROM global_settings WHERE key = ?;", (field,))
        row = cur.fetchone()
        mandatory_fields[field] = (row["value"] == "true") if row else False

    # API Key info
    api_key_value = get_api_key()
    api_key_exists = api_key_value is not None

    conn.close()

    return render_template(
        "admin/admin_dashboard.html",
        current_date_format=current_date_format,
        current_theme=current_theme,
        allow_duplicate_names=allow_duplicate_names,
        enable_product_discount=enable_product_discount,
        current_language=current_language,
        default_vat_percent=default_vat_percent,
        default_validity_days=default_validity_days,
        default_country=default_country,
        countries=get_country_list(),
        presets_by_cat=presets_by_cat,
        mandatory_fields=mandatory_fields,
        email_offer_subject=email_offer_subject,
        email_offer_body=email_offer_body,
        default_items_per_page=default_items_per_page,
        rent_defaults=rent_defaults,
        rent_email_preset=rent_email_preset,
        timestamp=int(time.time()),
        theme=current_theme,
        api_key_exists=api_key_exists,
        api_key_value=api_key_value
    )

@bp.route("/add_preset", methods=["POST"])
def add_preset():
    category = request.form.get("category")
    name = request.form.get("name")
    content = request.form.get("content")
    is_default = 1 if request.form.get("is_default") else 0

    if not category or not name:
        flash("Category and Name are required.", "error")
        return redirect(url_for("admin.index"))

    conn = get_db()
    cur = conn.cursor()
    
    if is_default:
        # Unset other defaults in same category
        cur.execute("UPDATE text_presets SET is_default = 0 WHERE category = ?;", (category,))
    
    cur.execute("""
        INSERT INTO text_presets (category, name, content, is_default)
        VALUES (?, ?, ?, ?);
    """, (category, name, content, is_default))
    
    conn.commit()
    conn.close()
    
    flash("Preset added successfully.", "success")
    return redirect(url_for("admin.index"))

@bp.route("/delete_preset", methods=["POST"])
def delete_preset():
    preset_id = request.form.get("preset_id")
    if not preset_id:
        return redirect(url_for("admin.index"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM text_presets WHERE id = ?;", (preset_id,))
    conn.commit()
    conn.close()
    
    flash("Preset deleted.", "success")
    return redirect(url_for("admin.index"))

@bp.route("/set_default_preset", methods=["POST"])
def set_default_preset():
    category = request.form.get("category")
    preset_id = request.form.get("preset_id")
    
    if not category or not preset_id:
        return redirect(url_for("admin.index"))

    conn = get_db()
    cur = conn.cursor()
    # Unset others
    cur.execute("UPDATE text_presets SET is_default = 0 WHERE category = ?;", (category,))
    # Set this one
    cur.execute("UPDATE text_presets SET is_default = 1 WHERE id = ?;", (preset_id,))
    conn.commit()
    conn.close()
    
    flash("Default preset updated.", "success")
    return redirect(url_for("admin.index"))

@bp.route("/update_passwords", methods=["POST"])
def update_passwords():
    current_admin_pass = request.form.get("current_admin_password")
    
    # Security check setup
    if not check_password("admin", current_admin_pass):
        flash("Incorrect Request: Invalid current Admin password.", "error")
        return redirect(url_for("admin.index"))

    # Helpers to process changes
    # Each app has new_pass and confirm_pass
    changes = [
        ("admin", request.form.get("new_admin_password"), request.form.get("new_admin_password_confirm")),
        ("pricing", request.form.get("new_pricing_password"), request.form.get("new_pricing_password_confirm")),
        ("offer", request.form.get("new_offer_password"), request.form.get("new_offer_password_confirm")),
        ("rent", request.form.get("new_rent_password"), request.form.get("new_rent_password_confirm")),
    ]

    updated_count = 0
    
    for app_name, new_p, confirm_p in changes:
        if new_p: # if not empty
            if len(new_p) < 8:
                flash(f"Error: Password for {app_name} must be at least 8 characters.", "error")
                return redirect(url_for("admin.index"))
            if new_p != confirm_p:
                flash(f"Error: Passwords for {app_name} did not match.", "error")
                return redirect(url_for("admin.index"))
            set_password(app_name, new_p)
            updated_count += 1
            
    if updated_count > 0:
        flash(f"Successfully updated {updated_count} password(s).", "success")
    else:
        flash("No password changes requested.", "success")
        
    return redirect(url_for("admin.index"))
        
@bp.route("/upload_logo", methods=["POST"])
def upload_logo():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("admin.index"))
        
    f = request.files.get("logo_file")
    if f and f.filename:
        # Save to static/img/logo_company.jpg (OVERWRITE)
        # Verify extension
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png']:
            flash("Logo must be JPG or PNG.", "error")
            return redirect(url_for("admin.index"))
            
        target_dir = os.path.join(STATIC_DIR, "img")
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, "logo_company.jpg")
        
        try:
            # If PNG, convert to JPG to match the .jpg filename (G34)
            if ext == '.png':
                from PIL import Image
                img = Image.open(f.stream).convert("RGB")
                img.save(target_path, "JPEG")
            else:
                # Save to static/img/logo_company.jpg
                f.save(target_path)
            
            # ALSO Save to app_assets/logo_company.jpg (which PDF template uses)
            asset_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
            import shutil
            shutil.copy2(target_path, asset_path)
            
            flash("Logo updated successfully.", "success")
        except Exception as e:
            flash(f"Error saving logo: {e}", "error")
    else:
        flash("No file selected.", "error")

    return redirect(url_for("admin.index"))

@bp.route("/upload_footer", methods=["POST"])
def upload_footer():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("admin.index"))
        
    f = request.files.get("footer_file")
    if f and f.filename:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png']:
            flash("Footer image must be JPG or PNG.", "error")
            return redirect(url_for("admin.index"))
            
        target_path = os.path.join(APP_ASSETS_DIR, "pdf_footer_image.png")
        
        try:
            f.save(target_path)
            flash("Footer image updated successfully.", "success")
        except Exception as e:
            flash(f"Error saving footer image: {e}", "error")
    else:
        flash("No file selected.", "error")

    return redirect(url_for("admin.index"))

@bp.route("/upload_favicon", methods=["POST"])
def upload_favicon():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("admin.index"))
        
    f = request.files.get("favicon_file")
    if f and f.filename:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ['.png']:
            flash("Favicon must be PNG.", "error")
            return redirect(url_for("admin.index"))
            
        target_path = os.path.join(APP_ASSETS_DIR, "favicon.png")
        
        try:
            f.save(target_path)
            flash("Favicon updated successfully.", "success")
        except Exception as e:
            flash(f"Error saving favicon: {e}", "error")
    else:
        flash("No file selected.", "error")

    return redirect(url_for("admin.index"))

@bp.route("/update_settings", methods=["POST"])
def update_settings():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("admin.index"))
        
    date_fmt = request.form.get("date_format")
    theme = request.form.get("theme")
    allow_dup = request.form.get("allow_duplicate_names")
    
    conn = get_db()
    cur = conn.cursor()
    
    if date_fmt:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('date_format', ?);", (date_fmt,))
    
    if theme:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('theme', ?);", (theme,))
        
    # Checkbox: if present = "true", if missing = "false"
    allow_dup_val = "true" if allow_dup == "true" else "false"
    cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('allow_duplicate_names', ?);", (allow_dup_val,))

    enable_prod_disc = request.form.get("enable_product_discount")
    enable_prod_disc_val = "true" if enable_prod_disc == "true" else "false"
    cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('enable_product_discount', ?);", (enable_prod_disc_val,))

    lang = request.form.get("language")
    if lang:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('language', ?);", (lang,))

    vat = request.form.get("default_vat_percent")
    if vat:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('default_vat_percent', ?);", (vat,))

    validity = request.form.get("default_validity_days")
    if validity:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('default_validity_days', ?);", (validity,))
        
    country = request.form.get("default_country")
    if country:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('default_country', ?);", (country,))
        
    email_subject = request.form.get("email_offer_subject")
    if email_subject:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('email_offer_subject', ?);", (email_subject,))

    email_body = request.form.get("email_offer_body")
    # Body can be empty, but let's save it anyway if present in form (even if empty string)
    if email_body is not None:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('email_offer_body', ?);", (email_body,))

    items_per_page = request.form.get("default_items_per_page")
    if items_per_page:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('default_items_per_page', ?);", (items_per_page,))

    # Mandatory fields
    for field in ['req_client_address', 'req_client_email', 'req_client_phone', 'req_client_pib', 'req_client_mb']:
        val = "true" if request.form.get(field) == "true" else "false"
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?);", (field, val))

    # Rent module defaults
    rent_num_keys = [
        'rent_default_interest_rate', 'rent_default_insurance_rate',
        'rent_default_guarantee_rate', 'rent_default_admin_fee',
        'rent_default_vat_percent', 'rent_default_salvage_value_percent',
        'rent_default_downpayment_percent', 'rent_default_period_months',
    ]
    for key in rent_num_keys:
        val = request.form.get(key)
        if val is not None and val.strip() != '':
            cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?);", (key, val.strip()))

    # Rent email preset
    rent_email_preset_val = request.form.get("rent_email_preset")
    if rent_email_preset_val is not None:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('rent_email_preset', ?);", (rent_email_preset_val,))

    # Rent email subject
    rent_email_subject_val = request.form.get("rent_email_subject")
    if rent_email_subject_val is not None:
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('rent_email_subject', ?);", (rent_email_subject_val,))

    conn.commit()
    conn.close()
    
    flash("Settings updated.", "success")
    redirect_to = request.form.get("redirect_to")
    if redirect_to:
        return redirect(redirect_to)
    return redirect(url_for("admin.index"))

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

@bp.route("/pdf_templates")
def list_pdf_templates():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pdf_templates ORDER BY id ASC;")
    templates = cur.fetchall()
    
    cur.execute("SELECT value FROM global_settings WHERE key = 'active_pdf_template_id';")
    row = cur.fetchone()
    active_id = int(row["value"]) if row else 0
    
    conn.close()
    return render_template("admin/pdf_templates.html", templates=templates, active_id=active_id)

@bp.route("/add_pdf_template", methods=["POST"])
def add_pdf_template():
    name = request.form.get("name", "New Template")
    source_id = request.form.get("source_id") # Clone from existing
    
    conn = get_db()
    cur = conn.cursor()
    
    header, body, footer, css = "", "", "", ""
    if source_id:
        cur.execute("SELECT * FROM pdf_templates WHERE id = ?;", (source_id,))
        src = cur.fetchone()
        if src:
            header, body, footer, css = src["header_html"], src["body_html"], src["footer_html"], src["css"]
            
    cur.execute("""
        INSERT INTO pdf_templates (name, header_html, body_html, footer_html, css, is_readonly)
        VALUES (?, ?, ?, ?, ?, 0);
    """, (name, header, body, footer, css))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    flash("Template created.", "success")
    return redirect(url_for("admin.edit_pdf_template", template_id=new_id))

@bp.route("/edit_pdf_template/<int:template_id>", methods=["GET", "POST"])
def edit_pdf_template(template_id):
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == "POST":
        name = request.form.get("name")
        header = request.form.get("header_html")
        body = request.form.get("body_html")
        footer = request.form.get("footer_html")
        css = request.form.get("css")
        
        cur.execute("SELECT is_readonly FROM pdf_templates WHERE id = ?;", (template_id,))
        row = cur.fetchone()
        if row and row["is_readonly"]:
            flash("System template is read-only.", "error")
        else:
            cur.execute("""
                UPDATE pdf_templates 
                SET name=?, header_html=?, body_html=?, footer_html=?, css=?
                WHERE id=?;
            """, (name, header, body, footer, css, template_id))
            conn.commit()
            flash("Template updated.", "success")
            
    cur.execute("SELECT * FROM pdf_templates WHERE id = ?;", (template_id,))
    template = cur.fetchone()
    
    # For preview testing: get all offers
    cur.execute("SELECT id, client_name, offer_number FROM offers ORDER BY date DESC, id DESC;")
    offers = cur.fetchall()
    
    conn.close()
    if not template:
        return "Template not found", 404
        
    return render_template("admin/pdf_template_edit.html", template=template, offers=offers)

import re

@bp.route("/cleanup_images", methods=["POST"])
def cleanup_images():
    current_admin_pass = request.form.get("current_admin_password")
    if not check_password("admin", current_admin_pass):
        flash("Invalid Admin Password", "error")
        return redirect(url_for('admin.index'))

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, name, photo_path FROM products")
    products = cur.fetchall()

    renamed_count = 0
    deleted_count = 0
    missing_count = 0

    valid_paths_in_db = set()

    for p in products:
        pid, pname, pphoto = p[0], p[1], p[2]
        
        if not pphoto:
            continue
            
        # 1. Check if the file physically exists
        old_full_path = os.path.join(IMAGE_DIR, pphoto)
        if not os.path.exists(old_full_path):
            missing_count += 1
            # Opt: we could clear it here, but leaving it as-is is safer
            continue

        # 2. Check if the name needs standardization
        ext = os.path.splitext(pphoto)[1].lower()
        if not ext:
            ext = ".jpg"

        base = (pname or "").strip().lower()
        base = re.sub(r"\s+", "_", base)
        base = re.sub(r"[^a-z0-9_-]", "", base)
        if not base:
             base = "product"

        new_filename = base + ext

        if new_filename != pphoto:
            new_full_path = os.path.join(IMAGE_DIR, new_filename)
            try:
                # Rename file
                os.rename(old_full_path, new_full_path)
                # Update DB
                cur.execute("UPDATE products SET photo_path = ? WHERE id = ?", (new_filename, pid))
                renamed_count += 1
                valid_paths_in_db.add(new_filename)
            except Exception as e:
                print(f"Error renaming {old_full_path} to {new_full_path}: {e}")
                valid_paths_in_db.add(pphoto) # Fallback to tracking old name
        else:
            valid_paths_in_db.add(pphoto)

    conn.commit()
    conn.close()

    # 3. Clean up orphaned files in IMAGE_DIR
    # G35: Only delete a file if it is NOT referenced anywhere else in the DB,
    #      not just in `products`. This avoids deleting shared images.
    conn = get_db()
    cur2 = conn.cursor()
    if os.path.exists(IMAGE_DIR):
        for filename in os.listdir(IMAGE_DIR):
            if filename not in valid_paths_in_db:
                # Check every table that may reference image paths before deleting
                cur2.execute("SELECT COUNT(*) AS c FROM products WHERE photo_path = ?", (filename,))
                used = cur2.fetchone()["c"] > 0
                if not used:
                    # Also check rent equipment photos if that table exists
                    try:
                        cur2.execute("SELECT COUNT(*) AS c FROM rent_equipment WHERE photo_path = ?", (filename,))
                        used = cur2.fetchone()["c"] > 0
                    except Exception:
                        pass
                if not used:
                    file_path = os.path.join(IMAGE_DIR, filename)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                        except Exception as e:
                            print(f"Error removing orphaned image {file_path}: {e}")
    conn.close()

    flash(f"Image Cleanup Complete: {renamed_count} renamed/fixed, {deleted_count} orphaned files deleted, {missing_count} DB records pointing to missing files.", "success")
    return redirect(url_for("admin.index"))

@bp.route("/delete_pdf_template", methods=["POST"])
def delete_pdf_template():
    tpl_id = request.form.get("template_id")
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT is_readonly FROM pdf_templates WHERE id = ?;", (tpl_id,))
    row = cur.fetchone()
    if row and row["is_readonly"]:
        flash("Cannot delete system template.", "error")
    else:
        cur.execute("DELETE FROM pdf_templates WHERE id = ?;", (tpl_id,))
        # If it was active, reset to 0
        cur.execute("SELECT value FROM global_settings WHERE key = 'active_pdf_template_id';")
        r = cur.fetchone()
        if r and r["value"] == str(tpl_id):
            cur.execute("UPDATE global_settings SET value = '0' WHERE key = 'active_pdf_template_id';")
        conn.commit()
        flash("Template deleted.", "success")
        
    conn.close()
    return redirect(url_for("admin.list_pdf_templates"))

@bp.route("/set_active_pdf_template", methods=["POST"])
def set_active_pdf_template():
    tpl_id = request.form.get("template_id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE global_settings SET value = ? WHERE key = 'active_pdf_template_id';", (tpl_id,))
    conn.commit()
    conn.close()
    flash("Active template updated.", "success")
    return redirect(url_for("admin.list_pdf_templates"))

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
            from rent.import_templates import seed_templates
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

@bp.route("/rounding_rules")
def list_rounding_rules():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM price_rounding_rules ORDER BY target ASC, limit_val ASC;")
    rules = cur.fetchall()
    
    rules_by_target = {'price': [], 'discount': []}
    for r in rules:
        if r['target'] in rules_by_target:
            rules_by_target[r['target']].append(r)
            
    conn.close()
    return render_template("admin/rounding_rules.html", rules_by_target=rules_by_target)

@bp.route("/add_rounding_rule", methods=["POST"])
def add_rounding_rule():
    target = request.form.get("target")
    limit_val = float(request.form.get("limit_val") or 0)
    step_val = float(request.form.get("step_val") or 0)
    method = request.form.get("method", "UP")
    
    if not target or limit_val <= 0 or step_val <= 0:
        flash("Invalid rule data.", "error")
        return redirect(url_for("admin.list_rounding_rules"))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO price_rounding_rules (target, limit_val, step_val, method)
        VALUES (?, ?, ?, ?);
    """, (target, limit_val, step_val, method))
    conn.commit()
    conn.close()
    
    flash("Rounding rule added.", "success")
    return redirect(url_for("admin.list_rounding_rules"))

@bp.route("/delete_rounding_rule", methods=["POST"])
def delete_rounding_rule():
    rule_id = request.form.get("rule_id")
    if not rule_id:
        return redirect(url_for("admin.list_rounding_rules"))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM price_rounding_rules WHERE id = ?;", (rule_id,))
    conn.commit()
    conn.close()
    
    flash("Rounding rule deleted.", "success")
    return redirect(url_for("admin.list_rounding_rules"))

# ─────────────────────────────────────────────────────────────────────────────
# API Key Management
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/api_key/generate", methods=["POST"])
def api_key_generate():
    """Generate a new API key (requires admin password)."""
    current_admin_pass = request.form.get("current_admin_password")
    if not check_password("admin", current_admin_pass):
        flash("Invalid Admin Password.", "error")
        return redirect(url_for("admin.index"))

    new_key = generate_api_key()
    flash(f"New API key generated.", "success")
    return redirect(url_for("admin.index"))

@bp.route("/api_key/revoke", methods=["POST"])
def api_key_revoke():
    """Revoke (delete) the current API key (requires admin password)."""
    current_admin_pass = request.form.get("current_admin_password")
    if not check_password("admin", current_admin_pass):
        flash("Invalid Admin Password.", "error")
        return redirect(url_for("admin.index"))

    revoke_api_key()
    flash("API key revoked. All existing API integrations will stop working.", "warning")
    return redirect(url_for("admin.index"))

# ─────────────────────────────────────────────────────────────────────────────
# Rent Master Template Editor (Admin)
# ─────────────────────────────────────────────────────────────────────────────

# Preferred display order for rent templates (slugs not listed go to the end)
_TEMPLATE_SORT_ORDER = [
    "ugovor-zakup",
    "prilog-1-zapisnik",
    "prilog-2-protokol",
    "menicno-ovlascenje",
    "instrukcija-avans",
    "info-osiguranje",
    "ugovor-zakup-jemac",
    "zapisnik-preuzimanje",
]

def _sort_rent_templates(templates):
    """Sort template rows by the preferred display order."""
    order_map = {slug: i for i, slug in enumerate(_TEMPLATE_SORT_ORDER)}
    return sorted(templates, key=lambda t: order_map.get(t["slug"], 999))

@bp.route("/rent/templates")
def admin_rent_templates():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin.login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, slug, name FROM rent_templates ORDER BY id;")
    templates = _sort_rent_templates(cur.fetchall())
    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_preset';")
    row = cur.fetchone()
    rent_email_preset = row["value"] if row else (
        "Poštovani,\n\n"
        "U prilogu Vam dostavljamo sva dokumenta vezana za zakup opreme.\n\n"
        "Ukoliko ste saglasni, molimo Vas da to potvrdite emailom, kako bismo Vam "
        "poštom poslali potpisane primerke ugovora koje nam na dan ugradnje opreme "
        "vraćate sa Vašim potpisom. Svaki prilog ide u 4 primerka \u2013 2 za Vas i 2 za nas.\n\n"
        "Molimo Vas da popunite i meničko ovlašćenje.\n\n"
        "Uplatu avansa izvršite na osnovu Instrukcija za uplatu avansa, "
        "a nakon toga pratite Plan plaćanja.\n\n"
        "Srdačan pozdrav,\nMarinković-Hofmann d.o.o."
    )
    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_subject';")
    subj_row = cur.fetchone()
    rent_email_subject = subj_row["value"] if subj_row else "Ugovor i prilozi za zakup opreme - {{ contract_number }} - {{ client_name }}"
    conn.close()
    return render_template("admin/admin_rent_templates.html", templates=templates, selected=None, msg=None,
                           rent_email_preset=rent_email_preset,
                           rent_email_subject=rent_email_subject)


@bp.route("/rent/templates/<slug>", methods=["GET", "POST"])
def admin_rent_template_edit(slug):
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin.login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, slug, name FROM rent_templates ORDER BY id;")
    templates = _sort_rent_templates(cur.fetchall())

    cur.execute("SELECT * FROM rent_templates WHERE slug=?;", (slug,))
    selected = cur.fetchone()
    if not selected:
        conn.close()
        return "Šablon nije pronađen", 404

    msg = None
    if request.method == "POST":
        new_html = request.form.get("content_html", "")
        cur.execute("UPDATE rent_templates SET content_html=? WHERE slug=?;", (new_html, slug))
        conn.commit()
        msg = "✓ Šablon je uspešno sačuvan."
        # Re-fetch updated
        cur.execute("SELECT * FROM rent_templates WHERE slug=?;", (slug,))
        selected = cur.fetchone()

    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_preset';")
    ep_row = cur.fetchone()
    rent_email_preset = ep_row["value"] if ep_row else (
        "Poštovani,\n\n"
        "U prilogu Vam dostavljamo sva dokumenta vezana za zakup opreme.\n\n"
        "Ukoliko ste saglasni, molimo Vas da to potvrdite emailom, kako bismo Vam "
        "poštom poslali potpisane primerke ugovora koje nam na dan ugradnje opreme "
        "vraćate sa Vašim potpisom. Svaki prilog ide u 4 primerka \u2013 2 za Vas i 2 za nas.\n\n"
        "Molimo Vas da popunite i meničko ovlašćenje.\n\n"
        "Uplatu avansa izvršite na osnovu Instrukcija za uplatu avansa, "
        "a nakon toga pratite Plan plaćanja.\n\n"
        "Srdačan pozdrav,\nMarinković-Hofmann d.o.o."
    )

    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_subject';")
    subj_row2 = cur.fetchone()
    rent_email_subject = subj_row2["value"] if subj_row2 else "Ugovor i prilozi za zakup opreme - {{ contract_number }} - {{ client_name }}"

    conn.close()
    return render_template("admin/admin_rent_templates.html",
                           templates=templates,
                           selected=selected,
                           msg=msg,
                           rent_email_preset=rent_email_preset,
                           rent_email_subject=rent_email_subject)

