"""Rent catalog CRUD: equipment (clients live in the shared directory)."""
from flask import redirect, render_template, request, url_for

from ..app import bp, get_db


# ─── Clients (P5-unification: REDIRECT to the shared directory) ────────────────
@bp.route("/clients", methods=["GET", "POST"])
def list_clients():
    """Legacy /rent/clients URL: the klient base moved to the shared
    directory (Zajednički imenik, per-user grant 'contacts').

    GET  -> redirect to /contacts/contacts?role=client (the directory
            filtered to the renter role).
    POST -> legacy form/bookmark submissions are translated: the old
            rent_clients columns map onto directory fields and the entry
            is created/updated there (role=client), then the user lands
            back in the directory. No legacy row is written anymore.
    """
    if request.method == "POST":
        from qp_crm.services import contact_service

        action = request.form.get("action")
        cid = request.form.get("client_id", type=int)
        if action == "delete" and cid:
            # The old delete button archived instead -- the directory has
            # no delete path (blueprint §4 rule 5).
            contact_service.set_contact_archived(cid, True)
        elif action == "save":
            display_name = request.form.get("name", "").strip()
            fields = {
                "mb": request.form.get("mb"),
                "pib": request.form.get("pib"),
                "account": request.form.get("account"),
                "billing_address": request.form.get("address"),
                "job_title": request.form.get("representative"),
                "email": request.form.get("email"),
            }
            if display_name:
                if cid:
                    contact_service.update_contact(
                        cid, display_name, kind="company",
                        roles=["client"], fields=fields)
                else:
                    contact_service.create_contact(
                        display_name, kind="company",
                        roles=["client"], fields=fields)
        return redirect(url_for("contacts.list_contacts", role="client"))

    return redirect(url_for("contacts.list_contacts", role="client"))


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
