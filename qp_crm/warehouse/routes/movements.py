"""Movement ledger routes (P5): list + record a movement.

The ledger list is filterable by product; the record form gates on the
product's regime (qty products get qty+direction, serialized subjects come
through equipment transitions instead).
"""
from flask import flash, redirect, render_template, request, session, url_for

from ..app import bp
from qp_crm.services import contact_service, warehouse_service as wh
from qp_crm.shared.schema import MOVEMENT_REASON_VALUES, MOVEMENT_REASON_LABELS


@bp.route("/movements")
def movements_list():
    product_id = request.args.get("product_id", type=int)
    movements = wh.list_movements(product_id=product_id)
    products = wh.tracked_products()
    return render_template(
        "warehouse/movements_list.html",
        movements=movements,
        products=products,
        selected_product=product_id,
        reason_labels=MOVEMENT_REASON_LABELS,
    )


@bp.route("/movements/new", methods=("GET", "POST"))
def movement_new():
    products = wh.tracked_products("qty")
    if request.method == "POST":
        ok, result = wh.record_movement(
            product_id=request.form.get("product_id", type=int),
            name_snapshot=request.form.get("name_snapshot"),
            qty=request.form.get("qty", type=float),
            direction=request.form.get("direction", "in"),
            reason=request.form.get("reason"),
            contact_id=request.form.get("contact_id", type=int) or None,
            note=request.form.get("note"),
            moved_by=session.get("user_id"),
        )
        if ok:
            flash("Kretanje je zabeleženo.", "success")
            return redirect(url_for("warehouse.movements_list"))
        flash(result, "error")
    return render_template(
        "warehouse/movement_form.html",
        products=products,
        reasons=MOVEMENT_REASON_VALUES,
        reason_labels=MOVEMENT_REASON_LABELS,
        contacts=contact_service.list_contacts(),
    )
