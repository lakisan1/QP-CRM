"""Price routes: history, new, edit and delete price entries."""

from datetime import date

from flask import redirect, render_template, request, url_for

from ..app import apply_rounding, bp, get_db

# ---------- PRICES ----------

@bp.route("/products/<int:product_id>/prices")
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
    return render_template("pricing/price_history.html", product=product, prices=prices)


@bp.route("/products/<int:product_id>/prices/new", methods=["GET", "POST"])
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
        return redirect(url_for("pricing.list_products"))

    # Load rounding rules for JS
    cur.execute("SELECT * FROM price_rounding_rules ORDER BY target, limit_val ASC;")
    rules_rows = cur.fetchall()
    rules_json = {'price': [], 'discount': []}
    for r in rules_rows:
        rules_json[r['target']].append({'limit': r['limit_val'], 'step': r['step_val'], 'method': r['method']})

    conn.close()
    # When rendering form, show percents as "x 100"
    return render_template(
        "pricing/price_form.html",
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

@bp.route("/products/<int:product_id>/prices/<int:price_id>/edit", methods=["GET", "POST"])
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
        return redirect(url_for("pricing.list_products"))

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
        "pricing/price_form.html",
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

@bp.route("/products/<int:product_id>/prices/<int:price_id>/delete", methods=["POST"])
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

    return redirect(url_for("pricing.price_history", product_id=product_id))
