from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import os
import sys
import re
from PIL import Image
from datetime import date

# Base directory = the "Custom" folder (parent of this app folder)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# app_data folder inside Custom
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")

# pricing.db inside app_data
DATABASE = os.path.join(APP_DATA_DIR, "pricing.db")

# product image data
IMAGE_DIR = os.path.join(APP_DATA_DIR, "product_images")

# import common_utils
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
            default_extras REAL         -- extra costs per unit
        );
    """)

    # Brands table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brands (
            name TEXT PRIMARY KEY
        );
    """)

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

            base_total REAL,                -- base_price + extras
            cost_total REAL,                -- total cost
            calculated_price REAL,          -- theoretical price
            final_price REAL,               -- your nice rounded price
            profit_final REAL,              -- final_price - cost_total

            discount_percent REAL,          -- 0.10 for 10% discount
            discount_price REAL,            -- final_price after discount
            profit_discount REAL,           -- discount_price - cost_total

            FOREIGN KEY (product_id) REFERENCES products(id),
            UNIQUE (product_id, date)
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

def save_product_image(file_storage, product_name):
    """
    Save uploaded JPG to IMAGE_DIR, resized to max 800x800.
    Returns the filename (e.g. 'my_product.jpg') or raises ValueError on bad input.
    """
    if not file_storage or not file_storage.filename:
        return None

    # Check extension
    orig_filename = file_storage.filename
    ext = os.path.splitext(orig_filename)[1].lower()
    if ext not in [".jpg", ".jpeg"]:
        raise ValueError("Slika mora biti JPG (.jpg ili .jpeg).")

    # Build base name from product_name
    base = (product_name or "").strip().lower()
    # spaces -> _
    base = re.sub(r"\s+", "_", base)
    # remove anything that's not a-z, 0-9, _ or -
    base = re.sub(r"[^a-z0-9_-]", "", base)
    if not base:
        base = "product"

    filename = base + ".jpg"

    os.makedirs(IMAGE_DIR, exist_ok=True)
    dest_path = os.path.join(IMAGE_DIR, filename)

    # Open with Pillow
    try:
        img = Image.open(file_storage.stream)
        # Convert to RGB if needed
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        # Resize if bigger than 800x800
        max_size = (800, 800)
        img.thumbnail(max_size)  # keeps aspect ratio, modifies in place

        img.save(dest_path, format="JPEG", quality=85)
    except Exception as e:
        raise ValueError("Greška pri obradi slike: " + str(e))

    return filename


@app.route("/")
def index():
    return redirect(url_for("list_products"))

@app.context_processor
def inject_helpers():
    return dict(format_amount=format_amount)

# ---------- PRODUCTS ----------

@app.route("/products")
def list_products():
    brand_filter = request.args.get("brand")
    category_filter = request.args.get("category")
    search_term = request.args.get("search") or ""  # name search

    conn = get_db()
    cur = conn.cursor()

    # Base query: products + latest price
    query = """
        SELECT p.*,
               pr.final_price AS current_price,
               pr.discount_price AS current_discount_price
        FROM products p
        LEFT JOIN prices pr
          ON pr.product_id = p.id
         AND pr.date = (
             SELECT MAX(date) FROM prices WHERE product_id = p.id
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

        # 2) handle photo upload
        photo_file = request.files.get("photo_file")
        photo_path = None
        if photo_file and photo_file.filename:
            try:
                photo_path = save_product_image(photo_file, name)
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
        conn.commit()
        conn.close()
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

        # handle photo upload
        photo_file = request.files.get("photo_file")
        if photo_file and photo_file.filename:
            try:
                photo_path = save_product_image(photo_file, name)
            except ValueError as e:
                conn.close()
                return render_template(
                    "product_form.html",
                    categories=categories,
                    brand_options=brand_options,
                    product=product,
                    error=str(e)
                )
        else:
            # keep existing photo
            photo_path = product["photo_path"]

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

        # store as fractions (0.07 for 7%)
        import_percent = import_percent_input / 100.0
        margin_percent = margin_percent_input / 100.0

        if category:
            if old_category and old_category != category:
                # RENAME category: update defaults + products
                try:
                    # Update the category name + values in defaults
                    cur.execute("""
                        UPDATE category_pricing_defaults
                        SET category = ?, import_percent = ?, margin_percent = ?,
                            domestic_transport = ?, default_extras = ?
                        WHERE category = ?;
                    """, (
                        category,
                        import_percent, margin_percent,
                        domestic_transport, default_extras,
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
                        domestic_transport, default_extras
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(category) DO UPDATE SET
                        import_percent = excluded.import_percent,
                        margin_percent = excluded.margin_percent,
                        domestic_transport = excluded.domestic_transport,
                        default_extras = excluded.default_extras;
                """, (
                    category,
                    import_percent, margin_percent,
                    domestic_transport, default_extras
                ))
                conn.commit()

    cur.execute("SELECT * FROM category_pricing_defaults ORDER BY category;")
    defaults = cur.fetchall()
    conn.close()

    return render_template("category_defaults.html", defaults=defaults)

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

    return render_template("brands.html", brands=rows)

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
            }

    if request.method == "POST":
        date_str = request.form.get("date") or date.today().isoformat()
        base_price = float(request.form.get("base_price") or 0)
        extras = float(request.form.get("extras") or 0)

        # User inputs percent as e.g. 7 (for 7%), we convert to 0.07
        import_percent_input = float(request.form.get("import_percent") or 0)
        margin_percent_input = float(request.form.get("margin_percent") or 0)

        import_percent = import_percent_input / 100.0
        margin_percent = margin_percent_input / 100.0

        domestic_transport = float(request.form.get("domestic_transport") or 0)
        final_price = float(request.form.get("final_price") or 0)

        # Discount inputs:
        # - discount_percent: e.g. 10 for 10%
        # - discount_price: nice rounded discount price entered by user
        discount_percent_input = float(request.form.get("discount_percent") or 0)
        discount_price_input = float(request.form.get("discount_price") or 0)

        base_total = base_price + extras

        # Cost total uses import + domestic transport
        cost_total = base_total * (1 + import_percent) + domestic_transport

        # Calculated price matches your Excel:
        # = (base + extras) * (1 + margin) + domestic transport
        calculated_price = base_total * (1 + margin_percent) + domestic_transport

        if final_price <= 0:
            final_price = calculated_price  # fallback

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
            discount_price = final_price * (1 - discount_percent)

        if discount_price is not None:
            profit_discount = discount_price - cost_total

        cur.execute("""
            INSERT INTO prices (
                product_id, date,
                base_price, extras,
                import_percent, margin_percent,
                domestic_transport,
                base_total, cost_total,
                calculated_price, final_price,
                profit_final,
                discount_percent, discount_price, profit_discount
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id, date) DO UPDATE SET
                base_price = excluded.base_price,
                extras = excluded.extras,
                import_percent = excluded.import_percent,
                margin_percent = excluded.margin_percent,
                domestic_transport = excluded.domestic_transport,
                base_total = excluded.base_total,
                cost_total = excluded.cost_total,
                calculated_price = excluded.calculated_price,
                final_price = excluded.final_price,
                profit_final = excluded.profit_final,
                discount_percent = excluded.discount_percent,
                discount_price = excluded.discount_price,
                profit_discount = excluded.profit_discount;
        """, (
            product_id, date_str,
            base_price, extras,
            import_percent, margin_percent,
            domestic_transport,
            base_total, cost_total,
            calculated_price, final_price,
            profit_final,
            discount_percent, discount_price, profit_discount
        ))

        conn.commit()
        conn.close()
        return redirect(url_for("price_history", product_id=product_id))

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
        },
        today=date.today().isoformat(),
        price=None
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

        import_percent = import_percent_input / 100.0
        margin_percent = margin_percent_input / 100.0

        domestic_transport = float(request.form.get("domestic_transport") or 0)
        final_price = float(request.form.get("final_price") or 0)

        # Discount inputs
        discount_percent_input = float(request.form.get("discount_percent") or 0)
        discount_price_input = float(request.form.get("discount_price") or 0)

        base_total = base_price + extras

        # Cost total (import + domestic)
        cost_total = base_total * (1 + import_percent) + domestic_transport

        # Calculated price (Excel logic)
        calculated_price = base_total * (1 + margin_percent) + domestic_transport

        if final_price <= 0:
            final_price = calculated_price

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
            discount_price = final_price * (1 - discount_percent)

        if discount_price is not None:
            profit_discount = discount_price - cost_total

        cur.execute("""
            UPDATE prices
            SET date = ?,
                base_price = ?,
                extras = ?,
                import_percent = ?,
                margin_percent = ?,
                domestic_transport = ?,
                base_total = ?,
                cost_total = ?,
                calculated_price = ?,
                final_price = ?,
                profit_final = ?,
                discount_percent = ?,
                discount_price = ?,
                profit_discount = ?
            WHERE id = ?;
        """, (
            date_str,
            base_price, extras,
            import_percent, margin_percent,
            domestic_transport,
            base_total, cost_total,
            calculated_price, final_price,
            profit_final,
            discount_percent if discount_percent_input > 0 else None,
            discount_price,
            profit_discount,
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
            }

    conn.close()
    return render_template(
        "price_form.html",
        product=product,
        defaults={
            "import_percent": defaults["import_percent"] * 100,
            "margin_percent": defaults["margin_percent"] * 100,
            "domestic_transport": defaults["domestic_transport"],
            "extras": defaults["default_extras"],
        },
        today=price["date"],
        price=price
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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
