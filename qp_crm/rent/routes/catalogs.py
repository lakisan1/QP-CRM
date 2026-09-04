"""Rent catalog CRUD: clients and equipment."""
from flask import redirect, render_template, request, url_for

from ..app import bp, get_db


# ─── Clients CRUD ──────────────────────────────────────────────────────────────
@bp.route("/clients", methods=["GET", "POST"])
def list_clients():
    conn = get_db()
    cur = conn.cursor()
    msg = None
    edit_client = None
    edit_id = request.args.get("edit_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "save":
            data = {
                "name": request.form.get("name", "").strip(),
                "mb": request.form.get("mb", "").strip(),
                "pib": request.form.get("pib", "").strip(),
                "account": request.form.get("account", "").strip(),
                "address": request.form.get("address", "").strip(),
                "representative": request.form.get("representative", "").strip(),
                "email": request.form.get("email", "").strip(),
                "rent_address": request.form.get("rent_address", "").strip(),
                "guarantor": request.form.get("guarantor", "").strip(),
            }
            cid = request.form.get("client_id", type=int)
            if cid:
                sets = ", ".join(f"{k}=?" for k in data)
                cur.execute(f"UPDATE rent_clients SET {sets} WHERE id=?;", list(data.values()) + [cid])
            else:
                cols = ", ".join(data.keys())
                ph = ", ".join(["?"] * len(data))
                cur.execute(f"INSERT INTO rent_clients ({cols}) VALUES ({ph});", list(data.values()))
            conn.commit()
            msg = "Sačuvano."
        elif action == "delete":
            cid = request.form.get("client_id", type=int)
            cur.execute("DELETE FROM rent_clients WHERE id=?;", (cid,))
            conn.commit()
            msg = "Obrisano."
        conn.close()
        return redirect(url_for("rent.list_clients"))

    if edit_id:
        cur.execute("SELECT * FROM rent_clients WHERE id=?;", (edit_id,))
        edit_client = cur.fetchone()

    cur.execute("SELECT * FROM rent_clients ORDER BY name;")
    clients = cur.fetchall()
    conn.close()
    return render_template("rent/rent_clients.html", clients=clients, edit_client=edit_client, msg=msg)


# ─── Equipment CRUD ────────────────────────────────────────────────────────────
@bp.route("/equipment", methods=["GET", "POST"])
def list_equipment():
    conn = get_db()
    cur = conn.cursor()
    msg = None
    edit_eq = None
    edit_id = request.args.get("edit_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "save":
            data = {
                "name": request.form.get("name", "").strip(),
                "price": float(request.form.get("price") or 0),
                "default_rent_months": int(request.form.get("default_rent_months") or 48),
                "default_guarantee_rate": float(request.form.get("default_guarantee_rate") or 5),
                "default_downpayment_percent": float(request.form.get("default_downpayment_percent") or 20),
            }
            eid = request.form.get("eq_id", type=int)
            if eid:
                sets = ", ".join(f"{k}=?" for k in data)
                cur.execute(f"UPDATE rent_equipment SET {sets} WHERE id=?;", list(data.values()) + [eid])
            else:
                cols = ", ".join(data.keys())
                ph = ", ".join(["?"] * len(data))
                cur.execute(f"INSERT INTO rent_equipment ({cols}) VALUES ({ph});", list(data.values()))
            conn.commit()
            msg = "Sačuvano."
        elif action == "delete":
            eid = request.form.get("eq_id", type=int)
            cur.execute("DELETE FROM rent_equipment WHERE id=?;", (eid,))
            conn.commit()
            msg = "Obrisano."
        conn.close()
        return redirect(url_for("rent.list_equipment"))

    if edit_id:
        cur.execute("SELECT * FROM rent_equipment WHERE id=?;", (edit_id,))
        edit_eq = cur.fetchone()

    cur.execute("SELECT * FROM rent_equipment ORDER BY name;")
    equipment = cur.fetchall()
    conn.close()
    return render_template("rent/rent_equipment.html", equipment=equipment, edit_eq=edit_eq, msg=msg)
