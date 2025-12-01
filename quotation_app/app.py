from flask import Flask, render_template, request, redirect, url_for, send_from_directory, send_file, jsonify
import sqlite3
import os
import sys
import io
import pdfkit
import requests
from weasyprint import HTML, CSS
from datetime import date
from pathlib import Path

# Base directory = the "Custom" folder (parent of this app folder)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# app_data folder inside Custom
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")

# pricing.db inside app_data
DATABASE = os.path.join(APP_DATA_DIR, "pricing.db")

# product_images inside app_data
IMAGE_DIR = os.path.join(APP_DATA_DIR, "product_images")

# app_assets inside app_data
APP_ASSETS_DIR = os.path.join(BASE_DIR, "app_assets")

#  common_utils app import
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from common_utils import format_amount

# static/css path
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static"
)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

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
            notes TEXT
        );
    """)

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
            line_net REAL NOT NULL,
            FOREIGN KEY (offer_id) REFERENCES offers(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
    """)

    conn.commit()
    conn.close()

import requests  # make sure this is at the top of the file

def get_nbs_eur_middle_rate():
    """
    Get today's srednji kurs EUR/RSD from Kurs API (uses NBS data).
    Returns float (e.g. 117.35) or None on error.
    """
    url = "https://kurs.resenje.org/api/v1/currencies/eur/rates/today"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        # According to Kurs API docs, field is 'exchange_middle'
        rate = data.get("exchange_middle")
        if rate is None:
            return None
        return float(rate)
    except Exception as e:
        print("Error fetching EUR/RSD rate:", e)
        return None


@app.context_processor
def inject_helpers():
    return dict(format_amount=format_amount)

@app.route("/api/nbs_eur_rate")
def api_nbs_eur_rate():
    rate = get_nbs_eur_middle_rate()
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

@app.route("/offers")
def list_offers():
    search_term = (request.args.get("search") or "").strip()
    date_from = request.args.get("date_from") or ""
    date_to = request.args.get("date_to") or ""

    conn = get_db()
    cur = conn.cursor()

    query = """
        SELECT *
        FROM offers
    """
    params = []
    clauses = []

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

    if clauses:
        query += " WHERE " + " AND ".join(clauses)

    query += " ORDER BY date DESC, id DESC;"

    cur.execute(query, params)
    offers = cur.fetchall()
    conn.close()

    return render_template(
        "offers.html",
        offers=offers,
        search_term=search_term,
        date_from=date_from,
        date_to=date_to,
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

        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO offers (
                offer_number, date,
                client_name, client_address, client_email, client_phone,
                currency, exchange_rate,
                discount_percent, vat_percent,
                total_net, total_discount, total_net_after_discount,
                total_vat, total_gross,
                payment_terms, delivery_terms, validity_days, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?, ?, ?);
        """, (
            offer_number, date_str,
            client_name, client_address, client_email, client_phone,
            currency, exchange_rate,
            discount_percent, vat_percent,
            payment_terms, delivery_terms, validity_days, notes
        ))
        offer_id = cur.lastrowid
        conn.commit()
        conn.close()

        return redirect(url_for("edit_offer", offer_id=offer_id))

    # GET
    return render_template("offer_form.html", offer=None, today=date.today().isoformat())


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

    # Load offer
    cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
    offer = cur.fetchone()
    if offer is None:
        conn.close()
        return "Offer not found", 404

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_header":
            date_str = request.form.get("date") or date.today().isoformat()
            offer_number = (request.form.get("offer_number") or "").strip()
            client_name = (request.form.get("client_name") or "").strip()
            client_address = (request.form.get("client_address") or "").strip()
            client_email = (request.form.get("client_email") or "").strip()
            client_phone = (request.form.get("client_phone") or "").strip()

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

            cur.execute("""
                UPDATE offers
                SET offer_number = ?, date = ?,
                    client_name = ?, client_address = ?, client_email = ?, client_phone = ?,
                    currency = ?, exchange_rate = ?,
                    discount_percent = ?, vat_percent = ?,
                    payment_terms = ?, delivery_terms = ?, validity_days = ?, notes = ?
                WHERE id = ?;
            """, (
                offer_number, date_str,
                client_name, client_address, client_email, client_phone,
                currency, exchange_rate,
                discount_percent, vat_percent,
                payment_terms, delivery_terms, validity_days, notes,
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
                # If you want to use description from product by default:
                if not item_description:
                    item_description = prod_row["description"] or ""
                item_photo_path = prod_row["photo_path"] or None

                # If unit price is not manually entered, use latest final price
                if not unit_price_input:
                    # latest price
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

            line_net = quantity * unit_price

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
                    quantity, unit_price, line_net
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                offer_id,
                int(product_id) if product_id else None,
                next_order,
                item_name, item_description, item_photo_path,
                quantity, unit_price, line_net
            ))
            conn.commit()
            recalc_totals(offer_id)

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
    brand_filter = request.args.get("brand")
    category_filter = request.args.get("category")
    search_term = request.args.get("search") or ""
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
    conn.close()
    return render_template("offer_view.html", offer=offer, items=items)

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
    conn.close()

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

    # ---- Logo URI ----
    logo_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
    logo_uri = Path(logo_path).as_uri()

    # Render HTML (note: we pass items_for_pdf, logo_uri, pdf_mode=True)
    html_string = render_template(
        "pdf_offer.html",
        offer=offer,
        items=items_for_pdf,
        pdf_mode=True,
        logo_uri=logo_uri,
    )

    pdf_css_path = os.path.join(BASE_DIR, "static", "css", "pdf.css")

    pdf_bytes = HTML(string=html_string).write_pdf(
        stylesheets=[CSS(filename=pdf_css_path)]
    )

    num = offer["offer_number"] or offer["id"]
    filename = f"Ponuda_{num}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )

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

@app.route("/offers/<int:offer_id>/duplicate", methods=["POST"])
def duplicate_offer(offer_id):
    conn = get_db()
    cur = conn.cursor()

    # Load original offer
    cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
    offer = cur.fetchone()
    if offer is None:
        conn.close()
        return "Offer not found", 404

    # Insert new offer: copy header, reset totals, new date, empty offer_number
    new_date = date.today().isoformat()
    cur.execute("""
        INSERT INTO offers (
            offer_number, date,
            client_name, client_address, client_email, client_phone,
            currency, exchange_rate,
            discount_percent, vat_percent,
            total_net, total_discount, total_net_after_discount,
            total_vat, total_gross,
            payment_terms, delivery_terms, validity_days, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?, ?, ?);
    """, (
        "",                         # new offer_number (you can type it later)
        new_date,
        offer["client_name"],
        offer["client_address"],
        offer["client_email"],
        offer["client_phone"],
        offer["currency"],
        offer["exchange_rate"],
        offer["discount_percent"] or 0.0,
        offer["vat_percent"] or 0.0,
        offer["payment_terms"],
        offer["delivery_terms"],
        offer["validity_days"],
        offer["notes"],
    ))
    new_offer_id = cur.lastrowid

    # Copy all items
    cur.execute("""
        SELECT *
        FROM offer_items
        WHERE offer_id = ?
        ORDER BY line_order, id;
    """, (offer_id,))
    items = cur.fetchall()

    for it in items:
        cur.execute("""
            INSERT INTO offer_items (
                offer_id, product_id, line_order,
                item_name, item_description, item_photo_path,
                quantity, unit_price, line_net
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            new_offer_id,
            it["product_id"],
            it["line_order"],
            it["item_name"],
            it["item_description"],
            it["item_photo_path"],
            it["quantity"],
            it["unit_price"],
            it["line_net"],
        ))

    conn.commit()
    conn.close()

    # Recalculate totals for the new offer
    recalc_totals(new_offer_id)

    # Go straight to edit screen of the new offer
    return redirect(url_for("edit_offer", offer_id=new_offer_id))

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", debug=True, port=5001)
