"""Coverage + reservations routes (P5): the ATP view and the reservation
ledger. Reservations always carry for_whom (free text — the deals spine
is gone); release never deletes.
"""
from flask import flash, redirect, render_template, request, url_for

from ..app import bp
from qp_crm.services import warehouse_service as wh


@bp.route("/coverage")
def coverage():
    """Per tracked product: on hand / reserved / available (qty) or
    warehouse instance count (serialized)."""
    return render_template(
        "warehouse/coverage.html",
        rows=wh.coverage_rows(),
    )


@bp.route("/reservations")
def reservations_list():
    active_only = request.args.get("all") != "1"
    reservations = wh.list_reservations(active_only=active_only)
    return render_template(
        "warehouse/reservations_list.html",
        reservations=reservations,
        active_only=active_only,
    )


@bp.route("/reservations/new", methods=("GET", "POST"))
def reservation_new():
    if request.method == "POST":
        ok, result = wh.create_reservation(
            product_id=request.form.get("product_id", type=int) or None,
            equipment_id=request.form.get("equipment_id", type=int) or None,
            qty=request.form.get("qty", type=float),
            for_whom=request.form.get("for_whom"),
            note=request.form.get("note"),
        )
        if ok:
            flash("Rezervacija je kreirana.", "success")
            return redirect(url_for("warehouse.reservations_list"))
        flash(result, "error")
    return render_template(
        "warehouse/reservation_form.html",
        qty_products=wh.tracked_products("qty"),
        equipment=wh.list_equipment(),
    )


@bp.route("/reservations/<int:reservation_id>/release", methods=("POST",))
def reservation_release(reservation_id):
    ok, message = wh.release_reservation(reservation_id)
    if ok:
        flash("Rezervacija je oslobođena.", "success")
    else:
        flash(message, "error")
    return redirect(url_for("warehouse.reservations_list"))
