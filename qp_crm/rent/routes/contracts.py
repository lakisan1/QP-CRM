"""Rent contract CRUD + calculation API routes."""
import math
from datetime import date, datetime

from flask import jsonify, redirect, render_template, request, url_for

from qp_crm.shared.web import fetch_rent_defaults

from ..app import bp, calculate_rent, get_db


@bp.route("/contracts")
def list_contracts():
    search = request.args.get("search", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    signed_filter = request.args.get("signed", "all").strip()  # all, signed, unsigned
    page = request.args.get("page", 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    conn = get_db()
    cur = conn.cursor()

    clauses, params = [], []
    if search:
        clauses.append("(contract_number LIKE ? OR client_name LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if date_from:
        clauses.append("contract_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("contract_date <= ?")
        params.append(date_to)
    if signed_filter == "signed":
        clauses.append("is_signed = 1")
    elif signed_filter == "unsigned":
        clauses.append("(is_signed IS NULL OR is_signed = 0)")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    cur.execute(f"SELECT COUNT(*) as c FROM rent_contracts {where}", params)
    total = cur.fetchone()["c"]
    total_pages = math.ceil(total / per_page) if total else 1

    cur.execute(f"SELECT * FROM rent_contracts {where} ORDER BY contract_date DESC, id DESC LIMIT {per_page} OFFSET {offset}", params)
    contracts = cur.fetchall()
    conn.close()

    return render_template("rent/rent_contracts.html",
                           contracts=contracts,
                           search=search, date_from=date_from, date_to=date_to,
                           signed_filter=signed_filter,
                           current_page=page, total_pages=total_pages, total=total,
                           calculate_rent=calculate_rent)


@bp.route("/contracts/toggle_signed/<int:contract_id>", methods=["POST"])
def toggle_signed(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT is_signed FROM rent_contracts WHERE id=?;", (contract_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    new_val = 0 if row["is_signed"] else 1
    cur.execute("UPDATE rent_contracts SET is_signed=? WHERE id=?;", (new_val, contract_id))
    conn.commit()
    conn.close()
    return jsonify({"is_signed": new_val})


@bp.route("/contracts/new", methods=["GET", "POST"])
def new_contract():
    return _contract_form(None)


@bp.route("/contracts/edit/<int:contract_id>", methods=["GET", "POST"])
def edit_contract(contract_id):
    return _contract_form(contract_id)


def _get_rent_defaults():
    """Fetch rent default parameters from global_settings."""
    conn = get_db()
    cur = conn.cursor()
    result = fetch_rent_defaults(cur)
    conn.close()
    return result


def generate_next_contract_number(db_conn, contract_date_str):
    """Generate contract number using: counter (zero-padded 2 chars) + month (2 chars) + year (2 chars)."""
    try:
        dt = datetime.strptime(contract_date_str, "%Y-%m-%d")
    except Exception:
        dt = date.today()
    
    year_short = dt.strftime("%y")  # '26'
    month_str = dt.strftime("%m")   # '06'
    
    cur = db_conn.cursor()
    pattern = f"{dt.year:04d}-{dt.month:02d}-%"
    cur.execute("SELECT COUNT(*) as cnt FROM rent_contracts WHERE contract_date LIKE ?;", (pattern,))
    count = cur.fetchone()["cnt"]
    
    next_counter = count + 1
    return f"{next_counter:02d}{month_str}{year_short}"


def _contract_form(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_clients ORDER BY name;")
    clients = cur.fetchall()
    cur.execute("SELECT * FROM rent_equipment ORDER BY name;")
    equipment = cur.fetchall()

    contract = None
    if contract_id:
        cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
        contract = cur.fetchone()

    if request.method == "POST":
        c_number = request.form.get("contract_number", "").strip()
        c_date = request.form.get("contract_date") or date.today().isoformat()
        
        # Auto-generate if new and contract number is empty
        if not contract_id and not c_number:
            c_number = generate_next_contract_number(conn, c_date)

        data = {
            "contract_number": c_number,
            "contract_date": c_date,
            "client_name": request.form.get("client_name", "").strip(),
            "client_mb": request.form.get("client_mb", "").strip(),
            "client_pib": request.form.get("client_pib", "").strip(),
            "client_account": request.form.get("client_account", "").strip(),
            "client_address": request.form.get("client_address", "").strip(),
            "client_representative": request.form.get("client_representative", "").strip(),
            "client_email": request.form.get("client_email", "").strip(),
            "rent_address": request.form.get("rent_address", "").strip(),
            "guarantor": request.form.get("guarantor", "").strip(),
            "delivery_time": request.form.get("delivery_time", "").strip(),
            "delivery_date": request.form.get("delivery_date", "").strip(),
            "equipment_model": request.form.get("equipment_model", "").strip(),
            "price": float(request.form.get("price") or 0),
            "vat_percent": float(request.form.get("vat_percent") or 20),
            "period_months": int(request.form.get("period_months") or 48),
            "downpayment_percent": float(request.form.get("downpayment_percent") or 20),
            "salvage_value_percent": float(request.form.get("salvage_value_percent") or 20),
            "interest_rate": float(request.form.get("interest_rate") or 14),
            "insurance_rate": float(request.form.get("insurance_rate") or 1.13),
            "guarantee_rate": float(request.form.get("guarantee_rate") or 5),
            "admin_fee": float(request.form.get("admin_fee") or 50),
        }
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        if contract_id:
            sets = ", ".join(f"{k}=?" for k in data.keys())
            cur.execute(f"UPDATE rent_contracts SET {sets} WHERE id=?;", list(data.values()) + [contract_id])
            conn.commit()
            conn.close()
            return redirect(url_for("rent.edit_contract", contract_id=contract_id))
        else:
            cur.execute(f"INSERT INTO rent_contracts ({cols}) VALUES ({placeholders});", list(data.values()))
            new_id = cur.lastrowid
            conn.commit()
            conn.close()
            return redirect(url_for("rent.edit_contract", contract_id=new_id))

    conn.close()
    rent_defaults = _get_rent_defaults()
    return render_template("rent/rent_contract_form.html",
                           contract=contract,
                           clients=clients,
                           equipment=equipment,
                           today=date.today().isoformat(),
                           rent_defaults=rent_defaults)


@bp.route("/contracts/delete/<int:contract_id>", methods=["POST"])
def delete_contract(contract_id):
    conn = get_db()
    conn.execute("DELETE FROM rent_contracts WHERE id=?;", (contract_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("rent.list_contracts"))


@bp.route("/contracts/duplicate/<int:contract_id>", methods=["POST"])
def duplicate_contract(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
    row = cur.fetchone()
    if row:
        d = dict(row)
        d.pop("id")
        d["contract_number"] = d.get("contract_number", "") + "-KOPIJA"
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        cur.execute(f"INSERT INTO rent_contracts ({cols}) VALUES ({placeholders});", list(d.values()))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        return redirect(url_for("rent.edit_contract", contract_id=new_id))
    conn.close()
    return redirect(url_for("rent.list_contracts"))


# ─── API endpoints ─────────────────────────────────────────────────────────────
@bp.route("/api/client/<int:client_id>")
def api_client(client_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_clients WHERE id=?;", (client_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({}), 404
    return jsonify(dict(row))


@bp.route("/api/equipment/<int:eq_id>")
def api_equipment(eq_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_equipment WHERE id=?;", (eq_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({}), 404
    return jsonify(dict(row))


@bp.route("/api/calculate")
def api_calculate():
    try:
        price = float(request.args.get("price", 0))
        period = int(request.args.get("period_months", 48))
        dp = float(request.args.get("downpayment_percent", 20))
        sv = float(request.args.get("salvage_value_percent", 20))
        ir = float(request.args.get("interest_rate", 14))
        ins = float(request.args.get("insurance_rate", 1.13))
        gr = float(request.args.get("guarantee_rate", 5))
        vat = float(request.args.get("vat_percent", 20))
        admin = float(request.args.get("admin_fee", 50))
        result = calculate_rent(price, period, dp, sv, ir, ins, gr, vat, admin)
        return jsonify({k: round(v, 4) for k, v in result.items()})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
