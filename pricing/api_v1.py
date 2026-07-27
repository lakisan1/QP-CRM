"""
AI-Friendly REST API v1 for QP-CRM
Provides endpoints for Products, Categories, and Brands management.
Authentication: Bearer token (API key).
"""

import os
import sys
import re
import io
from functools import wraps
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