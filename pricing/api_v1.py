"""
AI-Friendly REST API v1 for QP-CRM
Provides endpoints for Products, Categories, and Brands management.
Authentication: Bearer token (API key).
"""

import os
import sys
import re
import io
import html as _html
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from flask import Blueprint, request, jsonify, url_for

# Ensure parent dir in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from shared.db import get_db
from shared.auth import validate_api_key
from shared.config import IMAGE_DIR

from PIL import Image
import requests as http_requests


# ---------- Photo/image helpers (replicated from pricing/app.py to avoid circular imports) ----------

def save_product_image(image_stream, orig_filename, product_name):
    """
    Process and save an image (from stream) to IMAGE_DIR, resized to max 800x800.
    Returns the filename (e.g. 'my_product.jpg') or raises ValueError.
    """
    if not image_stream or not orig_filename:
        return None

    ext = os.path.splitext(orig_filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise ValueError("Image must be JPG, PNG or WEBP (.jpg, .jpeg, .png, or .webp).")

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
        if 'A' in img.mode:
            img = img.convert("RGBA")
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        max_size = (800, 800)
        img.thumbnail(max_size)
        img.save(dest_path, format="JPEG", quality=85)
    except Exception as e:
        raise ValueError("Error processing image: " + str(e))

    return filename


def download_image_from_url(url):
    """
    Download image from URL, validate it's an image.
    Returns (BytesIO stream, filename) or raises ValueError.
    """
    try:
        resp = http_requests.get(url, timeout=10, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get('Content-Type', '').lower()
        if 'image/jpeg' not in content_type and 'image/png' not in content_type and 'image/webp' not in content_type:
            raise ValueError("URL does not point to a JPG, PNG or WEBP image.")

        orig_filename = url.split("/")[-1].split("?")[0] or "url_image.jpg"
        if not any(orig_filename.lower().endswith(ex) for ex in ['.jpg', '.jpeg', '.png', '.webp']):
            if 'png' in content_type:
                orig_filename += '.png'
            elif 'webp' in content_type:
                orig_filename += '.webp'
            else:
                orig_filename += '.jpg'

        return io.BytesIO(resp.content), orig_filename

    except http_requests.exceptions.RequestException as e:
        raise ValueError(f"Error downloading image from URL: {str(e)}")


api_v1 = Blueprint("api_v1", __name__)

# ---------- Auth Decorator ----------

def require_api_key(f):
    """Decorator that checks for a valid Bearer token in the Authorization header."""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"success": False, "error": "Missing or invalid Authorization header. Use: Bearer <api_key>"}), 401
        token = auth_header[7:]  # Strip "Bearer "
        if not validate_api_key(token):
            return jsonify({"success": False, "error": "Invalid API key."}), 403
        return f(*args, **kwargs)
    return decorated


# ---------- Health ----------

@api_v1.route("/health")
def health():
    return jsonify({"success": True, "message": "API v1 is running", "version": "1.0.0"})


# ---------- PRODUCTS ----------

@api_v1.route("/products")
@require_api_key
def list_products():
    """List/search products with optional filters."""
    search = request.args.get("search", "").strip()
    brand = request.args.get("brand", "").strip()
    category = request.args.get("category", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 25, type=int)
    if per_page < 1:
        per_page = 25
    if per_page > 500:
        per_page = 500
    if page < 1:
        page = 1
    offset = (page - 1) * per_page

    conn = get_db()
    cur = conn.cursor()

    # Count query
    count_query = "SELECT COUNT(*) AS total FROM products p"
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

    if brand:
        where_clauses.append("p.brand = ?")
        params.append(brand)
    if category:
        where_clauses.append("p.category = ?")
        params.append(category)
    if search:
        where_clauses.append("p.name LIKE ?")
        params.append(f"%{search}%")

    if where_clauses:
        where_stmt = " WHERE " + " AND ".join(where_clauses)
        count_query += where_stmt
        query += where_stmt

    cur.execute(count_query, params)
    total = cur.fetchone()["total"]

    query += " ORDER BY p.name ASC"
    query += f" LIMIT {per_page} OFFSET {offset}"

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()

    products = []
    for p in rows:
        photo_url = None
        if p["photo_path"]:
            # We return a relative path; base URL can be constructed by the client
            photo_url = f"/api/v1/products/{p['id']}/photo"
        products.append({
            "id": p["id"],
            "name": p["name"],
            "description": p["description"],
            "category": p["category"],
            "brand": p["brand"],
            "photo_path": p["photo_path"],
            "photo_url": photo_url,
            "current_price": p["current_price"],
            "current_discount_price": p["current_discount_price"],
        })

    total_pages = -(-total // per_page)  # ceil division

    return jsonify({
        "success": True,
        "data": products,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        }
    })


@api_v1.route("/products/<int:product_id>")
@require_api_key
def get_product(product_id):
    """Get a single product by ID with full details."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.*,
               pr.final_price AS current_price,
               pr.discount_price AS current_discount_price
        FROM products p
        LEFT JOIN prices pr
          ON pr.id = (
              SELECT MAX(id) FROM prices WHERE product_id = p.id
          )
        WHERE p.id = ?;
    """, (product_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "error": f"Product with id {product_id} not found."}), 404

    photo_url = None
    if row["photo_path"]:
        photo_url = f"/api/v1/products/{row['id']}/photo"

    return jsonify({
        "success": True,
        "data": {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "category": row["category"],
            "brand": row["brand"],
            "photo_path": row["photo_path"],
            "photo_url": photo_url,
            "current_price": row["current_price"],
            "current_discount_price": row["current_discount_price"],
        }
    })


@api_v1.route("/products/<int:product_id>/photo")
@require_api_key
def get_product_photo(product_id):
    """Serve the product photo directly."""
    from flask import send_from_directory
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT photo_path FROM products WHERE id = ?;", (product_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row["photo_path"]:
        return jsonify({"success": False, "error": "No photo found for this product."}), 404
    return send_from_directory(IMAGE_DIR, row["photo_path"])


@api_v1.route("/products", methods=["POST"])
@require_api_key
def create_product():
    """Create a new product. Accepts multipart/form-data or JSON."""
    conn = get_db()
    cur = conn.cursor()

    # Handle both multipart and JSON
    if request.is_json:
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        description = data.get("description") or ""
        category = data.get("category") or ""
        brand = data.get("brand") or ""
        photo_url_field = (data.get("photo_url") or "").strip()
        photo_file = None
    else:
        name = (request.form.get("name") or "").strip()
        description = request.form.get("description") or ""
        category = request.form.get("category") or ""
        brand = request.form.get("brand") or ""
        photo_url_field = (request.form.get("photo_url") or "").strip()
        photo_file = request.files.get("photo")

    if not name:
        conn.close()
        return jsonify({"success": False, "error": "Product name is required."}), 400

    # Check duplicate name
    cur.execute("SELECT id FROM products WHERE name = ? COLLATE NOCASE;", (name,))
    if cur.fetchone():
        conn.close()
        return jsonify({"success": False, "error": f"A product with name '{name}' already exists."}), 409

    # Handle photo
    photo_path = None
    try:
        if photo_file and photo_file.filename:
            photo_path = save_product_image(photo_file.stream, photo_file.filename, name)
        elif photo_url_field:
            stream, orig_filename = download_image_from_url(photo_url_field)
            photo_path = save_product_image(stream, orig_filename, name)
    except ValueError as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

    cur.execute("""
        INSERT INTO products (name, description, category, brand, photo_path)
        VALUES (?, ?, ?, ?, ?);
    """, (name, description, category, brand, photo_path))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()

    photo_url = f"/api/v1/products/{new_id}/photo" if photo_path else None
    return jsonify({
        "success": True,
        "data": {
            "id": new_id,
            "name": name,
            "description": description,
            "category": category,
            "brand": brand,
            "photo_path": photo_path,
            "photo_url": photo_url,
        }
    }), 201


@api_v1.route("/products/<int:product_id>", methods=["PUT"])
@require_api_key
def update_product(product_id):
    """Update an existing product. Accepts multipart/form-data or JSON."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    product = cur.fetchone()
    if not product:
        conn.close()
        return jsonify({"success": False, "error": f"Product with id {product_id} not found."}), 404

    if request.is_json:
        data = request.get_json() or {}
        name = (data.get("name") or "").strip()
        description = data.get("description")
        category = data.get("category")
        brand = data.get("brand")
        photo_url_field = (data.get("photo_url") or "").strip()
        photo_file = None
    else:
        name = (request.form.get("name") or "").strip()
        description = request.form.get("description")
        category = request.form.get("category")
        brand = request.form.get("brand")
        photo_url_field = (request.form.get("photo_url") or "").strip()
        photo_file = request.files.get("photo")

    # Only validate name if provided
    if name and name != product["name"]:
        cur.execute("SELECT id FROM products WHERE name = ? COLLATE NOCASE AND id != ?;", (name, product_id))
        if cur.fetchone():
            conn.close()
            return jsonify({"success": False, "error": f"Another product with name '{name}' already exists."}), 409

    # Use existing values for fields not provided
    final_name = name if name else product["name"]
    final_description = description if description is not None else product["description"]
    final_category = category if category is not None else product["category"]
    final_brand = brand if brand is not None else product["brand"]

    # Handle photo
    photo_path = product["photo_path"]
    try:
        if photo_file and photo_file.filename:
            photo_path = save_product_image(photo_file.stream, photo_file.filename, final_name)
            # Delete old photo if different
            if product["photo_path"] and photo_path != product["photo_path"]:
                old_path = os.path.join(IMAGE_DIR, product["photo_path"])
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
        elif photo_url_field:
            stream, orig_filename = download_image_from_url(photo_url_field)
            photo_path = save_product_image(stream, orig_filename, final_name)
            if product["photo_path"] and photo_path != product["photo_path"]:
                old_path = os.path.join(IMAGE_DIR, product["photo_path"])
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
        elif final_name != product["name"] and photo_path:
            # Rename photo to match new product name
            ext = os.path.splitext(photo_path)[1].lower() or ".jpg"
            base = re.sub(r"\s+", "_", final_name.strip().lower())
            base = re.sub(r"[^a-z0-9_-]", "", base) or "product"
            new_filename = base + ext
            if new_filename != photo_path:
                old_full = os.path.join(IMAGE_DIR, photo_path)
                new_full = os.path.join(IMAGE_DIR, new_filename)
                if os.path.exists(old_full):
                    try:
                        os.rename(old_full, new_full)
                        photo_path = new_filename
                    except Exception:
                        pass
    except ValueError as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

    cur.execute("""
        UPDATE products
        SET name = ?, description = ?, category = ?, brand = ?, photo_path = ?
        WHERE id = ?;
    """, (final_name, final_description, final_category, final_brand, photo_path, product_id))
    conn.commit()
    conn.close()

    photo_url = f"/api/v1/products/{product_id}/photo" if photo_path else None
    return jsonify({
        "success": True,
        "data": {
            "id": product_id,
            "name": final_name,
            "description": final_description,
            "category": final_category,
            "brand": final_brand,
            "photo_path": photo_path,
            "photo_url": photo_url,
        }
    })


@api_v1.route("/products/<int:product_id>", methods=["DELETE"])
@require_api_key
def delete_product(product_id):
    """Delete a product and its associated photo."""
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM products WHERE id = ?;", (product_id,))
    product = cur.fetchone()
    if not product:
        conn.close()
        return jsonify({"success": False, "error": f"Product with id {product_id} not found."}), 404

    # Detach from offers
    try:
        cur.execute("UPDATE offer_items SET product_id = NULL WHERE product_id = ?;", (product_id,))
    except Exception:
        pass

    # Delete prices
    cur.execute("DELETE FROM prices WHERE product_id = ?;", (product_id,))
    # Delete product
    cur.execute("DELETE FROM products WHERE id = ?;", (product_id,))
    conn.commit()
    conn.close()

    # Delete photo file
    if product["photo_path"]:
        file_path = os.path.join(IMAGE_DIR, product["photo_path"])
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

    return jsonify({"success": True, "message": f"Product #{product_id} deleted."})


# ---------- CATEGORIES ----------

@api_v1.route("/categories")
@require_api_key
def list_categories():
    """List all categories with their default pricing parameters."""
    search = request.args.get("search", "").strip()
    conn = get_db()
    cur = conn.cursor()

    if search:
        cur.execute("""
            SELECT * FROM category_pricing_defaults
            WHERE category LIKE ?
            ORDER BY category;
        """, (f"%{search}%",))
    else:
        cur.execute("SELECT * FROM category_pricing_defaults ORDER BY category;")
    rows = cur.fetchall()
    conn.close()

    categories = []
    for r in rows:
        categories.append({
            "category": r["category"],
            "import_percent": r["import_percent"],
            "margin_percent": r["margin_percent"],
            "domestic_transport": r["domestic_transport"],
            "default_extras": r["default_extras"],
            "warranty_percent": r["warranty_percent"] or 0,
            "service_percent": r["service_percent"] or 0,
            "instalation": r["instalation"] or 0,
            "traning": r["traning"] or 0,
            "other": r["other"] or 0,
        })

    return jsonify({"success": True, "data": categories})


@api_v1.route("/categories", methods=["POST"])
@require_api_key
def create_or_update_category():
    """Create or update a category with pricing defaults. Accepts JSON."""
    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip()
    if not category:
        return jsonify({"success": False, "error": "Category name is required."}), 400

    import_percent = float(data.get("import_percent", 0))
    margin_percent = float(data.get("margin_percent", 0))
    domestic_transport = float(data.get("domestic_transport", 0))
    default_extras = float(data.get("default_extras", 0))
    warranty_percent = float(data.get("warranty_percent", 0))
    service_percent = float(data.get("service_percent", 0))
    instalation = float(data.get("instalation", 0))
    traning = float(data.get("traning", 0))
    other = float(data.get("other", 0))

    # Values are stored as fractions (0.07 = 7%). If user passes 7, convert.
    # We detect: if > 1.0, assume they passed percent and divide by 100.
    pct_fields = {
        "import_percent": import_percent,
        "margin_percent": margin_percent,
        "warranty_percent": warranty_percent,
        "service_percent": service_percent,
    }
    for key in pct_fields:
        if pct_fields[key] > 1.0:
            pct_fields[key] = pct_fields[key] / 100.0

    conn = get_db()
    cur = conn.cursor()
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
        pct_fields["import_percent"], pct_fields["margin_percent"],
        domestic_transport, default_extras,
        pct_fields["warranty_percent"], pct_fields["service_percent"],
        instalation, traning, other
    ))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "data": {
            "category": category,
            "import_percent": pct_fields["import_percent"],
            "margin_percent": pct_fields["margin_percent"],
            "domestic_transport": domestic_transport,
            "default_extras": default_extras,
            "warranty_percent": pct_fields["warranty_percent"],
            "service_percent": pct_fields["service_percent"],
            "instalation": instalation,
            "traning": traning,
            "other": other,
        }
    })


@api_v1.route("/categories/<path:category_name>", methods=["DELETE"])
@require_api_key
def delete_category(category_name):
    """Delete a category. Fails if any products use it."""
    conn = get_db()
    cur = conn.cursor()

    # URL-decode the category name
    from urllib.parse import unquote
    cat_name = unquote(category_name)

    cur.execute("SELECT id FROM products WHERE category = ? LIMIT 1;", (cat_name,))
    if cur.fetchone():
        conn.close()
        return jsonify({
            "success": False,
            "error": f"Cannot delete category '{cat_name}' because it is used by one or more products."
        }), 409

    cur.execute("DELETE FROM category_pricing_defaults WHERE category = ?;", (cat_name,))
    if cur.rowcount == 0:
        conn.close()
        return jsonify({"success": False, "error": f"Category '{cat_name}' not found."}), 404

    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Category '{cat_name}' deleted."})


# ---------- BRANDS ----------

@api_v1.route("/brands")
@require_api_key
def list_brands():
    """List all brands."""
    search = request.args.get("search", "").strip()
    conn = get_db()
    cur = conn.cursor()

    if search:
        cur.execute("SELECT name FROM brands WHERE name LIKE ? ORDER BY name;", (f"%{search}%",))
    else:
        cur.execute("SELECT name FROM brands ORDER BY name;")
    rows = cur.fetchall()
    conn.close()

    brands = [r["name"] for r in rows]
    return jsonify({"success": True, "data": brands})


@api_v1.route("/brands", methods=["POST"])
@require_api_key
def create_brand():
    """Create a new brand. Accepts JSON."""
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Brand name is required."}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO brands (name) VALUES (?);", (name,))
    conn.commit()
    conn.close()

    return jsonify({"success": True, "data": {"name": name}}), 201


@api_v1.route("/brands/<path:brand_name>", methods=["DELETE"])
@require_api_key
def delete_brand(brand_name):
    """Delete a brand. Fails if any products use it."""
    from urllib.parse import unquote
    name = unquote(brand_name)

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM products WHERE brand = ? LIMIT 1;", (name,))
    if cur.fetchone():
        conn.close()
        return jsonify({
            "success": False,
            "error": f"Cannot delete brand '{name}' because it is used by one or more products."
        }), 409

    cur.execute("DELETE FROM brands WHERE name = ?;", (name,))
    if cur.rowcount == 0:
        conn.close()
        return jsonify({"success": False, "error": f"Brand '{name}' not found."}), 404

    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": f"Brand '{name}' deleted."})


# ---------- SITE SYNC (Sajt <-> CRM product sync, manual only) ----------

import datetime as _dt
from shared.config import (
    SITE_API_BASE, SITE_PER_PAGE, SITE_TIMEOUT, SITE_RETRIES, SITE_MAX_DESC_LEN
)

def _clean_html(raw):
    """Strip all HTML tags, decode common entities, collapse whitespace."""
    if not raw:
        return ""
    # Remove tags
    text = re.sub(r"<[^>]+>", "", raw)
    # Decode common HTML entities (e.g. &, ", &#39;, &nbsp;)
    text = _html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text

# Common emoji ranges (kept compact but broad enough to cover pictographs,
# emoticons, flags, transport, supplemental symbols, and variation selectors)
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # Emoticons
    "\U0001F300-\U0001F5FF"   # Misc Symbols and Pictographs
    "\U0001F680-\U0001F6FF"   # Transport and Map
    "\U0001F1E0-\U0001F1FF"   # Regional Indicator Symbols (flags)
    "\U00002700-\U000027BF"   # Dingbats
    "\U0001F900-\U0001F9FF"   # Supplemental Symbols and Pictographs
    "\U00002600-\U000026FF"   # Miscellaneous Symbols
    "\U00002B00-\U00002BFF"   # Miscellaneous Symbols and Arrows
    "\U0001FA00-\U0001FAFF"   # Extended Pictographs
    "\U0000FE00-\U0000FE0F"   # Variation Selectors
    "\U0001F000-\U0001F0FF"   # Geometric Shapes
    "\U0001F170-\U0001F17F"
    "\U0001F180-\U0001F189"
    "\U0001F190-\U0001F19A"
    "\U0001F1A0-\U0001F1A9"
    "\U0001F1B0-\U0001F1B9"
    "\U0001F1C0-\U0001F1CF"
    "\U0001F1D0-\U0001F1DF"
    "\U0001F1E0-\U0001F1EF"
    "\U0001F1F0-\U0001F1FF"
    "\U0001F200-\U0001F2FF"
    "\U0001F700-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U000020D0-\U000020D7"
    "\U0000FE20-\U0000FE2F"
    "\U0000FE0F"
    "]+"
)

# Words that mark noisy lines we want to drop (prices, manufacturer blurb, etc.)
_NOISE_TERMS = [
    "o proizvođaču", "o proizvodjaču", "o proizvodacu", "o proizvodjacu",
    "o proizvodacu", "o brendu", "o marki", "o nama", "o proizvodu",
    "cena:", "cena ", "price:", "rsd", "din", "€", "$", "novo",
    "akcija", "sale", "popust", "preuzmi", "download",
]

def _strip_noise(text):
    """
    Remove emoji, URLs, and drop whole lines that carry prices/manufacturer
    blurbs/'o proizvođaču' boilerplate. Returns cleaned single-line text.
    """
    if not text:
        return ""
    # Remove emoji
    text = _EMOJI_RE.sub("", text)
    # Remove URLs (http/https/www)
    text = re.sub(r"https?://[^\s]+", "", text)
    text = re.sub(r"www\.[^\s]+", "", text)
    # Split into lines, drop noisy lines, then rejoin with single spaces
    lines = text.split("\n")
    kept = []
    for line in lines:
        low = line.lower()
        if any(term in low for term in _NOISE_TERMS):
            continue
        kept.append(line.strip())
    return " ".join(k for k in kept if k)

def _parse_specs(content_raw):
    """
    Parse spec lines of form 'label: value' from content HTML.
    Returns list of [label, value] pairs if 3+ found, else None.
    """
    text = _clean_html(content_raw)
    if not text:
        return None
    pairs = []
    for line in text.split("\n"):
        # A line can contain multiple 'label: value' segments
        for match in re.finditer(r"([A-Za-z][^:]{2,40}?):\s*(.{1,80})", line):
            label = match.group(1).strip()
            value = match.group(2).strip()
            # Avoid treating URLs/HTML leftovers as specs
            if label and value and not label.lower().startswith("http"):
                pairs.append((label, value))
    # Only keep unique labels (first occurrence wins), cap at 30 rows
    seen = {}
    uniq = []
    for label, value in pairs:
        key = label.lower()
        if key not in seen:
            seen[key] = True
            uniq.append((label, value))
        if len(uniq) >= 30:
            break
    if len(uniq) < 3:
        return None
    return uniq

def build_product_description(site_product):
    """
    Deterministic server-side description from site product data (no AI).
    Format:
      NAME
      <blank>
      Paragraph (2-4 sentences) from excerpt, HTML cleaned.
      <blank>
      **KARAKTERISTIKE:**            (only if 3+ 'label: value' pairs found)
      | Parametar | Specifikacija |
      | ... |
    Returns text <= SITE_MAX_DESC_LEN chars.
    """
    name = _clean_html(site_product.get("name") or "")
    excerpt = _clean_html(site_product.get("excerpt") or "")
    content = _clean_html(site_product.get("content") or "")

    lines = []
    lines.append(name or "Proizvod")
    lines.append("")

    # Paragraph: take up to 2-4 sentences from excerpt, cleaned of emoji/URLs/noise
    if excerpt:
        excerpt_clean = _strip_noise(excerpt)
        sentences = re.findall(r"[^.!?]+[.!?]", excerpt_clean)
        para = " ".join(sentences[:4]) if sentences else excerpt_clean
        para = para.strip()
        if para:
            lines.append(para)
            lines.append("")

    # Obim isporuke (ACF 'included_items' — what's in the box), deterministic
    included = _strip_noise(site_product.get("included_items") or "")
    if included:
        lines.append("**OBIM ISPORUKE:**")
        lines.append(included)
        lines.append("")

    # Specifications table (if 3+ pairs found in content)
    specs = _parse_specs(content)
    if specs:
        lines.append("**KARAKTERISTIKE:**")
        lines.append("| Parametar | Specifikacija |")
        lines.append("|---|---|")
        for label, value in specs:
            value_clean = _strip_noise(value)
            if value_clean:
                lines.append(f"| {label} | {value_clean} |")

    result = "\n".join(lines).strip()
    if len(result) > SITE_MAX_DESC_LEN:
        result = result[:SITE_MAX_DESC_LEN].rstrip() + "\n..."
    return result


def _fetch_all_site_products():
    """
    Fetch ALL publish products from the site (paginated).
    Returns list of dicts with normalized fields.
    Raises on network/API error (caller decides to keep old snapshot).
    """
    products = []
    page = 1
    while True:
        resp = None
        for attempt in range(SITE_RETRIES + 1):
            try:
                resp = http_requests.get(
                    f"{SITE_API_BASE}/product",
                    params={"per_page": SITE_PER_PAGE, "page": page,
                            "orderby": "id", "order": "asc", "status": "publish"},
                    timeout=SITE_TIMEOUT,
                )
                resp.raise_for_status()
                break
            except http_requests.exceptions.RequestException as e:
                if attempt == SITE_RETRIES:
                    raise
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("Unexpected API response format.")
        for item in data:
            if item.get("status") != "publish":
                continue
            title = _clean_html(item.get("title", {}).get("rendered") or "")
            if not title:
                continue
            # Brand / category: take first ID from arrays
            brand_ids = item.get("product_brand") or []
            cat_ids = item.get("product_cat") or []
            products.append({
                "id": item.get("id"),
                "name": title,
                "url": item.get("link"),
                "brand_id": brand_ids[0] if brand_ids else None,
                "cat_id": cat_ids[0] if cat_ids else None,
                "featured_media": item.get("featured_media"),
                "modified": item.get("modified"),
                "excerpt": item.get("excerpt", {}).get("rendered") or "",
                "content": item.get("content", {}).get("rendered") or "",
                "included_items": (item.get("acf") or {}).get("included_items") or "",
            })
        total_pages = int(resp.headers.get("X-WP-TotalPages", "1") or 1)
        if page >= total_pages:
            break
        page += 1
    return products


def _fetch_brand_and_cat_names():
    """Fetch brand names and category names from the site for denormalization."""
    names = {"brands": {}, "cats": {}}
    try:
        resp = http_requests.get(
            f"{SITE_API_BASE}/product_brand", params={"per_page": 100},
            timeout=SITE_TIMEOUT,
        )
        resp.raise_for_status()
        for b in resp.json() or []:
            names["brands"][b.get("id")] = _clean_html(b.get("name") or "")
    except Exception:
        pass
    try:
        resp = http_requests.get(
            f"{SITE_API_BASE}/product_cat", params={"per_page": 100},
            timeout=SITE_TIMEOUT,
        )
        resp.raise_for_status()
        for c in resp.json() or []:
            names["cats"][c.get("id")] = _clean_html(c.get("name") or "")
    except Exception:
        pass
    return names


def _fetch_media_url(media_id):
    """Fetch source_url for a media id."""
    if not media_id:
        return None
    try:
        resp = http_requests.get(f"{SITE_API_BASE}/media/{media_id}", timeout=SITE_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        return data.get("source_url")
    except Exception:
        return None


@api_v1.route("/sync/fetch", methods=["POST"])
@require_api_key
def sync_fetch():
    """
    Manually pull a fresh snapshot of the site products (paginated, publish only).
    Replace-all in site_products inside a transaction.
    Returns {fetched, new, changed, removed_from_site}.
    """
    conn = get_db()
    cur = conn.cursor()

    # Build brand/cat name maps first
    names = _fetch_brand_and_cat_names()
    products = _fetch_all_site_products()

    # NOTE: Bulk image fetching is intentionally skipped.
    # The comparison table shows only text columns (name/brand/category), not images.
    # Images are fetched fresh per-product in /sync/product_info for the "Add to CRM" dialog.
    # Bulk media calls (455 requests) are very slow/throttled and would make fetch unusable.
    for p in products:
        p["image_url"] = None

    fetched_at = _dt.datetime.now().isoformat()

    # Snapshot existing site IDs to compute new/changed/removed
    cur.execute("SELECT id FROM site_products;")
    existing_ids = {row["id"] for row in cur.fetchall()}

    # Build new rows
    new_rows = []
    for p in products:
        new_rows.append((
            p["id"], p["name"], p.get("url"),
            p.get("brand_id"), names["brands"].get(p.get("brand_id")),
            p.get("cat_id"), names["cats"].get(p.get("cat_id")),
            p.get("image_url"), p.get("modified"), fetched_at,
            p.get("included_items"),
        ))

    # Count new/changed by comparing to existing snapshot
    new_count = 0
    changed_count = 0
    if existing_ids:
        for p in products:
            cur.execute(
                "SELECT name, url, brand_name, cat_name, image_url, modified, included_items FROM site_products WHERE id = ?;",
                (p["id"],),
            )
            row = cur.fetchone()
            if row is None:
                new_count += 1
            else:
                new_name = names["brands"].get(p.get("brand_id"))
                new_cat = names["cats"].get(p.get("cat_id"))
                if (row["name"] != p["name"] or row["url"] != p.get("url") or
                    row["brand_name"] != new_name or row["cat_name"] != new_cat or
                    row["image_url"] != p.get("image_url") or row["modified"] != p.get("modified") or
                    row["included_items"] != p.get("included_items")):
                    changed_count += 1

    # Replace-all in a transaction (only commit when fully built)
    cur.execute("DELETE FROM site_products;")
    cur.executemany(
        """INSERT INTO site_products
        (id, name, url, brand_id, brand_name, cat_id, cat_name, image_url, modified, fetched_at, included_items)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);""",
        new_rows,
    )
    new_ids = {p["id"] for p in products}
    removed_count = len(existing_ids - new_ids)
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "data": {
            "fetched": len(new_rows),
            "new": new_count,
            "changed": changed_count,
            "removed_from_site": removed_count,
            "fetched_at": fetched_at,
        }
    })


@api_v1.route("/sync/table")
@require_api_key
def sync_table():
    """
    Combined comparison view.
    filter: all | unlinked | crm_missing | site_missing
    q: search by name (both sides)
    Returns {pairs: [...], crm_only: [...], site_only: [...]}.
    pairs = linked pairs + suggested pairs (exact case-insensitive trim name match).
    """
    filter_val = request.args.get("filter", "all")
    q = (request.args.get("q") or "").strip()

    conn = get_db()
    cur = conn.cursor()

    # Search clause applies to both CRM and site names
    like = None
    if q:
        like = f"%{q}%"
        cur.execute(
            "SELECT id, name, brand, category FROM products WHERE name LIKE ? ORDER BY name;",
            (like,),
        )
    else:
        cur.execute("SELECT id, name, brand, category FROM products ORDER BY name;")
    crm_rows = cur.fetchall()

    if q:
        cur.execute(
            "SELECT id, name, url, brand_name, cat_name, image_url, included_items FROM site_products WHERE name LIKE ? ORDER BY name;",
            (like,),
        )
    else:
        cur.execute("SELECT id, name, url, brand_name, cat_name, image_url, included_items FROM site_products ORDER BY name;")
    site_rows = cur.fetchall()

    # Build maps
    crm_by_id = {r["id"]: r for r in crm_rows}
    site_by_id = {r["id"]: r for r in site_rows}

    # CRM -> site link map (site_product_id)
    cur.execute("SELECT id, site_product_id FROM products WHERE site_product_id IS NOT NULL;")
    link_rows = cur.fetchall()
    crm_to_site = {}
    for r in link_rows:
        crm_to_site[r["id"]] = r["site_product_id"]

    # Reverse: site -> crm (1:1)
    site_to_crm = {}
    for crm_id, site_id in crm_to_site.items():
        site_to_crm[site_id] = crm_id

    # Exact name match (case-insensitive, trimmed) -> suggested pairs
    def norm(s):
        return (s or "").strip().lower()

    site_by_norm = {}
    for s in site_rows:
        site_by_norm.setdefault(norm(s["name"]), s)

    crm_by_norm = {}
    for c in crm_rows:
        crm_by_norm.setdefault(norm(c["name"]), c)

    pairs = []
    crm_only = []
    site_only = []

    used_crm = set()
    used_site = set()

    # 1. Linked pairs
    for crm_id, site_id in crm_to_site.items():
        crm = crm_by_id.get(crm_id)
        site = site_by_id.get(site_id)
        if crm is None:
            # CRM product deleted - show as site-only with note (link preserved in table via note)
            if site is not None:
                site_only.append({
                    "type": "site_only",
                    "site_id": site["id"], "site_name": site["name"],
                    "site_brand": site["brand_name"], "site_cat": site["cat_name"],
                    "site_url": site["url"], "site_image": site["image_url"],
                    "included_items": site["included_items"] or "",
                    "crm_linked_missing": True,
                })
            used_site.add(site_id)
            continue
        used_crm.add(crm_id)
        if site is not None:
            used_site.add(site_id)
            pairs.append({
                "type": "linked",
                "product_id": crm["id"], "name": crm["name"],
                "brand": crm["brand"], "category": crm["category"],
                "site_id": site["id"], "site_name": site["name"],
                "site_brand": site["brand_name"], "site_cat": site["cat_name"],
                "site_url": site["url"], "site_image": site["image_url"],
                "included_items": site["included_items"] or "",
                "suggested": False,
            })
        else:
            # Linked site product vanished from snapshot -> show in 'fali na sajtu'
            pairs.append({
                "type": "linked_missing_site",
                "product_id": crm["id"], "name": crm["name"],
                "brand": crm["brand"], "category": crm["category"],
                "site_id": site_id, "site_name": None,
                "site_brand": None, "site_cat": None,
                "site_url": None, "site_image": None,
                "included_items": "",
                "suggested": False,
                "note": "Sajt proizvod je nestao iz snapshot-a",
            })

    # 2. Suggested pairs (exact name match) - only if both sides unlinked
    for crm in crm_rows:
        if crm["id"] in used_crm:
            continue
        site = site_by_norm.get(norm(crm["name"]))
        if site is None or site["id"] in used_site:
            continue
        used_crm.add(crm["id"])
        used_site.add(site["id"])
        pairs.append({
            "type": "linked",  # shown as pair (suggestion)
            "product_id": crm["id"], "name": crm["name"],
            "brand": crm["brand"], "category": crm["category"],
            "site_id": site["id"], "site_name": site["name"],
            "site_brand": site["brand_name"], "site_cat": site["cat_name"],
            "site_url": site["url"], "site_image": site["image_url"],
            "included_items": site["included_items"] or "",
            "suggested": True,
        })

    # 3. CRM-only (unlinked CRM products not matched by name)
    for crm in crm_rows:
        if crm["id"] not in used_crm:
            crm_only.append({
                "type": "crm_only",
                "product_id": crm["id"], "name": crm["name"],
                "brand": crm["brand"], "category": crm["category"],
            })

    # 4. Site-only (unlinked site products not matched by name)
    for site in site_rows:
        if site["id"] not in used_site:
            site_only.append({
                "type": "site_only",
                "site_id": site["id"], "site_name": site["name"],
                "site_brand": site["brand_name"], "site_cat": site["cat_name"],
                "site_url": site["url"], "site_image": site["image_url"],
                "included_items": site["included_items"] or "",
                "crm_linked_missing": False,
            })

    # Fetch brand/category dropdown options for the "Add to CRM" dialog
    cur.execute("SELECT name FROM brands ORDER BY name;")
    brand_names = [r["name"] for r in cur.fetchall()]
    cur.execute("SELECT category FROM category_pricing_defaults ORDER BY category;")
    cat_names = [r["category"] for r in cur.fetchall()]
    cur.execute("SELECT MAX(fetched_at) AS fetched_at FROM site_products;")
    fetched_row = cur.fetchone()
    fetched_at = fetched_row["fetched_at"] if fetched_row else None

    conn.close()

    # Apply filter
    if filter_val == "unlinked":
        # Show all rows without an active link (suggested pairs + CRM-only + site-only)
        pairs = [p for p in pairs if p.get("suggested")]
        crm_only = crm_only
        site_only = site_only
    elif filter_val == "crm_missing":
        # Only site products missing a CRM counterpart
        pairs = []
        crm_only = []
        site_only = site_only
    elif filter_val == "site_missing":
        # Only CRM products missing a site counterpart (incl. vanished links)
        pairs = [p for p in pairs if p.get("type") == "linked_missing_site"]
        crm_only = crm_only
        site_only = []
    elif filter_val == "all":
        pass

    return jsonify({
        "success": True,
        "data": {
            "pairs": pairs,
            "crm_only": crm_only,
            "site_only": site_only,
            "fetched_at": fetched_at,
            "brands": brand_names,
            "categories": cat_names,
        }
    })


@api_v1.route("/sync/link", methods=["POST"])
@require_api_key
def sync_link():
    """Manually link a CRM product to a site product (1:1, no name check - any pair allowed)."""
    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    site_id = data.get("site_id")
    if not product_id or not site_id:
        return jsonify({"success": False, "error": "product_id and site_id are required."}), 400

    conn = get_db()
    cur = conn.cursor()

    # Verify both exist
    cur.execute("SELECT id FROM products WHERE id = ?;", (product_id,))
    if cur.fetchone() is None:
        conn.close()
        return jsonify({"success": False, "error": "CRM product not found."}), 404
    cur.execute("SELECT id FROM site_products WHERE id = ?;", (site_id,))
    if cur.fetchone() is None:
        conn.close()
        return jsonify({"success": False, "error": "Site product not found."}), 404

    # Check 1:1 constraints
    cur.execute("SELECT site_product_id FROM products WHERE site_product_id = ?;", (site_id,))
    if cur.fetchone() is not None:
        conn.close()
        return jsonify({"success": False, "error": "Site product is already linked to another CRM product."}), 400
    cur.execute("SELECT site_product_id FROM products WHERE id = ? AND site_product_id IS NOT NULL;", (product_id,))
    if cur.fetchone() is not None:
        conn.close()
        return jsonify({"success": False, "error": "CRM product is already linked."}), 400

    cur.execute("UPDATE products SET site_product_id = ? WHERE id = ?;", (site_id, product_id))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "data": {"product_id": product_id, "site_id": site_id}})


@api_v1.route("/sync/unlink", methods=["POST"])
@require_api_key
def sync_unlink():
    """Break a link between a CRM product and a site product."""
    data = request.get_json(silent=True) or {}
    product_id = data.get("product_id")
    if not product_id:
        return jsonify({"success": False, "error": "product_id is required."}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE products SET site_product_id = NULL WHERE id = ?;", (product_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "data": {"product_id": product_id}})


@api_v1.route("/sync/product_info")
@require_api_key
def sync_product_info():
    """
    Fetch a single site product (fresh from the WP API) and build its description
    for the 'Add to CRM' dialog. Returns name, description, brand, category,
    image_url, url, and exact-name-match CRM product id (if any).
    """
    site_id = request.args.get("site_id", type=int)
    if not site_id:
        return jsonify({"success": False, "error": "site_id is required."}), 400

    names = _fetch_brand_and_cat_names()
    try:
        resp = http_requests.get(
            f"{SITE_API_BASE}/product/{site_id}", timeout=SITE_TIMEOUT,
        )
        resp.raise_for_status()
        item = resp.json()
    except Exception as e:
        return jsonify({"success": False, "error": f"Neuspešno preuzimanje proizvoda sa sajta: {str(e)}"}), 502

    title = _clean_html(item.get("title", {}).get("rendered") or "")
    brand_ids = item.get("product_brand") or []
    cat_ids = item.get("product_cat") or []
    site_product = {
        "id": item.get("id"),
        "name": title,
        "excerpt": item.get("excerpt", {}).get("rendered") or "",
        "content": item.get("content", {}).get("rendered") or "",
        "included_items": (item.get("acf") or {}).get("included_items") or "",
    }
    description = build_product_description(site_product)

    image_url = None
    if item.get("featured_media"):
        image_url = _fetch_media_url(item["featured_media"])

    brand_name = names["brands"].get(brand_ids[0]) if brand_ids else None
    cat_name = names["cats"].get(cat_ids[0]) if cat_ids else None

    # Exact-name-match CRM product (case-insensitive, trimmed) for pre-selection
    crm_id = None
    crm_match_brand = ""
    crm_match_category = ""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, brand, category FROM products WHERE name = ? COLLATE NOCASE LIMIT 1;",
        (title.strip(),),
    )
    row = cur.fetchone()
    if row:
        crm_id = row["id"]
        crm_match_brand = row["brand"] or ""
        crm_match_category = row["category"] or ""
    conn.close()

    return jsonify({
        "success": True,
        "data": {
            "site_id": site_id,
            "name": title,
            "description": description,
            "brand": brand_name,
            "category": cat_name,
            "image_url": image_url,
            "url": item.get("link"),
            "included_items": site_product.get("included_items") or "",
            "crm_match_id": crm_id,
            "crm_match_brand": crm_match_brand,
            "crm_match_category": crm_match_category,
        }
    })


@api_v1.route("/sync/add_product", methods=["POST"])
@require_api_key
def sync_add_product():
    """
    Create a CRM product from a site product (manual 'Add to CRM' action).
    Accepts JSON: {site_id, name, description, brand, category, image_url}.
    Creates the product and immediately links it to the site product (1:1).
    """
    data = request.get_json(silent=True) or {}
    site_id = data.get("site_id")
    name = (data.get("name") or "").strip()
    description = data.get("description") or ""
    brand = data.get("brand") or ""
    category = data.get("category") or ""
    image_url = (data.get("image_url") or "").strip()

    if not site_id:
        return jsonify({"success": False, "error": "site_id is required."}), 400
    if not name:
        return jsonify({"success": False, "error": "Product name is required."}), 400

    conn = get_db()
    cur = conn.cursor()

    # Verify site product exists in snapshot
    cur.execute("SELECT id FROM site_products WHERE id = ?;", (site_id,))
    if cur.fetchone() is None:
        conn.close()
        return jsonify({"success": False, "error": "Site product not found in snapshot."}), 404

    # Check duplicate name (case-insensitive)
    cur.execute("SELECT id FROM products WHERE name = ? COLLATE NOCASE;", (name,))
    if cur.fetchone():
        conn.close()
        return jsonify({"success": False, "error": f"A product with name '{name}' already exists."}), 409

    # Download image if provided (reuse existing photo_url mechanism)
    photo_path = None
    try:
        if image_url:
            stream, orig_filename = download_image_from_url(image_url)
            photo_path = save_product_image(stream, orig_filename, name)
    except ValueError as e:
        conn.close()
        return jsonify({"success": False, "error": str(e)}), 400

    # Create the CRM product
    cur.execute("""
        INSERT INTO products (name, description, category, brand, photo_path)
        VALUES (?, ?, ?, ?, ?);
    """, (name, description, category, brand, photo_path))
    new_id = cur.lastrowid

    # Link immediately (1:1). Check site side not already linked.
    cur.execute("SELECT site_product_id FROM products WHERE site_product_id = ?;", (site_id,))
    if cur.fetchone() is not None:
        conn.rollback()
        conn.close()
        return jsonify({"success": False, "error": "Site product is already linked to another CRM product."}), 400

    cur.execute("UPDATE products SET site_product_id = ? WHERE id = ?;", (site_id, new_id))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "data": {
            "product_id": new_id,
            "site_id": site_id,
            "name": name,
        }
    })


# ---------- OpenAPI Spec ----------

@api_v1.route("/openapi.json")
def openapi_spec():
    """Auto-generated OpenAPI 3.0 specification for AI tool discovery."""
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "QP-CRM API",
            "description": "AI-friendly API for managing products, categories, and brands in QP-CRM.",
            "version": "1.0.0",
        },
        "servers": [
            {"url": "http://localhost:5000", "description": "Local pricing server"},
        ],
        "security": [
            {"bearerAuth": []}
        ],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "hex token (48 characters)",
                }
            },
            "schemas": {
                "Product": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "name": {"type": "string"},
                        "description": {"type": "string", "nullable": True},
                        "category": {"type": "string", "nullable": True},
                        "brand": {"type": "string", "nullable": True},
                        "photo_path": {"type": "string", "nullable": True},
                        "photo_url": {"type": "string", "nullable": True},
                        "current_price": {"type": "number", "nullable": True},
                        "current_discount_price": {"type": "number", "nullable": True},
                    }
                },
                "Category": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "import_percent": {"type": "number"},
                        "margin_percent": {"type": "number"},
                        "domestic_transport": {"type": "number"},
                        "default_extras": {"type": "number"},
                        "warranty_percent": {"type": "number"},
                        "service_percent": {"type": "number"},
                        "instalation": {"type": "number"},
                        "traning": {"type": "number"},
                        "other": {"type": "number"},
                    }
                },
                "Error": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean", "enum": [False]},
                        "error": {"type": "string"},
                    }
                },
            },
        },
        "paths": {
            "/api/v1/health": {
                "get": {
                    "summary": "Health check",
                    "operationId": "healthCheck",
                    "security": [],
                    "responses": {
                        "200": {"description": "API is running"},
                    }
                }
            },
            "/api/v1/products": {
                "get": {
                    "summary": "List/search products",
                    "operationId": "listProducts",
                    "parameters": [
                        {"name": "search", "in": "query", "schema": {"type": "string"}},
                        {"name": "brand", "in": "query", "schema": {"type": "string"}},
                        {"name": "category", "in": "query", "schema": {"type": "string"}},
                        {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}},
                        {"name": "per_page", "in": "query", "schema": {"type": "integer", "default": 25}},
                    ],
                    "responses": {
                        "200": {"description": "Paginated product list"},
                    }
                },
                "post": {
                    "summary": "Create a new product",
                    "operationId": "createProduct",
                    "requestBody": {
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "description": {"type": "string"},
                                        "category": {"type": "string"},
                                        "brand": {"type": "string"},
                                        "photo": {"type": "string", "format": "binary"},
                                        "photo_url": {"type": "string", "description": "URL to download photo from"},
                                    },
                                    "required": ["name"],
                                }
                            },
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "description": {"type": "string"},
                                        "category": {"type": "string"},
                                        "brand": {"type": "string"},
                                        "photo_url": {"type": "string"},
                                    },
                                    "required": ["name"],
                                }
                            },
                        }
                    },
                    "responses": {
                        "201": {"description": "Product created"},
                        "400": {"description": "Validation error"},
                        "409": {"description": "Duplicate name"},
                    }
                },
            },
            "/api/v1/products/{product_id}": {
                "get": {
                    "summary": "Get product by ID",
                    "operationId": "getProduct",
                    "parameters": [
                        {"name": "product_id", "in": "path", "required": True, "schema": {"type": "integer"}},
                    ],
                    "responses": {
                        "200": {"description": "Product details"},
                        "404": {"description": "Not found"},
                    }
                },
                "put": {
                    "summary": "Update a product",
                    "operationId": "updateProduct",
                    "parameters": [
                        {"name": "product_id", "in": "path", "required": True, "schema": {"type": "integer"}},
                    ],
                    "requestBody": {
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "description": {"type": "string"},
                                        "category": {"type": "string"},
                                        "brand": {"type": "string"},
                                        "photo": {"type": "string", "format": "binary"},
                                        "photo_url": {"type": "string"},
                                    },
                                }
                            },
                        }
                    },
                    "responses": {
                        "200": {"description": "Product updated"},
                        "404": {"description": "Not found"},
                    }
                },
                "delete": {
                    "summary": "Delete a product",
                    "operationId": "deleteProduct",
                    "parameters": [
                        {"name": "product_id", "in": "path", "required": True, "schema": {"type": "integer"}},
                    ],
                    "responses": {
                        "200": {"description": "Product deleted"},
                        "404": {"description": "Not found"},
                    }
                },
            },
            "/api/v1/categories": {
                "get": {
                    "summary": "List all categories",
                    "operationId": "listCategories",
                    "parameters": [
                        {"name": "search", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {"description": "Category list"},
                    }
                },
                "post": {
                    "summary": "Create or update a category",
                    "operationId": "createOrUpdateCategory",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "category": {"type": "string"},
                                        "import_percent": {"type": "number", "description": "7 for 7% or 0.07"},
                                        "margin_percent": {"type": "number", "description": "40 for 40% or 0.40"},
                                        "domestic_transport": {"type": "number"},
                                        "default_extras": {"type": "number"},
                                        "warranty_percent": {"type": "number"},
                                        "service_percent": {"type": "number"},
                                        "instalation": {"type": "number"},
                                        "traning": {"type": "number"},
                                        "other": {"type": "number"},
                                    },
                                    "required": ["category"],
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Category created/updated"},
                        "400": {"description": "Validation error"},
                    }
                },
            },
            "/api/v1/categories/{category_name}": {
                "delete": {
                    "summary": "Delete a category",
                    "operationId": "deleteCategory",
                    "parameters": [
                        {"name": "category_name", "in": "path", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {"description": "Category deleted"},
                        "404": {"description": "Not found"},
                        "409": {"description": "Category in use"},
                    }
                },
            },
            "/api/v1/brands": {
                "get": {
                    "summary": "List all brands",
                    "operationId": "listBrands",
                    "parameters": [
                        {"name": "search", "in": "query", "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {"description": "Brand list"},
                    }
                },
                "post": {
                    "summary": "Create a brand",
                    "operationId": "createBrand",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                    },
                                    "required": ["name"],
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Brand created"},
                        "400": {"description": "Validation error"},
                    }
                },
            },
            "/api/v1/brands/{brand_name}": {
                "delete": {
                    "summary": "Delete a brand",
                    "operationId": "deleteBrand",
                    "parameters": [
                        {"name": "brand_name", "in": "path", "required": True, "schema": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {"description": "Brand deleted"},
                        "404": {"description": "Not found"},
                        "409": {"description": "Brand in use"},
                    }
                },
            },
        },
    }
    return jsonify(spec)