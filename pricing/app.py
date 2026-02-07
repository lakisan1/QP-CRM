from flask import Flask, render_template, request, redirect, url_for, send_from_directory, send_file, session, jsonify
import requests
import sqlite3
import os
import sys
import re
import csv
import io
import zipfile
from PIL import Image
from datetime import date

# Base directory = the "Custom" folder (parent of this app folder)
# We now use shared.config for this.
import sys
import os

# Ensure we can import 'shared' from parent dir
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from shared.config import BASE_DIR, APP_DATA_DIR, DATABASE, IMAGE_DIR, STATIC_DIR
from shared.db import get_db
from shared.auth import check_password

# import common_utils (it's in PARENT_DIR)
# we already added PARENT_DIR to sys.path above
from shared.utils import format_amount, format_date

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static"
)
app.secret_key = "crm_pricing_secret_key_change_me"
app.config['SESSION_COOKIE_NAME'] = 'pricing_session'

@app.before_request
def check_auth():
    # Exempt login page and static files from authentication
    if request.endpoint in ('login', 'static'):
        return None
    
    if not session.get('authenticated'):
        return redirect(url_for('login'))


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # Products table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            brand TEXT,
            photo_path TEXT
        );
    """)

    # Category defaults table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS category_pricing_defaults (
            category TEXT PRIMARY KEY,
            import_percent REAL,        -- e.g. 0.07 for 7%
            margin_percent REAL,        -- e.g. 0.40 for 40%
            domestic_transport REAL,    -- fixed cost per unit
            default_extras REAL,        -- extra costs per unit
            warranty_percent REAL,
            service_percent REAL,
            instalation REAL,
            traning REAL,
            other REAL
        );
    """)

    # Brands table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brands (
            name TEXT PRIMARY KEY
        );
    """)

    # Global Settings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS global_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # Set default date format if not exists
    cur.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('date_format', 'YYYY-MM-DD');")

    # Prices table (base definition)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            date TEXT NOT NULL,

            base_price REAL NOT NULL,       -- CENA
            extras REAL DEFAULT 0,          -- dodaci
            import_percent REAL,            -- tro.uvoz (0.07 = 7%)
            margin_percent REAL,            -- marža (0.40 = 40%)
            domestic_transport REAL,        -- Dom. tr.

            warranty_percent REAL,
            service_percent REAL,
            instalation REAL,
            traning REAL,
            other REAL,

            base_total REAL,                -- base_price + extras
            cost_total REAL,                -- total cost
            calculated_price REAL,          -- theoretical price
            final_price REAL,               -- your nice rounded price
            profit_final REAL,              -- final_price - cost_total

            discount_percent REAL,          -- 0.10 for 10% discount
            discount_price REAL,            -- final_price after discount
            profit_discount REAL,           -- discount_price - cost_total

            FOREIGN KEY (product_id) REFERENCES products(id)
        );
    """)

    # Offers table (referenced by indices)
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
            notes TEXT,
            napomena TEXT
        );
    """)

    # Offer items table (referenced by indices)
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

    # CREATE INDEX IF NOT EXISTS
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_prices_product_id ON prices(product_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_client_name ON offers(client_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_offer_number ON offers(offer_number);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offer_items_offer_id ON offer_items(offer_id);")

    # For old DBs that already had "prices" without discount columns,
    # try to add them. If they exist, ignore the error.
    try:
        cur.execute("ALTER TABLE prices ADD COLUMN discount_percent REAL;")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE prices ADD COLUMN discount_price REAL;")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE prices ADD COLUMN profit_discount REAL;")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()

def migrate_schema():
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Add columns to category_pricing_defaults if missing
    new_cols = [
        ("warranty_percent", "REAL"),
        ("service_percent", "REAL"),
        ("instalation", "REAL"),
        ("traning", "REAL"),
        ("other", "REAL")
    ]
    for col_name, col_type in new_cols:
        try:
            cur.execute(f"ALTER TABLE category_pricing_defaults ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass

    # 2. Add columns to prices if missing
    for col_name, col_type in new_cols:
        try:
            cur.execute(f"ALTER TABLE prices ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass

    # 3. Add discount columns to prices if missing (legacy)
    discount_cols = [
        ("discount_percent", "REAL"),
        ("discount_price", "REAL"),
        ("profit_discount", "REAL")
    ]
    for col_name, col_type in discount_cols:
        try:
            cur.execute(f"ALTER TABLE prices ADD COLUMN {col_name} {col_type}")
        except sqlite3.OperationalError:
            pass

    # 4. Remove UNIQUE constraint from prices if present
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='prices'")
    row = cur.fetchone()
    # Check if constraint exists in definition
    if row and "UNIQUE" in row["sql"] and "product_id" in row["sql"] and "date" in row["sql"]:
        print("Migrating prices table: removing UNIQUE(product_id, date) constraint...")
        
        # Rename old table
        cur.execute("ALTER TABLE prices RENAME TO prices_old")
        
        # Re-create table with NEW schema (from updated init_db logic)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                date TEXT NOT NULL,
    
                base_price REAL NOT NULL,
                extras REAL DEFAULT 0,
                import_percent REAL,
                margin_percent REAL,
                domestic_transport REAL,
    
                warranty_percent REAL,
                service_percent REAL,
                instalation REAL,
                traning REAL,
                other REAL,

                base_total REAL,
                cost_total REAL,
                calculated_price REAL,
                final_price REAL,
                profit_final REAL,
    
                discount_percent REAL,
                discount_price REAL,
                profit_discount REAL,
    
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
        """)
        
        cur.execute("CREATE INDEX IF NOT EXISTS idx_prices_product_id ON prices(product_id);")

        # Copy data
        # Since we added columns to prices_old (step 2), schemas match
        cur.execute("INSERT INTO prices SELECT * FROM prices_old")
        cur.execute("DROP TABLE prices_old")
        
    conn.commit()
    conn.close()

from PIL import Image
import os
import re

# ... your other config/imports ...

def apply_rounding(val, target='price'):
    if val <= 0:
        return 0
    
    conn = get_db()
    cur = conn.cursor()
    # Find the matching rule: smallest limit >= val
    cur.execute("""
        SELECT step_val, method 
        FROM price_rounding_rules 
        WHERE target = ? AND limit_val >= ? 
        ORDER BY limit_val ASC 
        LIMIT 1;
    """, (target, val))
    rule = cur.fetchone()
    
    if not rule:
        # Fallback to the largest limit rule for this target
        cur.execute("""
            SELECT step_val, method 
            FROM price_rounding_rules 
            WHERE target = ? 
            ORDER BY limit_val DESC 
            LIMIT 1;
        """, (target,))
        rule = cur.fetchone()
    
    conn.close()
    
    if not rule:
        return val # No rules defined
        
    step = rule["step_val"]
    method = rule["method"]
    
    import math
    if method == 'UP':
        return math.ceil(val / step) * step
    elif method == 'DOWN':
        return math.floor(val / step) * step
    elif method == 'NEAREST':
        return round(val / step) * step
    else:
        return math.ceil(val / step) * step

def save_product_image(image_stream, orig_filename, product_name):
    """
    Process and save an image (from stream) to IMAGE_DIR, resized to max 800x800.
    Returns the filename (e.g. 'my_product.jpg') or raises ValueError.
    """
    if not image_stream or not orig_filename:
        return None

    # Check extension
    ext = os.path.splitext(orig_filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png"]:
        raise ValueError("Slika mora biti JPG ili PNG (.jpg, .jpeg, ili .png).")

    # Build base name from product_name
    base = (product_name or "").strip().lower()
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^a-z0-9_-]", "", base)
    if not base:
        base = "product"

    filename = base + ".jpg"

    os.makedirs(IMAGE_DIR, exist_ok=True)
    dest_path = os.path.join(IMAGE_DIR, filename)

    try:
        img = Image.open(image_stream)

        # PNG Transparency handling
        if 'A' in img.mode:
            img = img.convert("RGBA")
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize
        max_size = (800, 800)
        img.thumbnail(max_size)

        # Save as JPEG
        img.save(dest_path, format="JPEG", quality=85)
        
    except Exception as e:
        raise ValueError("Greška pri obradi slike: " + str(e))

    return filename

def get_date_format():
    """Fetch the date_format setting from global_settings table."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM global_settings WHERE key = 'date_format';")
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else "YYYY-MM-DD"

def get_theme():
    """Fetch the theme setting from global_settings table."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM global_settings WHERE key = 'theme';")
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else "dark"

import requests

def download_image_from_url(url):
    """
    Download image from URL, validate it's an image.
    Returns (stream, filename) or raises ValueError.
    """
    try:
        resp = requests.get(url, timeout=10, stream=True)
        resp.raise_for_status()
        
        content_type = resp.headers.get('Content-Type', '').lower()
        if 'image/jpeg' not in content_type and 'image/png' not in content_type:
            raise ValueError("URL ne vodi do JPG ili PNG slike.")

        # Get original filename from URL or default to url_image.jpg
        orig_filename = url.split("/")[-1].split("?")[0] or "url_image.jpg"
        if not any(orig_filename.lower().endswith(ex) for ex in ['.jpg', '.jpeg', '.png']):
            # force extension based on content-type if missing
            if 'png' in content_type: orig_filename += '.png'
            else: orig_filename += '.jpg'

        return io.BytesIO(resp.content), orig_filename

    except requests.exceptions.RequestException as e:
        raise ValueError(f"Greška pri preuzimanju slike sa URL-a: {str(e)}")


def get_nbs_rate(currency="eur"):
    """
    Get today's middle rate for a currency from Kurs API (uses NBS data).
    Returns float or None on error.
    """
    url = f"https://kurs.resenje.org/api/v1/currencies/{currency.lower()}/rates/today"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        rate = data.get("exchange_middle")
        if rate is None:
            return None
        return float(rate)
    except Exception as e:
        print(f"Error fetching {currency} rate:", e)
        return None

@app.route("/api/nbs_rate/<currency>")
def api_nbs_rate(currency):
    rate = get_nbs_rate(currency)
    if rate is None:
        return jsonify({"success": False, "message": f"Neuspešno preuzimanje kursa za {currency} sa NBS."}), 500
    return jsonify({"success": True, "rate": rate})
@app.route("/")
def index():
    return redirect(url_for("list_products"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if check_password("pricing", request.form.get("password")):
            session['authenticated'] = True
            return redirect(url_for('index'))
        else:
            error = "Pogrešna lozinka"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login'))

@app.route("/product-image/<path:filename>")
def product_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route("/settings", methods=["GET", "POST"])
def settings():
    conn = get_db()
    if request.method == "POST":
        if "date_format" in request.form:
            date_fmt = request.form.get("date_format")
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('date_format', ?);", (date_fmt,))
            conn.commit()
        
        if "theme" in request.form:
            theme = request.form.get("theme")
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES ('theme', ?);", (theme,))
            conn.commit()
    
    cur = conn.cursor()
    cur.execute("SELECT value FROM global_settings WHERE key = 'date_format';")
    row = cur.fetchone()
    current_fmt = row["value"] if row else "YYYY-MM-DD"

    cur.execute("SELECT value FROM global_settings WHERE key = 'theme';")
    row = cur.fetchone()
    current_theme = row["value"] if row else "dark"

    conn.close()
    return render_template("settings.html", current_date_format=current_fmt, current_theme=current_theme)

@app.template_filter('format_date')
def _format_date_filter(date_str):
    fmt = get_date_format()
    return format_date(date_str, fmt)

@app.context_processor
def inject_helpers():
    return dict(
        format_amount=format_amount,
        theme=get_theme()
    )

# ---------- PRODUCTS ----------

@app.route("/products")
def list_products():
    # Check if we should clear filters
    if request.args.get("clear"):
        session.pop("products_filter_brand", None)
        session.pop("products_filter_category", None)
        session.pop("products_filter_search", None)
        return redirect(url_for("list_products"))

    # Load from request or fallback to session
    brand_filter = request.args.get("brand")
    if brand_filter is None:
        brand_filter = session.get("products_filter_brand", "")
    else:
        session["products_filter_brand"] = brand_filter

    category_filter = request.args.get("category")
    if category_filter is None:
        category_filter = session.get("products_filter_category", "")
    else:
        session["products_filter_category"] = category_filter

    search_term = request.args.get("search")
    if search_term is None:
        search_term = session.get("products_filter_search", "")
    else:
        session["products_filter_search"] = search_term

    conn = get_db()
    cur = conn.cursor()

    # Base query: products + latest price
    query = """
        SELECT p.*,
               pr.final_price AS current_price,
               pr.discount_price AS current_discount_price
        FROM products p
        LEFT JOIN prices pr
          ON pr.id = (
              SELECT MAX(id) FROM prices WHERE product_id = p.id
          )
    """
    params = []

    where_clauses = []
    if brand_filter:
        where_clauses.append("p.brand = ?")
        params.append(brand_filter)
    if category_filter:
        where_clauses.append("p.category = ?")
        params.append(category_filter)
    if search_term:
        # search by name (case-insensitive-ish)
        where_clauses.append("p.name LIKE ?")
        params.append(f"%{search_term}%")

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    # Fixed sort by name (and category as secondary)
    query += " ORDER BY p.name, p.category;"

    cur.execute(query, params)
    products = cur.fetchall()

    # Distinct brands for dropdown
    cur.execute("""
        SELECT DISTINCT brand
        FROM products
        WHERE brand IS NOT NULL AND brand != ''
        ORDER BY brand;
    """)
    brand_rows = cur.fetchall()
    brand_options = [row["brand"] for row in brand_rows]

    # Categories for dropdown (from category defaults)
    cur.execute("""
        SELECT category
        FROM category_pricing_defaults
        ORDER BY category;
    """)
    cat_rows = cur.fetchall()
    category_options = [row["category"] for row in cat_rows]

    conn.close()

    return render_template(
        "products.html",
        products=products,
        brand_filter=brand_filter,
        category_filter=category_filter,
        brand_options=brand_options,
        category_options=category_options,
        search_term=search_term,
    )
@app.route("/products/quick_update")
def quick_update_products():
    # Check if we should clear filters
    if request.args.get("clear"):
        session.pop("products_filter_brand", None)
        session.pop("products_filter_category", None)
        session.pop("products_filter_search", None)
        return redirect(url_for("quick_update_products"))

    # Load from request or fallback to session
    brand_filter = request.args.get("brand")
    if brand_filter is None:
        brand_filter = session.get("products_filter_brand", "")
    else:
        session["products_filter_brand"] = brand_filter

    category_filter = request.args.get("category")
    if category_filter is None:
        category_filter = session.get("products_filter_category", "")
    else:
        session["products_filter_category"] = category_filter

    search_term = request.args.get("search")
    if search_term is None:
        search_term = session.get("products_filter_search", "")
    else:
        session["products_filter_search"] = search_term

    conn = get_db()
    cur = conn.cursor()

    # Base query: products + latest base_price + latest extras + current prices
    query = """
        SELECT p.*,
               pr.base_price AS latest_base_price,
               pr.extras AS latest_extras,
               pr.final_price AS current_price,
               pr.discount_price AS current_discount_price
        FROM products p
        LEFT JOIN prices pr
          ON pr.id = (
              SELECT MAX(id) FROM prices WHERE product_id = p.id
          )
    """
    params = []

    where_clauses = []
    if brand_filter:
        where_clauses.append("p.brand = ?")
        params.append(brand_filter)
    if category_filter:
        where_clauses.append("p.category = ?")
        params.append(category_filter)
    if search_term:
        where_clauses.append("p.name LIKE ?")
        params.append(f"%{search_term}%")

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    query += " ORDER BY p.name, p.category;"

    cur.execute(query, params)
    products = cur.fetchall()

    # Distinct brands for dropdown
    cur.execute("""
        SELECT DISTINCT brand
        FROM products
        WHERE brand IS NOT NULL AND brand != ''
        ORDER BY brand;
    """)
    brand_rows = cur.fetchall()
    brand_options = [row["brand"] for row in brand_rows]

    # Categories for dropdown (from category defaults)
    cur.execute("""
        SELECT category
        FROM category_pricing_defaults
        ORDER BY category;
    """)
    cat_rows = cur.fetchall()
    category_options = [row["category"] for row in cat_rows]

    conn.close()

    return render_template(
        "quick_update.html",
        products=products,
        brand_filter=brand_filter,
        category_filter=category_filter,
        brand_options=brand_options,
        category_options=category_options,
        search_term=search_term,
    )

@app.route("/products/<int:product_id>/quick_update_save", methods=["POST"])
def quick_update_save(product_id):
    if request.method != "POST":
        return redirect(url_for("quick_update_products"))
        
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Get new inputs
    new_base_price = float(request.form.get("base_price") or 0)
    new_extras = float(request.form.get("extras") or 0)
    
    # 2. Get existing latest price for coefficients
    cur.execute("SELECT * FROM prices WHERE product_id = ? ORDER BY date DESC, id DESC LIMIT 1;", (product_id,))
    latest_price = cur.fetchone()
    
    # Defaults
    import_percent = 0.0
    margin_percent = 0.0
    warranty_percent = 0.0
    service_percent = 0.0
    domestic_transport = 0.0
    instalation = 0.0
    traning = 0.0
    other = 0.0
    
    if latest_price:
        import_percent = latest_price["import_percent"] or 0
        margin_percent = latest_price["margin_percent"] or 0
        warranty_percent = latest_price["warranty_percent"] or 0
        service_percent = latest_price["service_percent"] or 0
        domestic_transport = latest_price["domestic_transport"] or 0
        instalation = latest_price["instalation"] or 0
        traning = latest_price["traning"] or 0
        other = latest_price["other"] or 0
    else:
        # Fallback to category defaults if no price history
        cur.execute("SELECT category FROM products WHERE id=?", (product_id,))
        prod = cur.fetchone()
        if prod and prod["category"]:
            cur.execute("SELECT * FROM category_pricing_defaults WHERE category=?", (prod["category"],))
            cat_def = cur.fetchone()
            if cat_def:
                import_percent = cat_def["import_percent"] or 0
                margin_percent = cat_def["margin_percent"] or 0
                warranty_percent = cat_def["warranty_percent"] or 0
                service_percent = cat_def["service_percent"] or 0
                domestic_transport = cat_def["domestic_transport"] or 0
                instalation = cat_def["instalation"] or 0
                traning = cat_def["traning"] or 0
                other = cat_def["other"] or 0

    # 3. Calculate new totals
    base_total = new_base_price + new_extras
    cost_total = base_total * (1 + import_percent + warranty_percent + service_percent) + domestic_transport + instalation + traning + other
    calculated_price = cost_total * (1 + margin_percent)
    final_price = apply_rounding(calculated_price)
    profit_final = final_price - cost_total
    
    # 4. Insert new price
    # Copy existing discount logic
    discount_percent = 0.0
    discount_price = None
    profit_discount = None
    
    if latest_price:
        discount_percent = latest_price["discount_percent"] or 0.0
        # If there was a discount, re-apply it
        if discount_percent > 0:
            # If percentage based, recalculate absolute price
            if final_price > 0:
                calc_discount_price = final_price * (1 - discount_percent)
                discount_price = apply_rounding(calc_discount_price, target='discount')
        elif latest_price["discount_price"]:
             # If it was a fixed price discount (no percent?), just copy it? 
             # Or is it safer to ignore fixed prices if base changed?
             # Let's assume if percent is 0 but discount_price > 0, it's a fixed override. 
             # We should probably keep the same *margin* of discount?
             # For now, let's just keep the percent logic as it's the most robust.
             pass

    if discount_price is not None:
         profit_discount = discount_price - cost_total      
    
    date_str = date.today().isoformat()
    
    cur.execute("""
        INSERT INTO prices (
            product_id, date,
            base_price, extras,
            import_percent, margin_percent,
            warranty_percent, service_percent,
            domestic_transport, instalation, traning, other,
            base_total, cost_total,
            calculated_price, final_price,
            profit_final,
            discount_percent, discount_price, profit_discount
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        product_id, date_str,
        new_base_price, new_extras,
        import_percent, margin_percent,
        warranty_percent, service_percent,
        domestic_transport, instalation, traning, other,
        base_total, cost_total,
        calculated_price, final_price,
        profit_final,
        discount_percent, discount_price, profit_discount
    ))
    
    conn.commit()
    conn.close()
    
    # 5. Redirect back with filters
    ref_brand = request.form.get("ref_brand", "")
    ref_category = request.form.get("ref_category", "")
    ref_search = request.form.get("ref_search", "")
    
    return redirect(url_for("quick_update_products", brand=ref_brand, category=ref_category, search=ref_search))

@app.route("/products/add", methods=["GET", "POST"])
def add_product():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = request.form.get("description") or ""
        category = request.form.get("category") or ""
        brand = request.form.get("brand") or ""

        # 1) check duplicate name
        cur.execute("""
            SELECT id
            FROM products
            WHERE name = ? COLLATE NOCASE;
        """, (name,))
        existing = cur.fetchone()

        # reload categories/brands for error cases
        cur.execute("SELECT category FROM category_pricing_defaults ORDER BY category;")
        cat_rows = cur.fetchall()
        cur.execute("SELECT name FROM brands ORDER BY name;")
        brand_rows = cur.fetchall()

        categories = [row["category"] for row in cat_rows]
        brand_options = [row["name"] for row in brand_rows]

        if existing:
            conn.close()
            return render_template(
                "product_form.html",
                categories=categories,
                brand_options=brand_options,
                product=None,
                error="Proizvod sa ovim imenom već postoji."
            )

        # 2) handle photo upload (file or URL)
        photo_file = request.files.get("photo_file")
        photo_url = (request.form.get("photo_url") or "").strip()
        photo_path = None
        
        try:
            if photo_file and photo_file.filename:
                # Priority 1: Manual file upload
                photo_path = save_product_image(photo_file.stream, photo_file.filename, name)
            elif photo_url:
                # Priority 2: Download from URL
                stream, orig_filename = download_image_from_url(photo_url)
                photo_path = save_product_image(stream, orig_filename, name)
        except ValueError as e:
            conn.close()
            return render_template(
                "product_form.html",
                categories=categories,
                brand_options=brand_options,
                product=None,
                error=str(e)
            )

        cur.execute("""
            INSERT INTO products (name, description, category, brand, photo_path)
            VALUES (?, ?, ?, ?, ?);
        """, (name, description, category, brand, photo_path))
        
        new_product_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Check which button was clicked
        action = request.form.get("action")
        if action == "save_add_price":
            return redirect(url_for("new_price", product_id=new_product_id))

        return redirect(url_for("list_products"))

    # GET – load existing categories and brands
    cur.execute("SELECT category FROM category_pricing_defaults ORDER BY category;")
    cat_rows = cur.fetchall()
    cur.execute("SELECT name FROM brands ORDER BY name;")
    brand_rows = cur.fetchall()
    conn.close()

    categories = [row["category"] for row in cat_rows]
    brand_options = [row["name"] for row in brand_rows]

    return render_template(
        "product_form.html",
        categories=categories,
        brand_options=brand_options,
        product=None
    )

@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
def edit_product(product_id):
    conn = get_db()
    cur = conn.cursor()

    # Load existing product
    cur.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    product = cur.fetchone()
    if product is None:
        conn.close()
        return "Product not found", 404

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        description = request.form.get("description") or ""
        category = request.form.get("category") or ""
        brand = request.form.get("brand") or ""

        # check duplicate name (but ignore this product's own id)
        cur.execute("""
            SELECT id
            FROM products
            WHERE name = ? COLLATE NOCASE
              AND id != ?;
        """, (name, product_id))
        existing = cur.fetchone()

        # reload categories/brands in case of error
        cur.execute("SELECT category FROM category_pricing_defaults ORDER BY category;")
        cat_rows = cur.fetchall()
        categories = [row["category"] for row in cat_rows]

        cur.execute("SELECT name FROM brands ORDER BY name;")
        brand_rows = cur.fetchall()
        brand_options = [row["name"] for row in brand_rows]

        if existing:
            conn.close()
            return render_template(
                "product_form.html",
                categories=categories,
                brand_options=brand_options,
                product=product,
                error="Drugi proizvod sa ovim imenom već postoji."
            )

        # handle photo upload (file or URL)
        photo_file = request.files.get("photo_file")
        photo_url = (request.form.get("photo_url") or "").strip()
        photo_path = product["photo_path"] # default to existing
        
        try:
            if photo_file and photo_file.filename:
                photo_path = save_product_image(photo_file.stream, photo_file.filename, name)
            elif photo_url:
                stream, orig_filename = download_image_from_url(photo_url)
                photo_path = save_product_image(stream, orig_filename, name)
        except ValueError as e:
            conn.close()
            return render_template(
                "product_form.html",
                categories=categories,
                brand_options=brand_options,
                product=product,
                error=str(e)
            )

        cur.execute("""
            UPDATE products
            SET name = ?, description = ?, category = ?, brand = ?, photo_path = ?
            WHERE id = ?;
        """, (name, description, category, brand, photo_path, product_id))
        conn.commit()
        conn.close()
        return redirect(url_for("list_products"))

    # GET – load categories and brands for dropdowns
    cur.execute("SELECT category FROM category_pricing_defaults ORDER BY category;")
    cat_rows = cur.fetchall()
    categories = [row["category"] for row in cat_rows]

    cur.execute("SELECT name FROM brands ORDER BY name;")
    brand_rows = cur.fetchall()
    brand_options = [row["name"] for row in brand_rows]

    conn.close()

    return render_template(
        "product_form.html",
        categories=categories,
        brand_options=brand_options,
        product=product
    )


@app.route("/products/<int:product_id>/delete", methods=["POST"])
def delete_product(product_id):
    conn = get_db()
    cur = conn.cursor()

    # 1) Detach from offers (so snapshots stay valid)
    try:
        cur.execute("""
            UPDATE offer_items
            SET product_id = NULL
            WHERE product_id = ?;
        """, (product_id,))
    except sqlite3.OperationalError:
        # If quotation tables don't exist yet, just ignore
        pass

    # 2) Delete all prices for this product
    cur.execute("DELETE FROM prices WHERE product_id = ?;", (product_id,))

    # 3) Delete the product itself
    cur.execute("DELETE FROM products WHERE id = ?;", (product_id,))

    conn.commit()
    conn.close()

    return redirect(url_for("list_products"))  # or whatever your products list endpoint is called

# ---------- CATEGORY DEFAULTS ----------

@app.route("/category-defaults", methods=["GET", "POST"])
def category_defaults():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        category = (request.form.get("category") or "").strip()
        old_category = (request.form.get("old_category") or "").strip()

        import_percent_input = float(request.form.get("import_percent") or 0)
        margin_percent_input = float(request.form.get("margin_percent") or 0)
        domestic_transport = float(request.form.get("domestic_transport") or 0)
        default_extras = float(request.form.get("default_extras") or 0)
        
        warranty_percent_input = float(request.form.get("warranty_percent") or 0)
        service_percent_input = float(request.form.get("service_percent") or 0)
        instalation = float(request.form.get("instalation") or 0)
        traning = float(request.form.get("traning") or 0)
        other = float(request.form.get("other") or 0)

        # store as fractions (0.07 for 7%)
        import_percent = import_percent_input / 100.0
        margin_percent = margin_percent_input / 100.0
        warranty_percent = warranty_percent_input / 100.0
        service_percent = service_percent_input / 100.0

        if category:
            if old_category and old_category != category:
                # RENAME category: update defaults + products
                try:
                    # Update the category name + values in defaults
                    cur.execute("""
                        UPDATE category_pricing_defaults
                        SET category = ?, import_percent = ?, margin_percent = ?,
                            domestic_transport = ?, default_extras = ?,
                            warranty_percent = ?, service_percent = ?,
                            instalation = ?, traning = ?, other = ?
                        WHERE category = ?;
                    """, (
                        category,
                        import_percent, margin_percent,
                        domestic_transport, default_extras,
                        warranty_percent, service_percent,
                        instalation, traning, other,
                        old_category
                    ))

                    # Update products that used the old category
                    cur.execute("""
                        UPDATE products
                        SET category = ?
                        WHERE category = ?;
                    """, (category, old_category))

                    conn.commit()
                except sqlite3.IntegrityError:
                    # New category name already exists – just ignore / rollback
                    conn.rollback()
            else:
                # Normal insert/update (no rename)
                cur.execute("""
                    INSERT INTO category_pricing_defaults (
                        category, import_percent, margin_percent,
                        domestic_transport, default_extras,
                        warranty_percent, service_percent,
                        instalation, traning, other
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(category) DO UPDATE SET
                        import_percent = excluded.import_percent,
                        margin_percent = excluded.margin_percent,
                        domestic_transport = excluded.domestic_transport,
                        default_extras = excluded.default_extras,
                        warranty_percent = excluded.warranty_percent,
                        service_percent = excluded.service_percent,
                        instalation = excluded.instalation,
                        traning = excluded.traning,
                        other = excluded.other;
                """, (
                    category,
                    import_percent, margin_percent,
                    domestic_transport, default_extras,
                    warranty_percent, service_percent,
                    instalation, traning, other
                ))
                conn.commit()

    cur.execute("SELECT * FROM category_pricing_defaults ORDER BY category;")
    defaults = cur.fetchall()
    conn.close()

    return render_template("category_defaults.html", defaults=defaults, error=request.args.get("error"))

@app.route("/category-defaults/delete", methods=["POST"])
def delete_category_default():
    cat_to_delete = request.form.get("category_to_delete")
    if not cat_to_delete:
        return redirect(url_for("category_defaults"))
    
    conn = get_db()
    cur = conn.cursor()

    # Check if used
    cur.execute("SELECT id FROM products WHERE category = ? LIMIT 1;", (cat_to_delete,))
    in_use = cur.fetchone()

    if in_use:
        conn.close()
        return redirect(url_for("category_defaults", error=f"Cannot delete category '{cat_to_delete}' because it is used by one or more products."))

    cur.execute("DELETE FROM category_pricing_defaults WHERE category = ?;", (cat_to_delete,))
    conn.commit()
    conn.close()
    
    return redirect(url_for("category_defaults"))

@app.route("/brands", methods=["GET", "POST"])
def brands():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        old_name = (request.form.get("old_name") or "").strip()

        if name:
            if old_name and old_name != name:
                # Rename brand: update brands table and products that use it
                try:
                    # Update brand name
                    cur.execute("UPDATE brands SET name = ? WHERE name = ?;", (name, old_name))
                    # Update products that referenced the old brand
                    cur.execute("UPDATE products SET brand = ? WHERE brand = ?;", (name, old_name))
                    conn.commit()
                except sqlite3.IntegrityError:
                    # New name already exists as a brand – do nothing or handle as needed
                    conn.rollback()
            else:
                # Just insert new brand (ignore if it already exists)
                cur.execute("""
                    INSERT INTO brands (name)
                    VALUES (?)
                    ON CONFLICT(name) DO NOTHING;
                """, (name,))
                conn.commit()

    cur.execute("SELECT name FROM brands ORDER BY name;")
    rows = cur.fetchall()
    conn.close()

    return render_template("brands.html", brands=rows, error=request.args.get("error"))

@app.route("/brands/delete", methods=["POST"])
def delete_brand():
    brand_to_delete = request.form.get("brand_to_delete")
    if not brand_to_delete:
        return redirect(url_for("brands"))

    conn = get_db()
    cur = conn.cursor()

    # Check if used
    cur.execute("SELECT id FROM products WHERE brand = ? LIMIT 1;", (brand_to_delete,))
    in_use = cur.fetchone()

    if in_use:
        conn.close()
        return redirect(url_for("brands", error=f"Cannot delete brand '{brand_to_delete}' because it is used by one or more products."))

    cur.execute("DELETE FROM brands WHERE name = ?;", (brand_to_delete,))
    conn.commit()
    conn.close()

    return redirect(url_for("brands"))

# ---------- PRICES ----------

@app.route("/products/<int:product_id>/prices")
def price_history(product_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    product = cur.fetchone()
    if product is None:
        conn.close()
        return "Product not found", 404

    cur.execute("""
        SELECT *
        FROM prices
        WHERE product_id = ?
        ORDER BY date DESC;
    """, (product_id,))
    prices = cur.fetchall()

    conn.close()
    return render_template("price_history.html", product=product, prices=prices)


@app.route("/products/<int:product_id>/prices/new", methods=["GET", "POST"])
def new_price(product_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    product = cur.fetchone()
    if product is None:
        conn.close()
        return "Product not found", 404

    # Load defaults for this product's category (if any)
    defaults = {
        "import_percent": 0.0,
        "margin_percent": 0.0,
        "domestic_transport": 0.0,
        "default_extras": 0.0,
        "warranty_percent": 0.0,
        "service_percent": 0.0,
        "instalation": 0.0,
        "traning": 0.0,
        "other": 0.0,
    }
    if product["category"]:
        cur.execute("""
            SELECT * FROM category_pricing_defaults
            WHERE category = ?;
        """, (product["category"],))
        row = cur.fetchone()
        if row:
            defaults = {
                "import_percent": row["import_percent"],
                "margin_percent": row["margin_percent"],
                "domestic_transport": row["domestic_transport"],
                "default_extras": row["default_extras"],
                "warranty_percent": row["warranty_percent"] or 0,
                "service_percent": row["service_percent"] or 0,
                "instalation": row["instalation"] or 0,
                "traning": row["traning"] or 0,
                "other": row["other"] or 0,
            }

    if request.method == "POST":
        date_str = request.form.get("date") or date.today().isoformat()
        base_price = float(request.form.get("base_price") or 0)
        extras = float(request.form.get("extras") or 0)

        # User inputs percent as e.g. 7 (for 7%), we convert to 0.07
        import_percent_input = float(request.form.get("import_percent") or 0)
        margin_percent_input = float(request.form.get("margin_percent") or 0)
        
        warranty_percent_input = float(request.form.get("warranty_percent") or 0)
        service_percent_input = float(request.form.get("service_percent") or 0)

        import_percent = import_percent_input / 100.0
        margin_percent = margin_percent_input / 100.0
        warranty_percent = warranty_percent_input / 100.0
        service_percent = service_percent_input / 100.0

        domestic_transport = float(request.form.get("domestic_transport") or 0)
        
        # New absolute costs
        instalation = float(request.form.get("instalation") or 0)
        traning = float(request.form.get("traning") or 0)
        other = float(request.form.get("other") or 0)

        final_price = float(request.form.get("final_price") or 0)

        # Discount inputs:
        # - discount_percent: e.g. 10 for 10%
        # - discount_price: nice rounded discount price entered by user
        discount_percent_input = float(request.form.get("discount_percent") or 0)
        discount_price_input = float(request.form.get("discount_price") or 0)

        base_total = base_price + extras

        # Cost total uses import + domestic transport + warranty + service + absolute costs
        # Formula: base_total * (1 + import + warranty + service) + domestic + install + training + other
        cost_total = base_total * (1 + import_percent + warranty_percent + service_percent) + domestic_transport + instalation + traning + other

        # Calculated price: cost_total * (1 + margin)
        calculated_price = cost_total * (1 + margin_percent)

        if final_price <= 0:

            final_price = apply_rounding(calculated_price)  # fallback logic with rounding

        profit_final = final_price - cost_total

        # Discount: keep % and nice price independent
        discount_percent = 0.0
        discount_price = None
        profit_discount = None

        if discount_percent_input > 0:
            discount_percent = discount_percent_input / 100.0

        # If user typed a nice discount price, use that.
        # Otherwise, if they only typed %, suggest a price from that.
        if discount_price_input > 0:
            discount_price = discount_price_input
        elif discount_percent > 0 and final_price > 0:
            calc_discount_price = final_price * (1 - discount_percent)
            discount_price = apply_rounding(calc_discount_price, target='discount')

        if discount_price is not None:
            profit_discount = discount_price - cost_total

        cur.execute("""
            INSERT INTO prices (
                product_id, date,
                base_price, extras,
                import_percent, margin_percent,
                warranty_percent, service_percent,
                domestic_transport, instalation, traning, other,
                base_total, cost_total,
                calculated_price, final_price,
                profit_final,
                discount_percent, discount_price, profit_discount
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            product_id, date_str,
            base_price, extras,
            import_percent, margin_percent,
            warranty_percent, service_percent,
            domestic_transport, instalation, traning, other,
            base_total, cost_total,
            calculated_price, final_price,
            profit_final,
            discount_percent, discount_price, profit_discount
        ))

        conn.commit()
        conn.close()
        return redirect(url_for("price_history", product_id=product_id))

    # Load rounding rules for JS
    cur.execute("SELECT * FROM price_rounding_rules ORDER BY target, limit_val ASC;")
    rules_rows = cur.fetchall()
    rules_json = {'price': [], 'discount': []}
    for r in rules_rows:
        rules_json[r['target']].append({'limit': r['limit_val'], 'step': r['step_val'], 'method': r['method']})

    conn.close()
    # When rendering form, show percents as "x 100"
    return render_template(
        "price_form.html",
        product=product,
        defaults={
            "import_percent": defaults["import_percent"] * 100,
            "margin_percent": defaults["margin_percent"] * 100,
            "domestic_transport": defaults["domestic_transport"],
            "extras": defaults["default_extras"],
            "warranty_percent": (defaults.get("warranty_percent") or 0) * 100,
            "service_percent": (defaults.get("service_percent") or 0) * 100,
            "instalation": defaults.get("instalation") or 0,
            "traning": defaults.get("traning") or 0,
            "other": defaults.get("other") or 0,
        },
        today=date.today().isoformat(),
        price=None,
        rounding_rules=rules_json
    )

@app.route("/products/<int:product_id>/prices/<int:price_id>/edit", methods=["GET", "POST"])
def edit_price(product_id, price_id):
    conn = get_db()
    cur = conn.cursor()

    # Load product
    cur.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    product = cur.fetchone()
    if product is None:
        conn.close()
        return "Product not found", 404

    # Load existing price row
    cur.execute("SELECT * FROM prices WHERE id = ?;", (price_id,))
    price = cur.fetchone()
    if price is None or price["product_id"] != product_id:
        conn.close()
        return "Price entry not found", 404

    if request.method == "POST":
        date_str = request.form.get("date") or date.today().isoformat()
        base_price = float(request.form.get("base_price") or 0)
        extras = float(request.form.get("extras") or 0)

        import_percent_input = float(request.form.get("import_percent") or 0)
        margin_percent_input = float(request.form.get("margin_percent") or 0)
        
        warranty_percent_input = float(request.form.get("warranty_percent") or 0)
        service_percent_input = float(request.form.get("service_percent") or 0)

        import_percent = import_percent_input / 100.0
        margin_percent = margin_percent_input / 100.0
        warranty_percent = warranty_percent_input / 100.0
        service_percent = service_percent_input / 100.0

        domestic_transport = float(request.form.get("domestic_transport") or 0)
        
        # New absolute costs
        instalation = float(request.form.get("instalation") or 0)
        traning = float(request.form.get("traning") or 0)
        other = float(request.form.get("other") or 0)
        
        final_price = float(request.form.get("final_price") or 0)

        # Discount inputs
        discount_percent_input = float(request.form.get("discount_percent") or 0)
        discount_price_input = float(request.form.get("discount_price") or 0)

        base_total = base_price + extras

        # Formula: base_total * (1 + import + warranty + service) + domestic + install + training + other
        cost_total = base_total * (1 + import_percent + warranty_percent + service_percent) + domestic_transport + instalation + traning + other

        # Calculated price: cost_total * (1 + margin)
        calculated_price = cost_total * (1 + margin_percent)

        if final_price <= 0:
            final_price = apply_rounding(calculated_price)

        profit_final = final_price - cost_total

        # Discount: keep % and nice price independent
        discount_percent = 0.0
        discount_price = None
        profit_discount = None

        if discount_percent_input > 0:
            discount_percent = discount_percent_input / 100.0

        if discount_price_input > 0:
            discount_price = discount_price_input
        elif discount_percent > 0 and final_price > 0:
            calc_discount_price = final_price * (1 - discount_percent)
            discount_price = apply_rounding(calc_discount_price, target='discount')

        if discount_price is not None:
            profit_discount = discount_price - cost_total

        cur.execute("""
            UPDATE prices
            SET date = ?,
                base_price = ?, extras = ?,
                import_percent = ?, margin_percent = ?,
                warranty_percent = ?, service_percent = ?,
                domestic_transport = ?,
                instalation = ?, traning = ?, other = ?,
                base_total = ?, cost_total = ?,
                calculated_price = ?, final_price = ?,
                profit_final = ?,
                discount_percent = ?, discount_price = ?, profit_discount = ?
            WHERE id = ?;
        """, (
            date_str,
            base_price, extras,
            import_percent, margin_percent,
            warranty_percent, service_percent,
            domestic_transport,
            instalation, traning, other,
            base_total, cost_total,
            calculated_price, final_price,
            profit_final,
            discount_percent, discount_price, profit_discount,
            price_id
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("price_history", product_id=product_id))

    # GET – load category defaults (not critical for edit, but ok)
    defaults = {
        "import_percent": 0.0,
        "margin_percent": 0.0,
        "domestic_transport": 0.0,
        "default_extras": 0.0,
        "warranty_percent": 0.0,
        "service_percent": 0.0,
        "instalation": 0.0,
        "traning": 0.0,
        "other": 0.0,
    }
    if product["category"]:
        cur.execute("""
            SELECT * FROM category_pricing_defaults
            WHERE category = ?;
        """, (product["category"],))
        row = cur.fetchone()
        if row:
            defaults = {
                "import_percent": row["import_percent"],
                "margin_percent": row["margin_percent"],
                "domestic_transport": row["domestic_transport"],
                "default_extras": row["default_extras"],
                "warranty_percent": row["warranty_percent"] or 0,
                "service_percent": row["service_percent"] or 0,
                "instalation": row["instalation"] or 0,
                "traning": row["traning"] or 0,
                "other": row["other"] or 0,
            }

    # Load rounding rules for JS
    cur.execute("SELECT * FROM price_rounding_rules ORDER BY target, limit_val ASC;")
    rules_rows = cur.fetchall()
    rules_json = {'price': [], 'discount': []}
    for r in rules_rows:
        rules_json[r['target']].append({'limit': r['limit_val'], 'step': r['step_val'], 'method': r['method']})

    conn.close()
    return render_template(
        "price_form.html",
        product=product,
        defaults={
            "import_percent": defaults["import_percent"] * 100,
            "margin_percent": defaults["margin_percent"] * 100,
            "domestic_transport": defaults["domestic_transport"],
            "extras": defaults["default_extras"],
            "warranty_percent": (defaults.get("warranty_percent") or 0) * 100,
            "service_percent": (defaults.get("service_percent") or 0) * 100,
            "instalation": defaults.get("instalation") or 0,
            "traning": defaults.get("traning") or 0,
            "other": defaults.get("other") or 0,
        },
        today=price["date"],
        price=price,
        rounding_rules=rules_json
    )

@app.route("/products/<int:product_id>/prices/<int:price_id>/delete", methods=["POST"])
def delete_price(product_id, price_id):
    conn = get_db()
    cur = conn.cursor()

    # Make sure the price row exists and belongs to this product
    cur.execute(
        "SELECT id FROM prices WHERE id = ? AND product_id = ?;",
        (price_id, product_id),
    )
    row = cur.fetchone()
    if row is None:
        conn.close()
        return "Price entry not found", 404

    cur.execute("DELETE FROM prices WHERE id = ?;", (price_id,))
    conn.commit()
    conn.close()

    return redirect(url_for("price_history", product_id=product_id))

# ---------- END ----------
if __name__ == "__main__":
    init_db()
    migrate_schema()
    app.run(host="0.0.0.0", port=5000, debug=True)