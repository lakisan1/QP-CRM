"""Equipment registry routes (P5): list, register, detail, transition.

Transitions only — no delete (rows live forever; exit = scrap). The
detail page is the machine's whole story: custody, movements, open
shortfalls, reservations.
"""
from flask import flash, redirect, render_template, request, session, url_for

from ..app import bp
from qp_crm.services import contact_service, warehouse_service as wh
from qp_crm.shared.schema import (
    CUSTODIAN_TYPES,
    EQUIPMENT_STATUS_LABELS,
    EQUIPMENT_STATUS_VALUES,
)


def _product_choices():
    """Catalog products a machine can attach to (any regime, incl.
    untracked — a machine registered for an untracked product is just
    custody, no ledger)."""
    from qp_crm.shared.db import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name FROM products ORDER BY name;").fetchall()
    conn.close()
    return rows


@bp.route("/equipment")
def equipment_list():
    status = request.args.get("status") or None
    custodian_type = request.args.get("custodian") or None
    search = request.args.get("search", "")
    equipment = wh.list_equipment(status=status, custodian_type=custodian_type,
                                  search=search)
    return render_template(
        "warehouse/equipment_list.html",
        equipment=equipment,
        statuses=EQUIPMENT_STATUS_VALUES,
        status_labels=EQUIPMENT_STATUS_LABELS,
        custodian_types=CUSTODIAN_TYPES,
        custodian_labels={"warehouse": "Magacin", "customer": "Kod kontakta",
                          "scrap": "Rashodovano"},
        selected_status=status,
        selected_custodian=custodian_type,
        search=search,
    )


@bp.route("/equipment/new", methods=("GET", "POST"))
def equipment_new():
    if request.method == "POST":
        ok, result = wh.register_equipment(
            product_id=request.form.get("product_id", type=int),
            name_snapshot=request.form.get("name_snapshot"),
            serial_number=request.form.get("serial_number"),
            custodian_type=request.form.get("custodian_type", "warehouse"),
            custodian_contact_id=request.form.get("custodian_contact_id", type=int),
            since_date=request.form.get("since_date") or None,
            status=request.form.get("status", "in_stock"),
            notes=request.form.get("notes"),
            registered_by=session.get("user_id"),
        )
        if ok:
            flash("Mašina je registrovana.", "success")
            return redirect(url_for("warehouse.equipment_detail", equipment_id=result))
        flash(result, "error")
    products = _product_choices()
    return render_template(
        "warehouse/equipment_form.html",
        products=products,
        custodian_types=CUSTODIAN_TYPES,
        custodian_labels={"warehouse": "Magacin", "customer": "Kod kontakta",
                          "scrap": "Rashodovano"},
        statuses=EQUIPMENT_STATUS_VALUES,
        status_labels=EQUIPMENT_STATUS_LABELS,
        contacts=contact_service.list_contacts(),
        equipment=None,
    )


@bp.route("/equipment/<int:equipment_id>")
def equipment_detail(equipment_id):
    equipment = wh.get_equipment(equipment_id)
    if equipment is None:
        flash("Oprema ne postoji.", "error")
        return redirect(url_for("warehouse.equipment_list"))
    return render_template(
        "warehouse/equipment_detail.html",
        equipment=equipment,
        movements=wh.equipment_history(equipment_id),
        shortfalls=wh.list_shortfalls(equipment_id=equipment_id),
        open_shortfalls=wh.open_shortfall_count(equipment_id),
        status_labels=EQUIPMENT_STATUS_LABELS,
        contacts=contact_service.list_contacts(),
        products=_product_choices(),
        custodian_types=CUSTODIAN_TYPES,
    )


@bp.route("/equipment/<int:equipment_id>/transition", methods=("POST",))
def equipment_transition(equipment_id):
    ok, result = wh.transition_equipment(
        equipment_id,
        custodian_type=request.form.get("custodian_type"),
        custodian_contact_id=request.form.get("custodian_contact_id", type=int),
        status=request.form.get("status") or None,
        note=request.form.get("note"),
        expected_return_at=request.form.get("expected_return_at") or None,
        moved_by=session.get("user_id"),
    )
    if ok:
        flash("Custody changed — kretanje je zabeleženo.", "success")
    else:
        flash(result, "error")
    return redirect(url_for("warehouse.equipment_detail", equipment_id=equipment_id))
