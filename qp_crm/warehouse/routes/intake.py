"""Unified intake/outtake route (P5-UI rework, user request 2026-09-27).

One screen for the whole truck: pick direction, pick product, and the
form adapts — serialized products get one serial-number input per unit
(with the known-serial indicator: 'already in the system at X'), qty
products get a plain amount. 'Zabeleži i dodaj još' re-posts the form
keeping direction/reason/contact so a delivery of five lines is five
quick submissions.
"""
import json

from flask import flash, redirect, render_template, request, session, url_for

from ..app import bp
from qp_crm.services import warehouse_service as wh
from qp_crm.shared.schema import MOVEMENT_REASON_VALUES, MOVEMENT_REASON_LABELS

# Intake reasons a warehouse operator can meaningfully choose on the
# unified form (the closed set filtered to in-flow ones).
INTAKE_REASONS = ("purchase_in", "return", "service_in")
# Out-flow is the user's four-word vocabulary (2026-09-27): the operator
# does NOT know why stock leaves — commercial nuance (free issue vs loan
# vs demo) is the sender's business. Mapping to ledger reasons:
#   Prodaja  → sale   (custodian: customer, status delivered)
#   Revers   → return (custodian: customer, status delivered)
#   Servis   → loan   (custodian: customer/service, status loaned)
#   Rashod   → scrap  (write-off, terminal)
OUTTAKE_REASONS = ("sale", "return", "loan", "scrap")
# UI labels for the operator's four-word outtake vocabulary (the ledger
# keeps the granular MOVEMENT_REASON_LABELS; the form shows these).
OUTTAKE_REASON_LABELS = {
    "sale":   "Prodaja",
    "return": "Revers",
    "loan":   "Servis",
    "scrap":  "Rashod",
}


@bp.route("/intake", methods=("GET", "POST"))
def intake():
    # Ceo katalog u picker-u (user request 2026-09-27: 'svi uređaji iz
    # cenovnika' kao u Oprema registru); nepraćeni proizvodi se unose
    # kao količina (service tretira untracked kao qty u formama).
    products = wh.catalog_products()
    if request.method == "POST":
        direction = request.form.get("direction", "in")
        product_id = request.form.get("product_id", type=int)
        reason = request.form.get("reason")
        contact_id = request.form.get("contact_id", type=int) or None
        note = request.form.get("note")
        again = request.form.get("again") == "1"

        if direction not in ("in", "out"):
            flash("Smer mora biti 'ulaz' ili 'izlaz'.", "error")
        elif product_id is None:
            flash("Izaberi proizvod iz kataloga.", "error")
        else:
            # Kontakt se beleži SAMO kod izlaza (komu se izdaje); kod ulaza
            # UI ne pokazuje dobavljača — ako se pošalje, ignoriše se.
            contact_id = contact_id if direction == "out" else None
            if direction == "in":
                serials = request.form.getlist("serial_numbers")
                ok, result = wh.intake_inbound(
                    product_id, serial_numbers=serials,
                    qty=request.form.get("qty"), reason=reason,
                    contact_id=contact_id, note=note,
                    moved_by=session.get("user_id"))
            else:
                ok, result = wh.outtake(
                    product_id, serial_numbers=request.form.getlist("serial_numbers"),
                    qty=request.form.get("qty"), reason=reason,
                    contact_id=contact_id, note=note,
                    moved_by=session.get("user_id"))
            if ok:
                if direction == "in" and isinstance(result, dict):
                    parts = []
                    if result.get("registered"):
                        parts.append(f"registrovano {result['registered']} mašina")
                    if result.get("returned"):
                        parts.append(f"vraćeno {result['returned']} (već u sistemu)")
                    if result.get("movement_id"):
                        parts.append(f"količina +{request.form.get('qty')}")
                    flash(f"{result['product_name']}: " + ", ".join(parts) + ".",
                          "success")
                else:
                    flash("Kretanje je zabeleženo.", "success")
                if again:
                    # Re-render the form keeping WHO/WHY (same truck), but
                    # fresh product/serials. Contact is only carried for
                    # outtake (it's not asked on intake).
                    return redirect(url_for("warehouse.intake", again="1",
                                            direction=direction,
                                            reason=reason or "",
                                            contact=contact_id or ""))
                return redirect(url_for("warehouse.stock_list"))
            flash(result, "error")

    # "Zabeleži i dodaj još": carried over via query args so the operator
    # keeps direction/reason/contact without re-picking them.
    keep_direction = request.args.get("direction") or "in"
    keep_reason = request.args.get("reason") or ""
    keep_contact = request.args.get("contact", type=int)
    return render_template(
        "warehouse/intake.html",
        products=products,
        products_payload=json.dumps(
            [{"id": p["id"], "name": p["name"],
              "regime": p["effective_regime"]} for p in products],
            ensure_ascii=False),
        reasons_in=INTAKE_REASONS,
        reasons_out=OUTTAKE_REASONS,
        reason_labels=MOVEMENT_REASON_LABELS,
        outtake_reason_labels=OUTTAKE_REASON_LABELS,
        contacts=wh.contact_choices(),
        selected_direction=keep_direction,
        selected_reason=keep_reason,
        selected_contact=keep_contact,
    )


@bp.route("/api/serial-lookup")
def serial_lookup():
    """Known-serial indicator for the intake form (user request 5.1).

    Returns whether this serial is already registered (optionally scoped
    to one product) and where the machine is now — the form turns the
    input orange and explains 'return it vs register as new'. JSON only;
    same module grant as every warehouse page.
    """
    from flask import jsonify

    serial = (request.args.get("serial") or "").strip()
    product_id = request.args.get("product_id", type=int)
    if not serial:
        return jsonify({"found": False})
    row = wh.find_equipment_by_serial(serial, product_id=product_id)
    if row is None:
        return jsonify({"found": False})
    from qp_crm.shared.schema import EQUIPMENT_STATUS_LABELS
    custodian = (row["custodian_name"] or row["custodian_type"]) \
        if row["custodian_type"] == "customer" else \
        {"warehouse": "u magacinu", "scrap": "rashodovana"}.get(
            row["custodian_type"], row["custodian_type"])
    where = f"{custodian} ({EQUIPMENT_STATUS_LABELS.get(row['status'], row['status'])})"
    return jsonify({
        "found": True,
        "serial": row["serial_number"],
        "equipment_id": row["id"],
        "product_name": row["product_name"],
        "where": where,
        "since": row["since_date"],
    })


@bp.route("/stock")
def stock_list():
    """One list for the warehouse operator (P5-UI rework A2).

    Per tracked product: current on-hand (ledger balance for qty, live
    instance count for serialized) + the latest ledger entries underneath.
    Everything a magacioner needs: 'what do we have, what moved last' —
    no reservations, no orders, no debts (those live with the commercial
    side: coverage + orders apps).
    """
    search = (request.args.get("search") or "").strip()
    from qp_crm.shared.schema import EQUIPMENT_STATUS_LABELS
    rows = []
    for product in wh.tracked_products():
        if search and search.lower() not in product["name"].lower():
            continue
        entry = dict(product)
        entry["status_labels"] = EQUIPMENT_STATUS_LABELS
        if product["tracking_regime"] == "qty":
            entry["on_hand"] = wh.qty_on_hand(product["id"])
            entry["machines"] = []
            entry["latest"] = wh.list_movements(product_id=product["id"], limit=5)
        else:
            entry["on_hand"] = None
            entry["machines"] = [dict(m) for m in wh.equipment_for_product(product["id"])]
            entry["latest"] = wh.list_movements(product_id=product["id"], limit=5)
        rows.append(entry)
    return render_template(
        "warehouse/stock_list.html",
        rows=rows,
        search=search,
    )
