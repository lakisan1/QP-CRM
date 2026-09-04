"""Product routes: sync page, list, quick update, add, edit and delete."""

import os
import re
import sqlite3
from datetime import date

from flask import redirect, render_template, request, session, url_for

from shared.config import IMAGE_DIR

from ..app import (
    apply_rounding,
    bp,
    download_image_from_url,
    get_api_key,
    get_db,
    save_product_image,
)

# ---------- PRODUCTS ----------

@bp.route("/products/product_sync")
def product_sync():
    """Sajt <-> CRM product comparison/sync page (manual sync only)."""
    return render_template(
        "pricing/product_sync.html",
        api_key=get_api_key(),
    )

@bp.route("/products")
def list_products():
    # Check if we should clear filters
    if request.args.get("clear"):
        session.pop("products_filter_brand", None)
        session.pop("products_filter_category", None)
        session.pop("products_filter_search", None)
        return redirect(url_for("pricing.list_products"))

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

    sort_option = request.args.get("sort")
    if sort_option is None:
        sort_option = session.get("products_sort_option", "name_asc") # Default sort
    else:
        session["products_sort_option"] = sort_option

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
        # search by name (case-insensitive-ish)
        where_clauses.append("p.name LIKE ?")
        params.append(f"%{search_term}%")

    if where_clauses:
        where_stmt = " WHERE " + " AND ".join(where_clauses)
        count_query += where_stmt
        query += where_stmt

    # Execute count before applying sort/limit
    cur.execute(count_query, params)
    total_count = cur.fetchone()["total_count"]

    import math
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
        "pricing/products.html",
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
@bp.route("/products/quick_update")
def quick_update_products():
    # Check if we should clear filters
    if request.args.get("clear"):
        session.pop("products_filter_brand", None)
        session.pop("products_filter_category", None)
        session.pop("products_filter_search", None)
        return redirect(url_for("pricing.quick_update_products"))

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

    page = request.args.get("page", 1, type=int)

    conn = get_db()
    cur = conn.cursor()

    # Fetch default items per page
    cur.execute("SELECT value FROM global_settings WHERE key = 'default_items_per_page';")
    row = cur.fetchone()
    items_per_page = int(row["value"]) if row else 25
    offset = (page - 1) * items_per_page

    count_query = "SELECT COUNT(*) AS total_count FROM products p"

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
        where_stmt = " WHERE " + " AND ".join(where_clauses)
        count_query += where_stmt
        query += where_stmt

    # Execute count before applying sort/limit
    cur.execute(count_query, params)
    total_count = cur.fetchone()["total_count"]

    import math
    total_pages = math.ceil(total_count / items_per_page) if total_count > 0 else 1

    query += " ORDER BY p.name, p.category"
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
        "pricing/quick_update.html",
        products=products,
        brand_filter=brand_filter,
        category_filter=category_filter,
        brand_options=brand_options,
        category_options=category_options,
        search_term=search_term,
        current_page=page,
        total_pages=total_pages,
        total_count=total_count
    )

@bp.route("/products/<int:product_id>/quick_update_save", methods=["POST"])
def quick_update_save(product_id):
    if request.method != "POST":
        return redirect(url_for("pricing.quick_update_products"))
        
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
    
    return redirect(url_for("pricing.quick_update_products", brand=ref_brand, category=ref_category, search=ref_search))

@bp.route("/products/add", methods=["GET", "POST"])
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
                "pricing/product_form.html",
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
                photo_path = save_product_image(
                    photo_file.stream, photo_file.filename, name,
                    error_ext="Slika mora biti JPG, PNG ili WEBP (.jpg, .jpeg, .png, ili .webp).",
                    error_process_prefix="Gre\u0161ka pri obradi slike: ")
            elif photo_url:
                # Priority 2: Download from URL
                stream, orig_filename = download_image_from_url(
                    photo_url,
                    error_content_type="URL ne vodi do JPG, PNG ili WEBP slike.",
                    error_request_prefix="Gre\u0161ka pri preuzimanju slike sa URL-a: ")
                photo_path = save_product_image(
                    stream, orig_filename, name,
                    error_ext="Slika mora biti JPG, PNG ili WEBP (.jpg, .jpeg, .png, ili .webp).",
                    error_process_prefix="Gre\u0161ka pri obradi slike: ")
        except ValueError as e:
            # Create a temporary product object to preserve form data
            temp_product = {
                "name": name,
                "description": description,
                "category": category,
                "brand": brand,
                "photo_url": photo_url,
                "id": None
            }
            conn.close()
            return render_template(
                "pricing/product_form.html",
                categories=categories,
                brand_options=brand_options,
                product=temp_product,
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
            return redirect(url_for("pricing.new_price", product_id=new_product_id))

        return redirect(url_for("pricing.list_products"))

    # GET – load existing categories and brands
    cur.execute("SELECT category FROM category_pricing_defaults ORDER BY category;")
    cat_rows = cur.fetchall()
    cur.execute("SELECT name FROM brands ORDER BY name;")
    brand_rows = cur.fetchall()
    
    product = None
    duplicate_id = request.args.get("duplicate_id", type=int)
    if duplicate_id:
        cur.execute("SELECT * FROM products WHERE id = ?;", (duplicate_id,))
        row = cur.fetchone()
        if row:
            product = dict(row)
            product["name"] = ""
            product["photo_path"] = None
            product["photo_url"] = ""
            product["id"] = None
            
    conn.close()

    categories = [row["category"] for row in cat_rows]
    brand_options = [row["name"] for row in brand_rows]

    return render_template(
        "pricing/product_form.html",
        categories=categories,
        brand_options=brand_options,
        product=product
    )

@bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
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
            # Convert row to dict to safely modify/pass back
            product_dict = dict(product)
            product_dict["name"] = name
            product_dict["description"] = description
            product_dict["category"] = category
            product_dict["brand"] = brand
            
            return render_template(
                "pricing/product_form.html",
                categories=categories,
                brand_options=brand_options,
                product=product_dict,
                error="Drugi proizvod sa ovim imenom već postoji."
            )

        # handle photo upload (file or URL)
        photo_file = request.files.get("photo_file")
        photo_url = (request.form.get("photo_url") or "").strip()
        photo_path = product["photo_path"] # default to existing
        
        try:
            if photo_file and photo_file.filename:
                photo_path = save_product_image(
                    photo_file.stream, photo_file.filename, name,
                    error_ext="Slika mora biti JPG, PNG ili WEBP (.jpg, .jpeg, .png, ili .webp).",
                    error_process_prefix="Gre\u0161ka pri obradi slike: ")
            elif photo_url:
                stream, orig_filename = download_image_from_url(
                    photo_url,
                    error_content_type="URL ne vodi do JPG, PNG ili WEBP slike.",
                    error_request_prefix="Gre\u0161ka pri preuzimanju slike sa URL-a: ")
                photo_path = save_product_image(
                    stream, orig_filename, name,
                    error_ext="Slika mora biti JPG, PNG ili WEBP (.jpg, .jpeg, .png, ili .webp).",
                    error_process_prefix="Gre\u0161ka pri obradi slike: ")
            else:
                # No new photo provided. Check if name changed and photo exists.
                if photo_path and product["name"] != name:
                    ext = os.path.splitext(photo_path)[1].lower()
                    if not ext:
                        ext = ".jpg"

                    base = (name or "").strip().lower()
                    base = re.sub(r"\s+", "_", base)
                    base = re.sub(r"[^a-z0-9_-]", "", base)
                    if not base:
                        base = "product"

                    new_filename = base + ext

                    if new_filename != photo_path:
                        old_full_path = os.path.join(IMAGE_DIR, photo_path)
                        new_full_path = os.path.join(IMAGE_DIR, new_filename)
                        
                        if os.path.exists(old_full_path):
                            try:
                                os.rename(old_full_path, new_full_path)
                                photo_path = new_filename
                            except Exception as e:
                                print(f"Error renaming image {old_full_path} to {new_full_path}: {e}")

        except ValueError as e:
            # Create a temporary product object to preserve form data, keeping original ID/path
            # Convert to dict to allow assignment (sqlite3.Row is immutable)
            product = dict(product)
            product["name"] = name
            product["description"] = description
            product["category"] = category
            product["brand"] = brand
            product["photo_url"] = photo_url # Carry over the failed URL so user can see/fix it
            
            conn.close()
            return render_template(
                "pricing/product_form.html",
                categories=categories,
                brand_options=brand_options,
                product=product,
                error=str(e)
            )

        # Delete old photo if it was replaced and has a different name
        if product["photo_path"] and photo_path != product["photo_path"]:
            old_full_path = os.path.join(IMAGE_DIR, product["photo_path"])
            if os.path.exists(old_full_path):
                try:
                    os.remove(old_full_path)
                except Exception as e:
                    print(f"Error removing replaced image {old_full_path}: {e}")

        cur.execute("""
            UPDATE products
            SET name = ?, description = ?, category = ?, brand = ?, photo_path = ?
            WHERE id = ?;
        """, (name, description, category, brand, photo_path, product_id))
        conn.commit()
        conn.close()

        # Check which button was clicked
        action = request.form.get("action")
        if action == "save_add_price":
            return redirect(url_for("pricing.new_price", product_id=product_id))

        return redirect(url_for("pricing.list_products"))

    # GET – load categories and brands for dropdowns
    cur.execute("SELECT category FROM category_pricing_defaults ORDER BY category;")
    cat_rows = cur.fetchall()
    categories = [row["category"] for row in cat_rows]

    cur.execute("SELECT name FROM brands ORDER BY name;")
    brand_rows = cur.fetchall()
    brand_options = [row["name"] for row in brand_rows]

    conn.close()

    return render_template(
        "pricing/product_form.html",
        categories=categories,
        brand_options=brand_options,
        product=product
    )


@bp.route("/products/<int:product_id>/delete", methods=["POST"])
def delete_product(product_id):
    conn = get_db()
    cur = conn.cursor()

    # Fetch product to get the photo path before deleting
    cur.execute("SELECT photo_path FROM products WHERE id = ?;", (product_id,))
    product = cur.fetchone()

    # 1) Detach from offers (so snapshots stay valid)
    try:
        cur.execute("""
            UPDATE offer_items
            SET product_id = NULL
            WHERE product_id = ?;
        """, (product_id,))
    except sqlite3.OperationalError:
        # If offer tables don't exist yet, just ignore
        pass

    # 2) Delete all prices for this product
    cur.execute("DELETE FROM prices WHERE product_id = ?;", (product_id,))

    # 3) Delete the product itself
    cur.execute("DELETE FROM products WHERE id = ?;", (product_id,))

    conn.commit()
    conn.close()

    # 4) Delete the photo file
    if product and product["photo_path"]:
        file_path = os.path.join(IMAGE_DIR, product["photo_path"])
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error removing image {file_path}: {e}")

    return redirect(url_for("pricing.list_products"))  # or whatever your products list endpoint is called
