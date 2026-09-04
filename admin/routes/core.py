"""Core admin routes: login, logout and the admin dashboard."""

from flask import render_template, request, redirect, url_for, session
import time

from ..app import bp, get_db, check_password, get_api_key, get_country_list, fetch_mandatory_fields, fetch_rent_defaults, DEFAULT_RENT_EMAIL

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

    # Fetch rent module defaults (shared key map + reader)
    rent_defaults = fetch_rent_defaults(cur)

    # Fetch rent email preset
    _DEFAULT_RENT_EMAIL = DEFAULT_RENT_EMAIL
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

    # Fetch mandatory fields settings (shared reader)
    mandatory_fields = fetch_mandatory_fields(cur)

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
