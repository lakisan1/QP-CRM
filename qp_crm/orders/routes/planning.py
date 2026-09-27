"""Planning routes (Komercijala, P5-UI rework): reservations + coverage.

Moved from the warehouse app (user decision 2026-09-27, variant B): the
warehouse operator only physically intakes/out-takes; RESERVING stock
for customers and watching the ATP coverage is commercial work. This
module owns the 'Komercijala' app: narudžbine + rezervacije + pokrivenost
+ pregled gde je koja mašina.
"""
from flask import flash, redirect, render_template, request, url_for

from ..app import bp
from qp_crm.services import warehouse_service as wh
from qp_crm.shared.schema import EQUIPMENT_STATUS_VALUES


@bp.route("/coverage")
def coverage():
    """Per tracked product: on hand / reserved / available (qty) or
    warehouse instance count (serialized)."""
    return render_template(
        "orders/coverage.html",
        rows=wh.coverage_rows(),
    )


@bp.route("/reservations")
def reservations_list():
    active_only = request.args.get("all") != "1"
    reservations = wh.list_reservations(active_only=active_only)
    return render_template(
        "orders/reservations_list.html",
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
            return redirect(url_for("orders.reservations_list"))
        flash(result, "error")
    return render_template(
        "orders/reservation_form.html",
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
    return redirect(url_for("orders.reservations_list"))


@bp.route("/equipment-map")
def equipment_map():
    """Where is every machine (user request, variant B): the commercialist
    answers 'koji je uređaj kod koje mušterije' without the warehouse app."""
    from qp_crm.shared.schema import EQUIPMENT_STATUS_LABELS
    status = request.args.get("status") or None
    search = request.args.get("search", "")
    equipment = wh.list_equipment(status=status, search=search)
    return render_template(
        "orders/equipment_map.html",
        equipment=equipment,
        statuses=EQUIPMENT_STATUS_VALUES,
        status_labels=EQUIPMENT_STATUS_LABELS,
        selected_status=status,
        search=search,
    )
