"""Catalog routes: category pricing defaults and brands."""

import sqlite3

from flask import redirect, render_template, request, url_for

from ..app import bp, get_db

# ---------- CATEGORY DEFAULTS ----------

@bp.route("/category-defaults", methods=["GET", "POST"])
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

    return render_template("pricing/category_defaults.html", defaults=defaults, error=request.args.get("error"))

@bp.route("/category-defaults/delete", methods=["POST"])
def delete_category_default():
    cat_to_delete = request.form.get("category_to_delete")
    if not cat_to_delete:
        return redirect(url_for("pricing.category_defaults"))
    
    conn = get_db()
    cur = conn.cursor()

    # Check if used
    cur.execute("SELECT id FROM products WHERE category = ? LIMIT 1;", (cat_to_delete,))
    in_use = cur.fetchone()

    if in_use:
        conn.close()
        return redirect(url_for("pricing.category_defaults", error=f"Cannot delete category '{cat_to_delete}' because it is used by one or more products."))

    cur.execute("DELETE FROM category_pricing_defaults WHERE category = ?;", (cat_to_delete,))
    conn.commit()
    conn.close()
    
    return redirect(url_for("pricing.category_defaults"))

@bp.route("/brands", methods=["GET", "POST"])
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

    return render_template("pricing/brands.html", brands=rows, error=request.args.get("error"))

@bp.route("/brands/delete", methods=["POST"])
def delete_brand():
    brand_to_delete = request.form.get("brand_to_delete")
    if not brand_to_delete:
        return redirect(url_for("pricing.brands"))

    conn = get_db()
    cur = conn.cursor()

    # Check if used
    cur.execute("SELECT id FROM products WHERE brand = ? LIMIT 1;", (brand_to_delete,))
    in_use = cur.fetchone()

    if in_use:
        conn.close()
        return redirect(url_for("pricing.brands", error=f"Cannot delete brand '{brand_to_delete}' because it is used by one or more products."))

    cur.execute("DELETE FROM brands WHERE name = ?;", (brand_to_delete,))
    conn.commit()
    conn.close()

    return redirect(url_for("pricing.brands"))
