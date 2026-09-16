"""Deal routes (Phase 4): list, create, the thread page, hand close.

Phase 4.x adds the financial tail: issuing invoices from accepted offers,
recording payments, voiding invoices (deal_service owns the derivation).
"""
from flask import flash, redirect, render_template, request, session, url_for

from ..app import bp
from qp_crm.services import deal_service, invoice_service
from qp_crm.shared.auth import get_db


def _current_user_id():
    return session.get("user_id")


STATUS_LABELS = {
    "new": ("Novi", "status-new"),
    "offered": ("Ponuđeno", "status-offered"),
    "won": ("Dobijeno", "status-won"),
    "paid": ("Plaćeno", "status-paid"),
    "closed": ("Zatvoreno", "status-closed"),
}


@bp.route("/")
def index():
    """/deals/ landing -> the deals list (same pattern as /offer/)."""
    return redirect(url_for("deals.list_deals"))


@bp.route("/deals")
def list_deals():
    if request.args.get("clear"):
        return redirect(url_for("deals.list_deals"))
    status = request.args.get("status", "")
    search = request.args.get("search", "")
    customer_id = request.args.get("customer", type=int)
    deals = deal_service.list_deals(status=status, customer_id=customer_id,
                                    search=search)
    customers = deal_service.list_customers()
    return render_template(
        "deals/deals.html",
        deals=deals,
        status=status,
        search=search,
        customer_id=customer_id,
        customers=customers,
        status_labels=STATUS_LABELS,
    )


@bp.route("/deals/new", methods=["GET", "POST"])
def new_deal():
    """Create-a-deal form. Discipline guard (open question #7): pick
    customer, one-line title, optional site -- done in seconds."""
    customers = deal_service.list_customers()
    customer_id = request.args.get("customer", type=int)

    preselected_locations = []
    if customer_id:
        preselected_locations = deal_service.list_locations(customer_id)

    if request.method == "POST":
        ok, result = deal_service.create_deal(
            request.form.get("customer", type=int),
            request.form.get("title"),
            location_id=request.form.get("location", type=int) or None,
            owner_user_id=_current_user_id(),
            author_user_id=_current_user_id(),
        )
        if not ok:
            return render_template(
                "deals/deal_form.html",
                customers=customers,
                locations=preselected_locations,
                error=result,
                selected_customer=request.form.get("customer", type=int),
            ), 200
        return redirect(url_for("deals.view_deal", deal_id=result))

    return render_template(
        "deals/deal_form.html",
        customers=customers,
        locations=preselected_locations,
        selected_customer=customer_id,
    )


@bp.route("/deals/<int:deal_id>")
def view_deal(deal_id):
    deal, offers, events, invoices, status = deal_service.deal_with_offers(deal_id)
    if deal is None:
        return "Deal not found", 404
    locations = deal_service.list_locations(deal["customer_id"])
    # accepted offers without a live invoice -> 'Izdaj fakturu' buttons
    invoiced_offer_ids = {inv["source_offer_id"] for inv in invoices}
    invoicable = [o for o in offers if o["id"] not in invoiced_offer_ids]
    return render_template(
        "deals/deal_detail.html",
        deal=deal,
        offers=offers,
        events=events,
        invoices=invoices,
        invoicable_offers=invoicable,
        status=status,
        status_labels=STATUS_LABELS,
        locations=locations,
        event_types=deal_service.EVENT_TYPES,
    )


@bp.route("/deals/<int:deal_id>/events", methods=["POST"])
def add_event(deal_id):
    event_type = request.form.get("event_type") or "note"
    body = request.form.get("body") or ""
    ok, result = deal_service.add_event(
        deal_id, event_type, body=body,
        author_user_id=_current_user_id(),
    )
    if not ok:
        flash(result, "error")
    return redirect(url_for("deals.view_deal", deal_id=deal_id))


@bp.route("/deals/<int:deal_id>/events/<int:event_id>/delete", methods=["POST"])
def delete_event(deal_id, event_id):
    ok, result = deal_service.delete_event(deal_id, event_id)
    if not ok:
        flash(result, "error")
    return redirect(url_for("deals.view_deal", deal_id=deal_id))


@bp.route("/deals/<int:deal_id>/accept_offer/<int:offer_id>", methods=["POST"])
def accept_offer(deal_id, offer_id):
    """The acceptance tap (decision record). Status derives to won."""
    ok, message = deal_service.record_offer_accepted(
        deal_id, offer_id, author_user_id=_current_user_id())
    if not ok:
        flash(message, "error")
    else:
        flash("Offer marked as accepted.", "success")
    return redirect(url_for("deals.view_deal", deal_id=deal_id))


@bp.route("/deals/<int:deal_id>/close", methods=["POST"])
def close_deal(deal_id):
    closed = request.form.get("closed") == "1"
    ok, message = deal_service.close_deal(deal_id, closed=closed)
    if not ok:
        flash(message, "error")
    return redirect(url_for("deals.view_deal", deal_id=deal_id))


# ---------------------------------------------------------------------------
# invoices + payments (Phase 4.x)
# ---------------------------------------------------------------------------

@bp.route("/deals/<int:deal_id>/issue_invoice/<int:offer_id>", methods=["POST"])
def issue_invoice(deal_id, offer_id):
    """Issue an invoice from an accepted offer on this deal."""
    due_date = request.form.get("due_date") or None
    ok, result = invoice_service.issue_invoice_from_offer(
        deal_id, offer_id, due_date=due_date,
        author_user_id=_current_user_id())
    if not ok:
        flash(result, "error")
    else:
        inv = invoice_service.invoice_with_details(result)
        code = inv["invoice"]["code"] if inv else result
        flash(f"Faktura {code} izdata.", "success")
    return redirect(url_for("deals.view_deal", deal_id=deal_id))


@bp.route("/invoices/<int:invoice_id>/pay", methods=["POST"])
def record_payment(invoice_id):
    invoice = invoice_service.invoice_with_details(invoice_id)
    if invoice is None:
        return "Invoice not found", 404
    ok, result = invoice_service.record_payment(
        invoice_id,
        request.form.get("amount"),
        paid_at=request.form.get("paid_at") or None,
        method=request.form.get("method") or None,
        reference=request.form.get("reference") or None,
        note=request.form.get("note") or None,
        created_by_user_id=_current_user_id(),
    )
    if not ok:
        flash(result, "error")
    else:
        flash("Uplata zabeležena.", "success")
    return redirect(url_for("deals.view_deal",
                            deal_id=invoice["invoice"]["deal_id"]))


@bp.route("/invoices/<int:invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    invoice = invoice_service.invoice_with_details(invoice_id)
    if invoice is None:
        return "Invoice not found", 404
    ok, message = invoice_service.void_invoice(
        invoice_id, author_user_id=_current_user_id())
    if not ok:
        flash(message, "error")
    return redirect(url_for("deals.view_deal",
                            deal_id=invoice["invoice"]["deal_id"]))


@bp.route("/deals/<int:deal_id>/set_location", methods=["POST"])
def set_deal_location(deal_id):
    """Move the deal to another site (NULL = customer HQ)."""
    location_id = request.form.get("location", type=int) or None
    deal = deal_service.get_deal(deal_id)
    if deal is None:
        return "Deal not found", 404
    if location_id:
        location = deal_service.get_location(location_id)
        if location is None or location["customer_id"] != deal["customer_id"]:
            flash("Location does not belong to this customer.", "error")
            return redirect(url_for("deals.view_deal", deal_id=deal_id))
    conn = get_db()
    conn.execute("UPDATE deals SET location_id = ? WHERE id = ?;",
                 (location_id, deal_id))
    conn.commit()
    conn.close()
    return redirect(url_for("deals.view_deal", deal_id=deal_id))
