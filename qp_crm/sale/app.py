import os
import math
import sqlite3
import html
from flask import Blueprint, Flask, render_template, request, redirect, url_for, send_from_directory, session, abort
import markdown

from qp_crm.shared.config import STATIC_DIR, IMAGE_DIR
from qp_crm.shared.db import get_db
from qp_crm.shared.utils import format_amount
from qp_crm.shared.web import get_theme, register_product_image

# ---------------------------------------------------------------------------
# Phase 2 stage 1: sale is a Blueprint on the single QP-CRM app.
#
# The Flask(...) instance, secret key and SESSION_COOKIE_NAME moved to
# main.py (one session/secret/cookie for the whole stack; SALE_SECRET_KEY
# and the sale_readonly_session cookie are no longer used). Routes keep the
# same URLs via the blueprint's /sale prefix in main.py; endpoints are
# namespaced (sale.list_sale, ...) in Python and templates. Templates live
# under sale/templates/sale/ because the unified Jinja environment resolves
# same-name templates by blueprint registration order (every module ships a
# base.html).
# ---------------------------------------------------------------------------

bp = Blueprint("sale", __name__, template_folder="templates")

@bp.context_processor
def inject_helpers():
    return dict(
        format_amount=format_amount,
        theme=get_theme()
    )

# /product-image route: shared implementation (also on pricing and offer)
register_product_image(bp)

@bp.route("/")
def index():
    return redirect(url_for("sale.list_sale"))

@bp.route("/pricelist")
def list_sale():
    # Check if we should clear filters
    if request.args.get("clear"):
        session.pop("sale_filter_brand", None)
        session.pop("sale_filter_category", None)
        session.pop("sale_filter_search", None)
        return redirect(url_for("sale.list_sale"))

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

    # BUG fix (phase-2 bug-fix stage, card "BUG - sale module:
    # list_sale 500s on uninitialized schema"): a bare/recreated schema
    # (restore_db edge cases, future split deployments, fresh test DBs)
    # used to 500 with sqlite3.OperationalError; render a clean empty
    # state instead. Sane defaults: 25 items/page, empty filters.
    try:
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


    except sqlite3.OperationalError:
        products = []
        total_count = 0
        total_pages = 1
        brand_options = []
        category_options = []
    finally:
        conn.close()

    return render_template(
        "sale/sale.html",
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

@bp.route("/product/<int:product_id>")
def view_product(product_id):
    conn = get_db()
    cur = conn.cursor()

    query = """
        SELECT p.*,
               pr.final_price AS current_price,
               pr.discount_price AS current_discount_price
        FROM products p
        LEFT JOIN prices pr
          ON pr.id = (
              SELECT MAX(id) FROM prices WHERE product_id = p.id
          )
        WHERE p.id = ?
    """
    try:
        cur.execute(query, (product_id,))
        product = cur.fetchone()
    except sqlite3.OperationalError:
        # BUG fix (same card): bare schema degrades to not-found, not 500.
        product = None
    finally:
        conn.close()

    if not product:
        abort(404)

    # Convert markdown description to HTML safely
    description_html = ""
    if product["description"]:
        # Escape raw HTML/JS in the source before Markdown conversion to prevent XSS
        description_html = markdown.markdown(html.escape(product["description"]))

    return render_template(
        "sale/view_product.html",
        product=product,
        description_html=description_html
    )

if __name__ == "__main__":
    # Standalone dev run (python -m qp_crm.sale.app) -- previously this module's own
    # Flask instance; now the blueprint mounted on a throwaway app with the
    # same URL prefix and port.
    standalone = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    standalone.register_blueprint(bp, url_prefix="/sale")
    standalone.secret_key = os.environ.get("SALE_SECRET_KEY", "sale_readonly_secret_change_me")
    standalone.config['SESSION_COOKIE_NAME'] = 'sale_readonly_session'
    standalone.run(host="0.0.0.0", port=5001, debug=True)
