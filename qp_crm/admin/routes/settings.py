"""Admin settings routes: passwords, branding uploads, global settings and API key management."""

from flask import request, redirect, url_for, flash
import os

from qp_crm.shared.config import STATIC_DIR, APP_ASSETS_DIR
from qp_crm.shared.web import MANDATORY_FIELD_KEYS, RENT_DEFAULT_KEYS

from ..app import bp, get_db, check_password, set_password, generate_api_key, revoke_api_key

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
    for field in MANDATORY_FIELD_KEYS:
        val = "true" if request.form.get(field) == "true" else "false"
        cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?);", (field, val))

    # Rent module defaults
    rent_num_keys = list(RENT_DEFAULT_KEYS)
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
