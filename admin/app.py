from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os
import sys
import time
import zipfile
import io
import pathlib

# Ensure we can import 'shared' from parent dir
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from shared.config import STATIC_DIR, DATABASE, APP_ASSETS_DIR, IMAGE_DIR
from shared.db import get_db
from shared.auth import check_password, set_password, get_password
from shared.countries import get_country_list

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static"
)
app.secret_key = "crm_admin_secret_key_change_me"
app.config['SESSION_COOKIE_NAME'] = 'admin_session'

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
    templates_dir = os.path.join(PARENT_DIR, "quotation", "templates")
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

@app.before_request
def check_auth():
    if request.endpoint in ('login', 'static'):
        return None
    if not session.get('admin_authenticated'):
        return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pwd = request.form.get("password")
        # Check against 'admin' password
        if check_password("admin", pwd):
            session['admin_authenticated'] = True
            return redirect(url_for('index'))
        else:
            error = "Invalid Admin Password"
    return render_template("admin_login.html", error=error)

@app.route("/logout")
def logout():
    session.pop('admin_authenticated', None)
    return redirect(url_for('login'))

@app.route("/")
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

    conn.close()

    return render_template(
        "admin_dashboard.html",
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
        timestamp=int(time.time()),
        theme=current_theme
    )

@app.route("/add_preset", methods=["POST"])
def add_preset():
    category = request.form.get("category")
    name = request.form.get("name")
    content = request.form.get("content")
    is_default = 1 if request.form.get("is_default") else 0

    if not category or not name:
        flash("Category and Name are required.", "error")
        return redirect(url_for("index"))

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
    return redirect(url_for("index"))

@app.route("/delete_preset", methods=["POST"])
def delete_preset():
    preset_id = request.form.get("preset_id")
    if not preset_id:
        return redirect(url_for("index"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM text_presets WHERE id = ?;", (preset_id,))
    conn.commit()
    conn.close()
    
    flash("Preset deleted.", "success")
    return redirect(url_for("index"))

@app.route("/set_default_preset", methods=["POST"])
def set_default_preset():
    category = request.form.get("category")
    preset_id = request.form.get("preset_id")
    
    if not category or not preset_id:
        return redirect(url_for("index"))

    conn = get_db()
    cur = conn.cursor()
    # Unset others
    cur.execute("UPDATE text_presets SET is_default = 0 WHERE category = ?;", (category,))
    # Set this one
    cur.execute("UPDATE text_presets SET is_default = 1 WHERE id = ?;", (preset_id,))
    conn.commit()
    conn.close()
    
    flash("Default preset updated.", "success")
    return redirect(url_for("index"))

@app.route("/update_passwords", methods=["POST"])
def update_passwords():
    current_admin_pass = request.form.get("current_admin_password")
    
    # Security check setup
    if not check_password("admin", current_admin_pass):
        flash("Incorrect Request: Invalid current Admin password.", "error")
        return redirect(url_for("index"))

    # Helpers to process changes
    # Each app has new_pass and confirm_pass
    changes = [
        ("admin", request.form.get("new_admin_password"), request.form.get("new_admin_password_confirm")),
        ("pricing", request.form.get("new_pricing_password"), request.form.get("new_pricing_password_confirm")),
        ("quotation", request.form.get("new_quotation_password"), request.form.get("new_quotation_password_confirm")),
    ]

    updated_count = 0
    
    for app_name, new_p, confirm_p in changes:
        if new_p: # if not empty
            if new_p != confirm_p:
                flash(f"Error: Passwords for {app_name} did not match.", "error")
                return redirect(url_for("index"))
            set_password(app_name, new_p)
            updated_count += 1
            
    if updated_count > 0:
        flash(f"Successfully updated {updated_count} password(s).", "success")
    else:
        flash("No password changes requested.", "success")
        
    return redirect(url_for("index"))

@app.route("/upload_logo", methods=["POST"])
def upload_logo():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("index"))
        
    f = request.files.get("logo_file")
    if f and f.filename:
        # Save to static/img/logo_company.jpg (OVERWRITE)
        # Verify extension
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png']:
            flash("Logo must be JPG or PNG.", "error")
            return redirect(url_for("index"))
            
        target_dir = os.path.join(STATIC_DIR, "img")
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, "logo_company.jpg")
        
        try:
            # Save to static/img/logo_company.jpg
            f.save(target_path)
            
            # ALSO Save to app_assets/logo_company.jpg (which PDF template uses)
            asset_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
            shutil.copy2(target_path, asset_path)
            
            flash("Logo updated successfully.", "success")
        except Exception as e:
            flash(f"Error saving logo: {e}", "error")
    else:
        flash("No file selected.", "error")

    return redirect(url_for("index"))

@app.route("/update_settings", methods=["POST"])
def update_settings():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("index"))
        
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

        
    # Mandatory fields
    for field in ['req_client_address', 'req_client_email', 'req_client_phone', 'req_client_pib', 'req_client_mb']:
        val = "true" if request.form.get(field) == "true" else "false"
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?);", (field, val))

    conn.commit()
    conn.close()
    
    flash("Settings updated.", "success")
    return redirect(url_for("index"))

@app.route("/backup_db")
def backup_db():
    if not session.get('admin_authenticated'):
        return redirect(url_for('login'))
        
    conn = get_db()
    conn.close() # Ensure db is closed before reading file
    
    file_path = DATABASE
    if not os.path.exists(file_path):
        flash("Database file not found.", "error")
        return redirect(url_for("index"))
        
    date_str = time.strftime("%Y-%m-%d")
    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"full_backup_{date_str}.db"
    )

@app.route("/pdf_templates")
def list_pdf_templates():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pdf_templates ORDER BY id ASC;")
    templates = cur.fetchall()
    
    cur.execute("SELECT value FROM global_settings WHERE key = 'active_pdf_template_id';")
    row = cur.fetchone()
    active_id = int(row["value"]) if row else 0
    
    conn.close()
    return render_template("pdf_templates.html", templates=templates, active_id=active_id)

@app.route("/add_pdf_template", methods=["POST"])
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
    return redirect(url_for("edit_pdf_template", template_id=new_id))

@app.route("/edit_pdf_template/<int:template_id>", methods=["GET", "POST"])
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
    
    # For preview testing: get all quotations
    cur.execute("SELECT id, client_name, offer_number FROM offers ORDER BY date DESC, id DESC;")
    offers = cur.fetchall()
    
    conn.close()
    if not template:
        return "Template not found", 404
        
    return render_template("pdf_template_edit.html", template=template, offers=offers)

@app.route("/delete_pdf_template", methods=["POST"])
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
    return redirect(url_for("list_pdf_templates"))

@app.route("/set_active_pdf_template", methods=["POST"])
def set_active_pdf_template():
    tpl_id = request.form.get("template_id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE global_settings SET value = ? WHERE key = 'active_pdf_template_id';", (tpl_id,))
    conn.commit()
    conn.close()
    flash("Active template updated.", "success")
    return redirect(url_for("list_pdf_templates"))

@app.route("/restore_db", methods=["POST"])
def restore_db():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("index"))
        
    f = request.files.get("db_file")
    if f and f.filename:
        # Basic check
        if not f.filename.endswith(".db") and not f.filename.endswith(".sqlite"):
            flash("Invalid file extension. Please upload a .db file.", "error")
            return redirect(url_for("index"))
            
        # We need to overwrite the database file.
        # Ensure no active connections (not 100% possible with threading but we try)
        # In this simple app, just overwriting usually works on Linux.
        try:
            f.save(DATABASE)
            flash("Database restored successfully.", "success")
        except Exception as e:
            flash(f"Error restoring database: {e}", "error")
    else:
        flash("No file selected.", "error")

    return redirect(url_for("index"))

@app.route("/backup_full")
def backup_full():
    if not session.get('admin_authenticated'):
        return redirect(url_for('login'))
        
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
    date_str = time.strftime("%Y-%m-%d")
    return send_file(
        memory_file,
        as_attachment=True,
        download_name=f"FULL_SYSTEM_BACKUP_{date_str}.zip",
        mimetype="application/zip"
    )

@app.route("/restore_full", methods=["POST"])
def restore_full():
    current_admin_pass = request.form.get("current_admin_password")
    
    if not check_password("admin", current_admin_pass):
        flash("Invalid current Admin password.", "error")
        return redirect(url_for("index"))
        
    f = request.files.get("backup_file")
    if not f or not f.filename:
        flash("No file selected.", "error")
        return redirect(url_for("index"))
        
    if not f.filename.endswith(".zip"):
        flash("Invalid file extension. Please upload a .zip file.", "error")
        return redirect(url_for("index"))
        
    try:
        # Create temp file to extract from
        # Or Just use ZipFile on the file object if strictly supported, but safer to save to temp
        # Using io.BytesIO for in-memory handling if file is specialized
        
        # Check if zip is valid
        with zipfile.ZipFile(f) as zf:
            # Check for pricing.db
            if "pricing.db" not in zf.namelist():
                flash("Invalid Backup: pricing.db not found in archive.", "error")
                return redirect(url_for("index"))
            
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
        
    return redirect(url_for("index"))

@app.route("/rounding_rules")
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
    return render_template("rounding_rules.html", rules_by_target=rules_by_target)

@app.route("/add_rounding_rule", methods=["POST"])
def add_rounding_rule():
    target = request.form.get("target")
    limit_val = float(request.form.get("limit_val") or 0)
    step_val = float(request.form.get("step_val") or 0)
    method = request.form.get("method", "UP")
    
    if not target or limit_val <= 0 or step_val <= 0:
        flash("Invalid rule data.", "error")
        return redirect(url_for("list_rounding_rules"))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO price_rounding_rules (target, limit_val, step_val, method)
        VALUES (?, ?, ?, ?);
    """, (target, limit_val, step_val, method))
    conn.commit()
    conn.close()
    
    flash("Rounding rule added.", "success")
    return redirect(url_for("list_rounding_rules"))

@app.route("/delete_rounding_rule", methods=["POST"])
def delete_rounding_rule():
    rule_id = request.form.get("rule_id")
    if not rule_id:
        return redirect(url_for("list_rounding_rules"))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM price_rounding_rules WHERE id = ?;", (rule_id,))
    conn.commit()
    conn.close()
    
    flash("Rounding rule deleted.", "success")
    return redirect(url_for("list_rounding_rules"))
