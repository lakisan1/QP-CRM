from flask import Flask, render_template, render_template_string, request, redirect, url_for, send_from_directory, send_file, jsonify, session
import sqlite3
import os
import sys
import io
# pdfkit removed
import requests
from weasyprint import HTML, CSS
from datetime import date
from pathlib import Path

# Base directory = the "QP-CRM" folder (parent of this app folder)
# We now use shared.config for this.

# Ensure we can import 'shared' from parent dir
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from shared.config import BASE_DIR, APP_DATA_DIR, DATABASE, IMAGE_DIR, APP_ASSETS_DIR, STATIC_DIR
from shared.db import get_db
from shared.auth import check_password
from shared.countries import get_country_list

#  common_utils app import
# it's in PARENT_DIR which is already in sys.path
from shared.utils import format_amount, format_date, get_nbs_rate

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static"
)
app.secret_key = "crm_offer_secret_key_change_me"
app.config['SESSION_COOKIE_NAME'] = 'offer_session'

@app.before_request
def check_auth():
    # Exempt login page, static files, and NBS API from authentication
    if request.endpoint in ('login', 'static', 'api_nbs_eur_rate'):
        return None
    
    if not session.get('authenticated'):
        return redirect(url_for('login'))

def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Offers table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_number TEXT,
            date TEXT,
            client_name TEXT,
            client_address TEXT,
            client_email TEXT,
            client_phone TEXT,
            country TEXT,

            currency TEXT,
            exchange_rate REAL,

            discount_percent REAL,
            vat_percent REAL,

            total_net REAL,
            total_discount REAL,
            total_net_after_discount REAL,
            total_vat REAL,
            total_gross REAL,

            payment_terms TEXT,
            delivery_terms TEXT,
            validity_days INTEGER,
            notes TEXT,
            napomena TEXT,
            is_template INTEGER DEFAULT 0
        );
    """)

    # --- Migration for existing databases ---
    try:
        cur.execute("ALTER TABLE offers ADD COLUMN napomena TEXT;")
    except sqlite3.OperationalError:
        # Already exists
        pass

    try:
        cur.execute("ALTER TABLE offers ADD COLUMN is_template INTEGER DEFAULT 0;")
    except sqlite3.OperationalError:
        # Already exists
        pass

    try:
        cur.execute("ALTER TABLE offers ADD COLUMN client_pib TEXT;")
    except sqlite3.OperationalError:
        # Already exists
        pass

    try:
        cur.execute("ALTER TABLE offers ADD COLUMN client_mb TEXT;")
    except sqlite3.OperationalError:
        # Already exists
        pass

    try:
        cur.execute("ALTER TABLE offers ADD COLUMN country TEXT DEFAULT 'Srbija';")
    except sqlite3.OperationalError:
        # Already exists
        pass

    # Offer items table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS offer_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER NOT NULL,
            product_id INTEGER,
            line_order INTEGER,
            item_name TEXT NOT NULL,
            item_description TEXT,
            item_photo_path TEXT,
            quantity REAL NOT NULL,
            unit_price REAL NOT NULL,
            discount_percent REAL DEFAULT 0.0,
            line_net REAL NOT NULL,
            FOREIGN KEY (offer_id) REFERENCES offers(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
    """)

    try:
        cur.execute("ALTER TABLE offer_items ADD COLUMN discount_percent REAL DEFAULT 0.0;")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()





@app.template_filter('format_date')
def _format_date_filter(date_str, fmt=None):
    if fmt is None:
        fmt = get_date_format()
    return format_date(date_str, fmt)

@app.context_processor
def inject_helpers():
    return dict(
        format_amount=format_amount,
        theme=get_theme(),
        enable_product_discount=get_enable_product_discount()
    )

@app.route("/api/nbs_eur_rate")
def api_nbs_eur_rate():
    rate = get_nbs_rate("eur")
    if rate is None:
        return jsonify({"success": False, "message": "Neuspešno preuzimanje kursa sa NBS."}), 500
    return jsonify({"success": True, "rate": rate})

@app.route("/product-image/<path:filename>")
def product_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route("/asset/<path:filename>")
def app_asset(filename):
    return send_from_directory(APP_ASSETS_DIR, filename)

@app.route("/")
def index():
    return redirect(url_for("list_offers"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if check_password("offer", request.form.get("password")):
            session['authenticated'] = True
            return redirect(url_for('index'))
        else:
            error = "Pogrešna lozinka"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

def get_date_format():
    """Fetch the date_format setting from cookies."""
    from flask import request
    return request.cookies.get("date_format", "YYYY-MM-DD")

def get_theme():
    """Fetch the theme setting from cookies."""
    from flask import request
    return request.cookies.get("theme", "dark")

def get_enable_product_discount():
    """Fetch the enable_product_discount setting."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM global_settings WHERE key = 'enable_product_discount';")
    row = cur.fetchone()
    conn.close()
    return (row["value"] == "true") if row else True

def get_mandatory_fields():
    """Fetch mandatory field settings from global_settings."""
    conn = get_db()
    cur = conn.cursor()
    fields = ['req_client_address', 'req_client_email', 'req_client_phone', 'req_client_pib', 'req_client_mb']
    settings = {}
    for f in fields:
        cur.execute("SELECT value FROM global_settings WHERE key = ?;", (f,))
        row = cur.fetchone()
        settings[f] = (row["value"] == "true") if row else False
    conn.close()
    return settings

@app.route("/offers")
def list_offers():
    # Check if we should clear filters
    if request.args.get("clear"):
        session.pop("offers_filter_search", None)
        session.pop("offers_filter_date_from", None)
        session.pop("offers_filter_date_to", None)
        session.pop("offers_filter_item", None)
        session.pop("offers_filter_view", None)
        session.pop("offers_filter_country", None)
        return redirect(url_for("list_offers"))

    # Load from request or fallback to session
    view = request.args.get("view")
    if view is None:
        view = session.get("offers_filter_view", "offers")
    else:
        session["offers_filter_view"] = view
    search_term = request.args.get("search")
    if search_term is None:
        search_term = session.get("offers_filter_search", "")
    else:
        session["offers_filter_search"] = search_term

    page = request.args.get("page", 1, type=int)

    date_from = request.args.get("date_from")
    if date_from is None:
        date_from = session.get("offers_filter_date_from", "")
    else:
        session["offers_filter_date_from"] = date_from

    date_to = request.args.get("date_to")
    if date_to is None:
        date_to = session.get("offers_filter_date_to", "")
    else:
        session["offers_filter_date_to"] = date_to

    item_filter = request.args.get("item")
    if item_filter is None:
        item_filter = session.get("offers_filter_item", "")
    else:
        session["offers_filter_item"] = item_filter

    country_filter = request.args.get("country")
    if country_filter is None:
        country_filter = session.get("offers_filter_country", "")
    else:
        session["offers_filter_country"] = country_filter

    conn = get_db()
    cur = conn.cursor()
    
    # Fetch default items per page
    cur.execute("SELECT value FROM global_settings WHERE key = 'default_items_per_page';")
    row = cur.fetchone()
    items_per_page = int(row["value"]) if row else 25
    offset = (page - 1) * items_per_page

    # Fetch all countries for the dropdown dynamically
    countries = get_country_list()

    # Fetch all products for the dropdown
    cur.execute("""
        SELECT id, name, brand, category
        FROM products
        ORDER BY name;
    """)
    products = cur.fetchall()

        # Build query with optional item filter
    if item_filter:
        # Join with offer_items to filter by product
        count_query = """
            SELECT COUNT(DISTINCT o.id) AS total_count
            FROM offers o
            INNER JOIN offer_items oi ON o.id = oi.offer_id
        """
        query = """
            SELECT DISTINCT o.*
            FROM offers o
            INNER JOIN offer_items oi ON o.id = oi.offer_id
        """
        params = []
        clauses = []
        
        # Add item filter
        clauses.append("oi.product_id = ?")
        params.append(item_filter)

        if search_term:
            clauses.append("(o.client_name LIKE ? OR o.offer_number LIKE ?)")
            pattern = f"%{search_term}%"
            params.extend([pattern, pattern])

        if date_from:
            clauses.append("o.date >= ?")
            params.append(date_from)

        if date_to:
            clauses.append("o.date <= ?")
            params.append(date_to)

        if country_filter:
            clauses.append("o.country = ?")
            params.append(country_filter)

        if clauses:
            where_stmt = " WHERE " + " AND ".join(clauses)
            count_query += where_stmt
            query += where_stmt

        query += " ORDER BY o.date DESC, o.id DESC"
        query += f" LIMIT {items_per_page} OFFSET {offset};"
    else:
        # No item filter, use simple query
        count_query = """
            SELECT COUNT(*) AS total_count
            FROM offers
        """
        query = """
            SELECT *
            FROM offers
        """
        params = []
        clauses = []

        if view == "templates":
            clauses.append("is_template = 1")
        else:
            clauses.append("is_template = 0")

        if search_term:
            clauses.append("(client_name LIKE ? OR offer_number LIKE ?)")
            pattern = f"%{search_term}%"
            params.extend([pattern, pattern])

        if date_from:
            clauses.append("date >= ?")
            params.append(date_from)

        if date_to:
            clauses.append("date <= ?")
            params.append(date_to)

        if country_filter:
            clauses.append("country = ?")
            params.append(country_filter)

        if clauses:
            where_stmt = " WHERE " + " AND ".join(clauses)
            count_query += where_stmt
            query += where_stmt

        query += " ORDER BY date DESC, id DESC"
        query += f" LIMIT {items_per_page} OFFSET {offset};"

    # Execute count
    cur.execute(count_query, params)
    total_count = cur.fetchone()["total_count"]
    
    import math
    total_pages = math.ceil(total_count / items_per_page) if total_count > 0 else 1

    cur.execute(query, params)
    offers = cur.fetchall()

    cur.execute("SELECT value FROM global_settings WHERE key = 'language';")
    row = cur.fetchone()
    current_language = row["value"] if row else "en"

    conn.close()

    return render_template(
        "offers.html",
        offers=offers,
        search_term=search_term,
        date_from=date_from,
        date_to=date_to,
        item_filter=item_filter,
        country_filter=country_filter,
        products=products,
        countries=countries,
        current_view=view,
        current_language=current_language,
        current_page=page,
        total_pages=total_pages,
        total_count=total_count
    )


@app.route("/offers/new", methods=["GET", "POST"])
def new_offer():
    if request.method == "POST":
        date_str = request.form.get("date") or date.today().isoformat()
        offer_number = (request.form.get("offer_number") or "").strip()

        client_name = (request.form.get("client_name") or "").strip()
        client_address = (request.form.get("client_address") or "").strip()
        client_email = (request.form.get("client_email") or "").strip()
        client_phone = (request.form.get("client_phone") or "").strip()
        client_pib = (request.form.get("client_pib") or "").strip()
        client_mb = (request.form.get("client_mb") or "").strip()
        country = (request.form.get("country") or "").strip()

        currency = (request.form.get("currency") or "EUR").strip()
        exchange_rate = float(request.form.get("exchange_rate") or 0)

        discount_percent_input = float(request.form.get("discount_percent") or 0)
        vat_percent_input = float(request.form.get("vat_percent") or 20)

        discount_percent = discount_percent_input / 100.0 if discount_percent_input else 0.0
        vat_percent = vat_percent_input / 100.0 if vat_percent_input else 0.0

        payment_terms = (request.form.get("payment_terms") or "").strip()
        delivery_terms = (request.form.get("delivery_terms") or "").strip()
        validity_days = int(request.form.get("validity_days") or 10)
        notes = (request.form.get("notes") or "").strip()
        napomena = (request.form.get("napomena") or "").strip()
        is_template = 1 if request.form.get("is_template") else 0

        # Validate mandatory fields
        mandatory = get_mandatory_fields()
        errors = []
        if mandatory.get('req_client_address') and not client_address:
            errors.append("Address is required.")
        if mandatory.get('req_client_email') and not client_email:
            errors.append("Email is required.")
        if mandatory.get('req_client_phone') and not client_phone:
            errors.append("Phone is required.")
        if mandatory.get('req_client_pib') and not client_pib:
            errors.append("PIB is required.")
        if mandatory.get('req_client_mb') and not client_mb:
            errors.append("MB is required.")

        if errors:
            # Re-render with error
             # Fetch default presets if they exist
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT category, content FROM text_presets WHERE is_default = 1;")
            default_rows = cur.fetchall()
            
            # Fetch all presets for dropdowns
            cur.execute("SELECT * FROM text_presets ORDER BY name ASC;")
            all_presets = cur.fetchall()
            presets_by_cat = {'delivery': [], 'payment': [], 'note': [], 'extra': []}
            for p in all_presets:
                if p['category'] in presets_by_cat:
                    presets_by_cat[p['category']].append(p)
            cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_subject';")
            row = cur.fetchone()
            email_offer_subject = row["value"] if row else "Ponuda br. {offer_number}"

            cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_body';")
            row = cur.fetchone()
            email_offer_body = row["value"] if row else "Postovani,\n\nU prilogu vam saljemo ponudu br. {offer_number}.\n\nSrdacan pozdrav,\nVas Tim"
            
            conn.close()

            preserved_offer = {
                "offer_number": offer_number,
                "date": date_str,
                "client_name": client_name,
                "client_address": client_address,
                "client_email": client_email,
                "client_phone": client_phone,
                "client_pib": client_pib,
                "client_mb": client_mb,
            "currency": currency,
            "exchange_rate": exchange_rate,
            "discount_percent": discount_percent_input / 100.0 if discount_percent_input else None, 
            "vat_percent": vat_percent_input / 100.0 if vat_percent_input else None,
            "payment_terms": payment_terms,
            "delivery_terms": delivery_terms,
            "validity_days": validity_days,
            "notes": notes,
            "napomena": napomena,
            "country": country
        }
            return render_template("offer_form.html", offer=preserved_offer, today=date.today().isoformat(), 
                                   error=" ".join(errors), mandatory_fields=mandatory, presets_by_cat=presets_by_cat,
                                   countries=get_country_list(),
                                   email_offer_subject=email_offer_subject, email_offer_body=email_offer_body,
                                   current_language=current_language)

        conn = get_db()
        cur = conn.cursor()
        # Validate duplicates if not allowed
        cur.execute("SELECT value FROM global_settings WHERE key = 'allow_duplicate_names';")
        row_dup = cur.fetchone()
        allow_dup = row_dup["value"] == "true" if row_dup else False
        
        if not allow_dup:
            cur.execute("SELECT id FROM offers WHERE offer_number = ?;", (offer_number,))
            existing = cur.fetchone()
            if existing:
                cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_subject';")
                row = cur.fetchone()
                email_offer_subject = row["value"] if row else "Ponuda br. {offer_number}"

                cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_body';")
                row = cur.fetchone()
                email_offer_body = row["value"] if row else "Postovani,\n\nU prilogu vam saljemo ponudu br. {offer_number}.\n\nSrdacan pozdrav,\nVas Tim"

                conn.close()
                # Construct a dict to preserve inputs
                preserved_offer = {
                    "offer_number": offer_number,
                    "date": date_str,
                    "client_name": client_name,
                    "client_address": client_address,
                    "client_email": client_email,
                    "client_phone": client_phone,
                    "client_pib": client_pib,
                    "client_mb": client_mb,
            "currency": currency,
            "exchange_rate": exchange_rate,
            "discount_percent": discount_percent_input / 100.0 if discount_percent_input else None, 
            "vat_percent": vat_percent_input / 100.0 if vat_percent_input else None,
            "payment_terms": payment_terms,
            "delivery_terms": delivery_terms,
            "validity_days": validity_days,
            "notes": notes,
            "napomena": napomena,
            "country": country
        }
                return render_template("offer_form.html", offer=preserved_offer, today=date.today().isoformat(), 
                                       email_offer_subject=email_offer_subject, email_offer_body=email_offer_body,
                                       countries=get_country_list(),
                                       current_language=current_language)

        cur.execute("""
            INSERT INTO offers (
                offer_number, date,
                client_name, client_address, client_email, client_phone, client_pib, client_mb,
                currency, exchange_rate,
                discount_percent, vat_percent,
                total_net, total_discount, total_net_after_discount,
                total_vat, total_gross,
                payment_terms, delivery_terms, validity_days, notes, napomena, is_template, country
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?, ?, ?, ?, ?, ?);
        """, (
            offer_number, date_str,
            client_name, client_address, client_email, client_phone, client_pib, client_mb,
            currency, exchange_rate,
            discount_percent, vat_percent,
            payment_terms, delivery_terms, validity_days, notes, napomena, is_template, country
        ))
        offer_id = cur.lastrowid
        conn.commit()
        conn.close()

        return redirect(url_for("edit_offer", offer_id=offer_id))

    # GET
    # Fetch default presets if they exist
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT category, content FROM text_presets WHERE is_default = 1;")
    default_rows = cur.fetchall()
    
    # Fetch all presets for dropdowns
    cur.execute("SELECT * FROM text_presets ORDER BY name ASC;")
    all_presets = cur.fetchall()
    presets_by_cat = {'delivery': [], 'payment': [], 'note': [], 'extra': []}
    for p in all_presets:
        if p['category'] in presets_by_cat:
            presets_by_cat[p['category']].append(p)

    # Fetch default VAT and Validity from global_settings
    cur.execute("SELECT value FROM global_settings WHERE key = 'default_vat_percent';")
    row = cur.fetchone()
    default_vat_percent = float(row["value"]) if row else 20.0

    cur.execute("SELECT value FROM global_settings WHERE key = 'default_validity_days';")
    row = cur.fetchone()
    default_validity_days = int(row["value"]) if row else 10

    cur.execute("SELECT value FROM global_settings WHERE key = 'default_country';")
    row = cur.fetchone()
    default_country = row["value"] if row else "Srbija"

    # Fetch email templates
    cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_subject';")
    row = cur.fetchone()
    email_offer_subject = row["value"] if row else "Ponuda br. {offer_number}"

    cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_body';")
    row = cur.fetchone()
    email_offer_body = row["value"] if row else "Postovani,\n\nU prilogu vam saljemo ponudu br. {offer_number}.\n\nSrdacan pozdrav,\nVas Tim"

    cur.execute("SELECT value FROM global_settings WHERE key = 'language';")
    row = cur.fetchone()
    current_language = row["value"] if row else "en"

    conn.close()

    defaults = {r['category']: r['content'] for r in default_rows}
    
    # These are the default values if no preset is set to default
    default_delivery = defaults.get('delivery', '')
    default_napomena = defaults.get('note', '')
    default_extra = defaults.get('extra', '')
    default_payment = defaults.get('payment', '')

    return render_template("offer_form.html", 
                           offer=None, 
                           today=date.today().isoformat(),
                           default_delivery=default_delivery,
                           default_napomena=default_napomena,
                           default_extra=default_extra,
                           default_payment=default_payment,
                           default_vat_percent=default_vat_percent,
                           default_validity_days=default_validity_days,
                           default_country=default_country,
                           countries=get_country_list(),
                           presets_by_cat=presets_by_cat,
                           mandatory_fields=get_mandatory_fields(),
                           email_offer_subject=email_offer_subject,
                           email_offer_body=email_offer_body,
                           current_language=current_language)


def recalc_totals(offer_id):
    """Recalculate totals for an offer based on its items and discount/VAT."""
    conn = get_db()
    cur = conn.cursor()

    # Load offer
    cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
    offer = cur.fetchone()
    if offer is None:
        conn.close()
        return

    discount_percent = offer["discount_percent"] or 0.0
    vat_percent = offer["vat_percent"] or 0.0

    # Sum line_net
    cur.execute("""
        SELECT COALESCE(SUM(line_net), 0) AS sum_net
        FROM offer_items
        WHERE offer_id = ?;
    """, (offer_id,))
    row = cur.fetchone()
    total_net = row["sum_net"] or 0.0

    total_discount = total_net * discount_percent
    total_net_after_discount = total_net - total_discount
    total_vat = total_net_after_discount * vat_percent
    total_gross = total_net_after_discount + total_vat

    cur.execute("""
        UPDATE offers
        SET total_net = ?, total_discount = ?, total_net_after_discount = ?,
            total_vat = ?, total_gross = ?
        WHERE id = ?;
    """, (
        total_net, total_discount, total_net_after_discount,
        total_vat, total_gross, offer_id
    ))
    conn.commit()
    conn.close()


@app.route("/offers/<int:offer_id>/edit", methods=["GET", "POST"])
def edit_offer(offer_id):
    conn = get_db()
    cur = conn.cursor()

    new_prod_id = None
    # Load offer
    cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
    offer = cur.fetchone()
    if offer is None:
        conn.close()
        return "Offer not found", 404

    # Check if we should clear item filters
    if request.args.get("clear"):
        session.pop("offer_edit_filter_brand", None)
        session.pop("offer_edit_filter_category", None)
        session.pop("offer_edit_filter_search", None)
        return redirect(url_for("edit_offer", offer_id=offer_id))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_header":
            date_str = request.form.get("date") or date.today().isoformat()
            offer_number = (request.form.get("offer_number") or "").strip()
            client_name = (request.form.get("client_name") or "").strip()
            client_address = (request.form.get("client_address") or "").strip()
            client_email = (request.form.get("client_email") or "").strip()
            client_phone = (request.form.get("client_phone") or "").strip()
            client_pib = (request.form.get("client_pib") or "").strip()
            client_mb = (request.form.get("client_mb") or "").strip()
            country = (request.form.get("country") or "").strip()

            currency = (request.form.get("currency") or "EUR").strip()
            exchange_rate = float(request.form.get("exchange_rate") or 0)

            discount_percent_input = float(request.form.get("discount_percent") or 0)
            vat_percent_input = float(request.form.get("vat_percent") or 20)

            discount_percent = discount_percent_input / 100.0 if discount_percent_input else 0.0
            vat_percent = vat_percent_input / 100.0 if vat_percent_input else 0.0

            payment_terms = (request.form.get("payment_terms") or "").strip()
            delivery_terms = (request.form.get("delivery_terms") or "").strip()
            validity_days = int(request.form.get("validity_days") or 10)
            notes = (request.form.get("notes") or "").strip()
            napomena = (request.form.get("napomena") or "").strip()
            is_template = 1 if request.form.get("is_template") else 0

            # Validate mandatory fields
            mandatory = get_mandatory_fields()
            errors = []
            if mandatory.get('req_client_address') and not client_address:
                errors.append("Address is required.")
            if mandatory.get('req_client_email') and not client_email:
                errors.append("Email is required.")
            if mandatory.get('req_client_phone') and not client_phone:
                errors.append("Phone is required.")
            if mandatory.get('req_client_pib') and not client_pib:
                errors.append("PIB is required.")
            if mandatory.get('req_client_mb') and not client_mb:
                errors.append("MB is required.")

            if errors:
                session["error_message"] = " ".join(errors)
                return redirect(url_for("edit_offer", offer_id=offer_id))

            # Validate duplicates if not allowed
            cur.execute("SELECT value FROM global_settings WHERE key = 'allow_duplicate_names';")
            row_dup = cur.fetchone()
            allow_dup = row_dup["value"] == "true" if row_dup else False
            
            if not allow_dup:
                cur.execute("SELECT id FROM offers WHERE offer_number = ? AND id != ?;", (offer_number, offer_id))
                existing = cur.fetchone()
                if existing:
                    conn.close()
                    # For edit, we must use session to persist error across redirect
                    session["error_message"] = "Duplicate Offer Number not allowed."
                    return redirect(url_for("edit_offer", offer_id=offer_id))

            cur.execute("""
                UPDATE offers
                SET offer_number = ?, date = ?,
                    client_name = ?, client_address = ?, client_email = ?, client_phone = ?, client_pib = ?, client_mb = ?,
                    currency = ?, exchange_rate = ?,
                    discount_percent = ?, vat_percent = ?,
                    payment_terms = ?, delivery_terms = ?, validity_days = ?, notes = ?, napomena = ?, is_template = ?, country = ?
                WHERE id = ?;
            """, (
                offer_number, date_str,
                client_name, client_address, client_email, client_phone, client_pib, client_mb,
                currency, exchange_rate,
                discount_percent, vat_percent,
                payment_terms, delivery_terms, validity_days, notes, napomena, is_template, country,
                offer_id
            ))
            conn.commit()
            # recalc with new discount/vat
            recalc_totals(offer_id)

        elif action == "add_item":
            product_id = request.form.get("product_id")
            quantity = float(request.form.get("quantity") or 1)
            unit_price_input = request.form.get("unit_price")

            # Lookup product info
            prod_row = None
            if product_id:
                cur.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
                prod_row = cur.fetchone()

            item_name = (request.form.get("item_name") or "").strip()
            item_description = (request.form.get("item_description") or "").strip()
            item_photo_path = None

            if prod_row:
                if not item_name:
                    item_name = prod_row["name"]
                if not item_description:
                    item_description = prod_row["description"] or ""
                item_photo_path = prod_row["photo_path"] or None

                # If unit price is not manually entered, use latest final price
                if not unit_price_input:
                    cur.execute("""
                        SELECT final_price
                        FROM prices
                        WHERE product_id = ?
                        ORDER BY date DESC
                        LIMIT 1;
                    """, (product_id,))
                    pr = cur.fetchone()
                    if pr and pr["final_price"] is not None:
                        unit_price = float(pr["final_price"])
                    else:
                        unit_price = 0.0
                else:
                    unit_price = float(unit_price_input or 0)
            else:
                # No product selected – free text line
                unit_price = float(unit_price_input or 0)

            discount_percent_input = float(request.form.get("discount_percent") or 0)
            discount_percent = discount_percent_input / 100.0 if discount_percent_input else 0.0

            line_net = quantity * unit_price * (1 - discount_percent)

            # Determine line_order
            cur.execute("""
                SELECT COALESCE(MAX(line_order), 0) AS max_order
                FROM offer_items
                WHERE offer_id = ?;
            """, (offer_id,))
            row = cur.fetchone()
            next_order = (row["max_order"] or 0) + 1

            cur.execute("""
                INSERT INTO offer_items (
                    offer_id, product_id, line_order,
                    item_name, item_description, item_photo_path,
                    quantity, unit_price, discount_percent, line_net
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                offer_id,
                int(product_id) if product_id else None,
                next_order,
                item_name, item_description, item_photo_path,
                quantity, unit_price, discount_percent, line_net
            ))
            conn.commit()

            # totals in DB
            recalc_totals(offer_id)

            # IMPORTANT: redirect to GET so we reload fresh offer + items
            conn.close()
            return redirect(url_for("edit_offer", offer_id=offer_id))

        elif action == "create_temp_product":
            # Quick-create a minimal product with TEMP brand/category
            new_name = (request.form.get("new_product_name") or "").strip()
            new_desc = (request.form.get("new_product_desc") or "").strip()

            new_prod_id = None

            if new_name:
                # Check if product with same name already exists (case-insensitive)
                cur.execute("""
                    SELECT id
                    FROM products
                    WHERE name = ? COLLATE NOCASE;
                """, (new_name,))
                existing = cur.fetchone()

                if existing:
                    new_prod_id = existing["id"]
                else:
                    cur.execute("""
                        INSERT INTO products (name, brand, category, description)
                        VALUES (?, ?, ?, ?);
                    """, (new_name, "TEMP", "TEMP", new_desc))
                    conn.commit()
                    new_prod_id = cur.lastrowid

            conn.close()

        elif action == "delete_item":
            item_id = int(request.form.get("item_id"))
            cur.execute("DELETE FROM offer_items WHERE id = ? AND offer_id = ?;", (item_id, offer_id))
            conn.commit()
            recalc_totals(offer_id)

            conn.close()
            return redirect(url_for("edit_offer", offer_id=offer_id))

        # Redirect so that GET can preselect this product in the dropdown
        if new_prod_id:
            return redirect(url_for("edit_offer",
                                    offer_id=offer_id,
                                    product_id=new_prod_id))
        else:
            return redirect(url_for("edit_offer", offer_id=offer_id))

    # GET or after POST: load items
    cur.execute("""
        SELECT *
        FROM offer_items
        WHERE offer_id = ?
        ORDER BY line_order, id;
    """, (offer_id,))
    items = cur.fetchall()

    # --- Product filters for dropdown (brand, category, search name) ---
    # Load from request or fallback to session
    brand_filter = request.args.get("brand")
    if brand_filter is None:
        brand_filter = session.get("offer_edit_filter_brand", "")
    else:
        session["offer_edit_filter_brand"] = brand_filter

    category_filter = request.args.get("category")
    if category_filter is None:
        category_filter = session.get("offer_edit_filter_category", "")
    else:
        session["offer_edit_filter_category"] = category_filter

    search_term = request.args.get("search")
    if search_term is None:
        search_term = session.get("offer_edit_filter_search", "")
    else:
        session["offer_edit_filter_search"] = search_term

    # which product should be pre-selected in dropdown (after quick-add)
    selected_product_id = request.args.get("product_id")

    # Build products query with optional filters (and latest price)
    query = """
        SELECT
            p.id,
            p.name,
            p.brand,
            p.category,
            p.description,
            (
                SELECT pr.final_price
                FROM prices pr
                WHERE pr.product_id = p.id
                ORDER BY pr.date DESC
                LIMIT 1
            ) AS latest_price
        FROM products p
    """
    params = []
    clauses = []

    if brand_filter:
        clauses.append("p.brand = ?")
        params.append(brand_filter)

    if category_filter:
        clauses.append("p.category = ?")
        params.append(category_filter)

    if search_term:
        clauses.append("p.name LIKE ?")
        params.append(f"%{search_term}%")

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY p.name;"

    cur.execute(query, params)
    products = cur.fetchall()


    # Brand options for dropdown
    cur.execute("""
        SELECT DISTINCT brand
        FROM products
        WHERE brand IS NOT NULL AND brand != ''
        ORDER BY brand;
    """)
    brand_rows = cur.fetchall()
    brand_options = [row["brand"] for row in brand_rows]

    # Category options for dropdown (from pricing app table)
    cur.execute("""
        SELECT category
        FROM category_pricing_defaults
        ORDER BY category;
    """)
    cat_rows = cur.fetchall()
    category_options = [row["category"] for row in cat_rows]

    # Fetch presets for dropdowns
    cur.execute("SELECT * FROM text_presets ORDER BY name ASC;")
    all_presets = cur.fetchall()
    presets_by_cat = {'delivery': [], 'note': [], 'extra': []}
    for p in all_presets:
        if p['category'] in presets_by_cat:
            presets_by_cat[p['category']].append(p)

    # Fetch email templates
    cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_subject';")
    row = cur.fetchone()
    email_offer_subject = row["value"] if row else "Ponuda br. {offer_number}"

    cur.execute("SELECT value FROM global_settings WHERE key = 'email_offer_body';")
    row = cur.fetchone()
    email_offer_body = row["value"] if row else "Postovani,\n\nU prilogu vam saljemo ponudu br. {offer_number}.\n\nSrdacan pozdrav,\nVas Tim"

    cur.execute("SELECT value FROM global_settings WHERE key = 'language';")
    row = cur.fetchone()
    current_language = row["value"] if row else "en"

    conn.close()
    return render_template(
        "offer_form.html",
        offer=offer,
        items=items,
        products=products,
        brand_options=brand_options,
        category_options=category_options,
        brand_filter=brand_filter,
        category_filter=category_filter,
        search_term=search_term,
        selected_product_id=selected_product_id,
        today=date.today().isoformat(),
        new_prod_id=new_prod_id,
        presets_by_cat=presets_by_cat,
        mandatory_fields=get_mandatory_fields(),
        email_offer_subject=email_offer_subject,
        email_offer_body=email_offer_body,
        countries=get_country_list(),
        current_language=current_language
    )


@app.route("/offers/<int:offer_id>/view")
def view_offer(offer_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
    offer = cur.fetchone()
    if offer is None:
        conn.close()
        return "Offer not found", 404

    cur.execute("""
        SELECT *
        FROM offer_items
        WHERE offer_id = ?
        ORDER BY line_order, id;
    """, (offer_id,))
    items = cur.fetchall()
    cur.execute("SELECT value FROM global_settings WHERE key = 'language';")
    row = cur.fetchone()
    current_language = row["value"] if row else "en"

    conn.close()
    return render_template(
        "offer_view.html", 
        offer=offer, 
        items=items,
        countries=get_country_list(),
        current_language=current_language
    )

import io
from flask import send_file, request

from pathlib import Path

@app.route("/offers/<int:offer_id>/pdf")
def offer_pdf(offer_id):
    conn = get_db()
    cur = conn.cursor()

    # Load offer
    cur.execute("SELECT * FROM offers WHERE id = ?", (offer_id,))
    offer = cur.fetchone()
    if not offer:
        conn.close()
        return "Offer not found", 404

    # Load items
    cur.execute("""
        SELECT *
        FROM offer_items
        WHERE offer_id = ?
        ORDER BY line_order, id
    """, (offer_id,))
    items = cur.fetchall()

    # ---- Build file:// URIs for product images ----
    items_for_pdf = []
    for row in items:
        d = dict(row)
        photo_name = d.get("item_photo_path")
        if photo_name:
            full_path = os.path.join(IMAGE_DIR, photo_name)
            if os.path.isfile(full_path):
                d["item_photo_uri"] = Path(full_path).as_uri()
            else:
                d["item_photo_uri"] = None
        else:
            d["item_photo_uri"] = None
        items_for_pdf.append(d)

    # ---- Template Selection ----
    preview_tpl_id = request.args.get("preview_template_id")
    active_tpl_id = 0
    
    if preview_tpl_id:
        active_tpl_id = int(preview_tpl_id)
    else:
        # Get active template from global_settings
        cur.execute("SELECT value FROM global_settings WHERE key = 'active_pdf_template_id';")
        row = cur.fetchone()
        active_tpl_id = int(row["value"]) if row else 0

    custom_tpl = None
    if active_tpl_id > 0:
        cur.execute("SELECT * FROM pdf_templates WHERE id = ?;", (active_tpl_id,))
        custom_tpl = cur.fetchone()

    cur.execute("SELECT value FROM global_settings WHERE key = 'language';")
    row = cur.fetchone()
    current_language = row["value"] if row else "en"

    conn.close()

    # ---- Logo URI ----
    logo_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
    logo_uri = Path(logo_path).as_uri()

    # ---- Footer Image URI ----
    rig_path = os.path.join(APP_ASSETS_DIR, "pdf_footer_image.png")
    rig_uri = Path(rig_path).as_uri()

    ctx = {
        "offer": offer,
        "items": items_for_pdf,
        "pdf_mode": True,
        "logo_uri": logo_uri,
        "rig_uri": rig_uri,
        "format_amount": globals().get('format_amount'), # Make sure these are available
        "format_date": globals().get('format_date'),
        "countries": get_country_list(),
        "current_language": current_language
    }
    # Actually these are already in app.jinja_env.globals if registered
    # but for render_template_string we might need to be explicit or it uses the current app context.

    # Fix for System Default template (render_template_string needs these explicitly if not global)
    ctx["current_date_format"] = get_date_format()
    # Dummy translation function if not present
    ctx["_"] = lambda x: x
    ctx["gettext"] = lambda x: x

    if custom_tpl:
        # Render parts from DB
        header_html = render_template_string(custom_tpl["header_html"], **ctx)
        body_html = render_template_string(custom_tpl["body_html"], **ctx)
        footer_html = render_template_string(custom_tpl["footer_html"], **ctx)
        custom_css = custom_tpl["css"]
        
        # We still use a basic wrapper to position header/footer running elements
        html_string = f"""
        <!doctype html>
        <html>
        <head><meta charset="utf-8"></head>
        <body>
            <div class="pdf-footer">{footer_html}</div>
            <div class="pdf-header">{header_html}</div>
            <div class="page-content">{body_html}</div>
        </body>
        </html>
        """
        pdf_bytes = HTML(string=html_string).write_pdf(
            stylesheets=[CSS(string=custom_css)]
        )
    else:
        # Fallback to filesystem
        html_string = render_template(
            "pdf_offer.html",
            **ctx
        )
        pdf_css_path = os.path.join(BASE_DIR, "static", "css", "pdf.css")
        pdf_bytes = HTML(string=html_string).write_pdf(
            stylesheets=[CSS(filename=pdf_css_path)]
        )

    num = offer["offer_number"] or offer["id"]
    filename = f"{num}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

@app.route("/offers/<int:offer_id>/duplicate", methods=["POST"])
def duplicate_offer(offer_id):
    conn = get_db()
    cur = conn.cursor()

    # 1. Fetch original offer
    cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
    offer = cur.fetchone()
    if not offer:
        conn.close()
        return "Offer not found", 404

    # 2. Insert new offer based on original
    # We set is_template=0 for the new offer, and clear the offer_number so user can set a new one
    # Also set today's date
    today = date.today().isoformat()
    
    cur.execute("""
        INSERT INTO offers (
            offer_number, date,
            client_name, client_address, client_email, client_phone, client_pib, client_mb,
            currency, exchange_rate,
            discount_percent, vat_percent,
            total_net, total_discount, total_net_after_discount,
            total_vat, total_gross,
            payment_terms, delivery_terms, validity_days, notes, napomena, is_template, country
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?);
    """, (
        "", today,
        offer["client_name"], offer["client_address"], offer["client_email"], offer["client_phone"], offer["client_pib"], offer["client_mb"],
        offer["currency"], offer["exchange_rate"],
        offer["discount_percent"], offer["vat_percent"],
        offer["total_net"], offer["total_discount"], offer["total_net_after_discount"],
        offer["total_vat"], offer["total_gross"],
        offer["payment_terms"], offer["delivery_terms"], offer["validity_days"], offer["notes"], offer["napomena"], offer["country"]
    ))
    new_offer_id = cur.lastrowid

    # 3. Copy items
    cur.execute("SELECT * FROM offer_items WHERE offer_id = ? ORDER BY line_order;", (offer_id,))
    items = cur.fetchall()
    for item in items:
        cur.execute("""
            INSERT INTO offer_items (
                offer_id, product_id, line_order,
                item_name, item_description, item_photo_path,
                quantity, unit_price, discount_percent, line_net
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            new_offer_id, item["product_id"], item["line_order"],
            item["item_name"], item["item_description"], item["item_photo_path"],
            item["quantity"], item["unit_price"], item["discount_percent"], item["line_net"]
        ))

    conn.commit()
    conn.close()

    return redirect(url_for("edit_offer", offer_id=new_offer_id))

@app.route("/offers/<int:offer_id>/delete", methods=["POST"])
def delete_offer(offer_id):
    conn = get_db()
    cur = conn.cursor()

    # First delete items for this offer
    cur.execute("DELETE FROM offer_items WHERE offer_id = ?;", (offer_id,))

    # Then delete the offer itself
    cur.execute("DELETE FROM offers WHERE id = ?;", (offer_id,))

    conn.commit()
    conn.close()
    return redirect(url_for("list_offers"))

@app.route("/offers/<int:offer_id>/reorder", methods=["POST"])
def update_item_order(offer_id):
    data = request.json
    item_ids = data.get("item_ids", [])
    if not item_ids:
        return jsonify({"success": False, "message": "No item IDs provided"}), 400

    conn = get_db()
    cur = conn.cursor()
    try:
        for idx, item_id in enumerate(item_ids, start=1):
            cur.execute("""
                UPDATE offer_items
                SET line_order = ?
                WHERE id = ? AND offer_id = ?;
            """, (idx, item_id, offer_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": str(e)}), 500
    finally:
        conn.close()

    return jsonify({"success": True})

@app.route("/compare")
def compare_offers():
    """Comparison tool - pure JS based, no DB saving."""
    conn = get_db()
    cur = conn.cursor()
    
    # Build products query with latest price
    query = """
        SELECT 
            p.id, 
            p.name, 
            p.brand, 
            p.category, 
            p.description,
            p.photo_path,
            (
                SELECT pr.final_price 
                FROM prices pr 
                WHERE pr.product_id = p.id 
                ORDER BY pr.date DESC 
                LIMIT 1
            ) AS latest_price
        FROM products p
        ORDER BY p.name;
    """
    cur.execute(query)
    products = cur.fetchall()

    # Brand options for dropdown
    cur.execute("""
        SELECT DISTINCT brand
        FROM products
        WHERE brand IS NOT NULL AND brand != ''
        ORDER BY brand;
    """)
    brand_rows = cur.fetchall()
    brand_options = [row["brand"] for row in brand_rows]

    # Category options for dropdown
    cur.execute("""
        SELECT DISTINCT category
        FROM products
        WHERE category IS NOT NULL AND category != ''
        ORDER BY category;
    """)
    cat_rows = cur.fetchall()
    category_options = [row["category"] for row in cat_rows]

    conn.close()
    
    return render_template("compare.html", 
                           products=products, 
                           brand_options=brand_options, 
                           category_options=category_options)



@app.context_processor
def inject_helpers():
    fmt = get_date_format()
    return dict(
        format_amount=format_amount,
        format_date=lambda d: format_date(d, fmt)
    )

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", debug=True, port=5001)
