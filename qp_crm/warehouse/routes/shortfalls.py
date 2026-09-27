"""Shortfall routes (P5): donor-part debts.

Created from the machine's detail page (user answer 2026-09-25: on the
equipment page); close never deletes. PO reference is free text (POs are
a deferred batch).
"""
from flask import flash, redirect, request, url_for

from ..app import bp
from qp_crm.services import warehouse_service as wh


@bp.route("/shortfalls", methods=("POST",))
def shortfall_create():
    equipment_id = request.form.get("equipment_id", type=int)
    ok, result = wh.create_shortfall(
        equipment_id,
        part_product_id=request.form.get("part_product_id", type=int) or None,
        part_name=request.form.get("part_name"),
        po_ref=request.form.get("po_ref"),
        note=request.form.get("note"),
    )
    if ok:
        flash("Nedostajući deo je zabeležen.", "success")
    else:
        flash(result, "error")
    return redirect(url_for("warehouse.equipment_detail", equipment_id=equipment_id))


@bp.route("/shortfalls/<int:shortfall_id>/close", methods=("POST",))
def shortfall_close(shortfall_id):
    ok, message = wh.close_shortfall(shortfall_id)
    if ok:
        flash("Nedostatak je zatvoren.", "success")
    else:
        flash(message, "error")
    return redirect(request.referrer or url_for("warehouse.equipment_list"))
