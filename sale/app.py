import os
import sys
import sqlite3
import math
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session

# Ensure shared modules can be imported
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from shared.config import STATIC_DIR, DATABASE, IMAGE_DIR
from shared.utils import format_amount

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static",
    template_folder="templates"
)
app.secret_key = "sale_readonly_secret_change_me"
app.config['SESSION_COOKIE_NAME'] = 'sale_readonly_session'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def get_theme():
    """Fetch the theme setting from cookies."""
    from flask import request
    return request.cookies.get("theme", "dark")

@app.context_processor
def inject_helpers():
    return dict(
        format_amount=format_amount,
        theme=get_theme()
    )

@app.route("/product-image/<path:filename>")
def product_image(filename):
    return send_from_directory(IMAGE_DIR, filename)

@app.route("/")
def list_sale():
    # Check if we should clear filters
    if request.args.get("clear"):
        session.pop("sale_filter_brand", None)
        session.pop("sale_filter_category", None)
        session.pop("sale_filter_search", None)
        return redirect(url_for("list_sale"))

    # Load from request or fallback to session
    brand_filter = request.args.get("brand")
    if brand_filter is None:
        brand_filter = session.get("sale_filter_brand", "")
    else:
        session["sale_filter_brand"] = brand_filter

    category_filter = request.args.get("category")
    if category_filter is None:
        category_filter = session.get("sale_filter_category", "")
    else:
        session["sale_filter_category"] = category_filter

    search_term = request.args.get("search")
    if search_term is None:
        search_term = session.get("sale_filter_search", "")
    else:
        session["sale_filter_search"] = search_term

    sort_option = request.args.get("sort")
    if sort_option is None:
        sort_option = session.get("sale_sort_option", "name_asc") # Default sort
    else:
        session["sale_sort_option"] = sort_option

    page = request.args.get("page", 1, type=int)

    conn = get_db()
    cur = conn.cursor()

    # Fetch default items per page
    cur.execute("SELECT value FROM global_settings WHERE key = 'default_items_per_page';")
    row = cur.fetchone()
    items_per_page = int(row["value"]) if row else 25
    offset = (page - 1) * items_per_page

    # Base query: count total
    count_query = "SELECT COUNT(*) AS total_count FROM products p"

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
        where_clauses.append("p.name LIKE ?")
        params.append(f"%{search_term}%")

    if where_clauses:
        where_stmt = " WHERE " + " AND ".join(where_clauses)
        count_query += where_stmt
        query += where_stmt

    # Execute count before applying sort/limit
    cur.execute(count_query, params)
    total_count = cur.fetchone()["total_count"]

    total_pages = math.ceil(total_count / items_per_page) if total_count > 0 else 1

    # Sorting Logic
    if sort_option == "name_asc":
        query += " ORDER BY p.name ASC"
    elif sort_option == "name_desc":
        query += " ORDER BY p.name DESC"
    elif sort_option == "price_asc":
        query += " ORDER BY COALESCE(pr.final_price, 0) ASC"
    elif sort_option == "price_desc":
        query += " ORDER BY COALESCE(pr.final_price, 0) DESC"
    else:
        # Fallback
        query += " ORDER BY p.name ASC"

    query += f" LIMIT {items_per_page} OFFSET {offset};"

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
        "sale.html",
        products=products,
        brand_filter=brand_filter,
        category_filter=category_filter,
        brand_options=brand_options,
        category_options=category_options,
        search_term=search_term,
        sort_option=sort_option,
        current_page=page,
        total_pages=total_pages,
        total_count=total_count
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
