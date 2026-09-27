"""Orders core routes (P5-UI rework batch B): list, detail, new, receive,
cancel + the 'what to order' board.

Role split (user request 2026-09-27): this app belongs to the person who
ORDERS — the warehouse operator's intake screen updates stock on its own
when lines are received here.
"""
from flask import flash, redirect, render_template, request, session, url_for

from ..app import bp
from qp_crm.services import order_service as orders
from qp_crm.services import warehouse_service as wh
from qp_crm.shared.schema import ORDER_STATUS_VALUES


def _lines_from_form():
    """The dynamic line rows of the new-PO form: line_qty[] with parallel
    line_product[] / line_name[] / line_shortfall[] inputs."""
    qtys = request.form.getlist("line_qty")
    pids = request.form.getlist("line_product")
    names = request.form.getlist("line_name")
    shorts = request.form.getlist("line_shortfall")
    lines = []
    for qty, pid, name, short in zip(qtys, pids, names, shorts):
        if not (qty or "").strip():
            continue
        lines.append({
            "product_id": int(pid) if (pid or "").strip() else None,
            "name_snapshot": name or None,
            "qty": qty,
            "shortfall_id": int(short) if (short or "").strip() else None,
        })
    return lines


@bp.route("/")
def index():
    return redirect(url_for("orders.orders_list"))


@bp.route("/list")
def orders_list():
    active_only = request.args.get("all") != "1"
    status = request.args.get("status") or None
    return render_template(
        "orders/list.html",
        orders=orders.list_orders(status=status, active_only=active_only),
        statuses=ORDER_STATUS_VALUES,
        active_only=active_only,
        selected_status=status,
    )


@bp.route("/needed")
def needed():
    """The 'what do we need to order' board: open debts + min-stock gaps."""
    return render_template("orders/needed.html", data=orders.open_shortfalls_for_ordering())


@bp.route("/new", methods=("GET", "POST"))
def order_new():
    shortfall_id = request.args.get("shortfall", type=int)
    if request.method == "POST":
        ok, result = orders.create_order(
            supplier_name=request.form.get("supplier_name"),
            lines=_lines_from_form(),
            expected_at=request.form.get("expected_at") or None,
            note=request.form.get("note"),
            created_by=session.get("user_id"),
        )
        if ok:
            flash("Narudžbina je kreirana.", "success")
            return redirect(url_for("orders.order_detail", po_id=result))
        flash(result, "error")
    # Ceo katalog (user request 2026-09-27): i nepraćeni proizvodi se
    # mogu naručiti — name_snapshot nosi naziv ako proizvod kasnije nestane.
    products = wh.catalog_products()
    shortfall = None
    if shortfall_id:
        all_short = wh.list_shortfalls()
        shortfall = next((s for s in all_short if s["id"] == shortfall_id), None)
    return render_template(
        "orders/order_form.html",
        products=products,
        shortfall=shortfall,
    )


@bp.route("/<int:po_id>")
def order_detail(po_id):
    order = orders.get_order(po_id)
    if order is None:
        flash("Narudžbina ne postoji.", "error")
        return redirect(url_for("orders.orders_list"))
    return render_template("orders/order_detail.html", order=order)


@bp.route("/<int:po_id>/cancel", methods=("POST",))
def order_cancel(po_id):
    ok, message = orders.cancel_order(po_id)
    if ok:
        flash("Narudžbina je otkazana.", "success")
    else:
        flash(message, "error")
    return redirect(url_for("orders.order_detail", po_id=po_id))


@bp.route("/lines/<int:line_id>/receive", methods=("POST",))
def line_receive(line_id):
    ok, result = orders.receive_line(line_id, received_by=session.get("user_id"))
    if ok:
        flash("Stavka je primljena — zaliha je automatski povećana.", "success")
    else:
        flash(result, "error")
    po_id = request.form.get("po_id", type=int)
    return redirect(url_for("orders.order_detail", po_id=po_id))
