"""Customer + location routes (Phase 4): master data screens.

No delete anywhere: customers archive (set_customer_archived), locations
just exist (a site's history must not vanish because a sign changed).
"""
from flask import flash, redirect, render_template, request, session, url_for

from ..app import bp
from qp_crm.services import deal_service


def _current_user_id():
    return session.get("user_id")


@bp.route("/customers")
def list_customers():
    search = request.args.get("search", "")
    show_archived = request.args.get("archived") == "1"
    customers = deal_service.list_customers(
        include_archived=show_archived, search=search)
    return render_template(
        "deals/customers.html",
        customers=customers,
        search=search,
        show_archived=show_archived,
    )


@bp.route("/customers/new", methods=["GET", "POST"])
def new_customer():
    if request.method == "POST":
        ok, result = deal_service.create_customer(
            request.form.get("name"),
            pib=request.form.get("pib"),
            mb=request.form.get("mb"),
            billing_address=request.form.get("billing_address"),
            city=request.form.get("city"),
            country=request.form.get("country"),
            email=request.form.get("email"),
            phone=request.form.get("phone"),
            notes=request.form.get("notes"),
        )
        if not ok:
            return render_template("deals/customer_form.html",
                                   customer=None, error=result), 200
        flash("Customer created.", "success")
        return redirect(url_for("deals.view_customer", customer_id=result))
    return render_template("deals/customer_form.html", customer=None)


@bp.route("/customers/<int:customer_id>")
def view_customer(customer_id):
    customer = deal_service.get_customer(customer_id)
    if customer is None:
        return "Customer not found", 404
    locations = deal_service.list_locations(customer_id)
    deals = deal_service.list_deals(customer_id=customer_id)
    return render_template(
        "deals/customer_detail.html",
        customer=customer,
        locations=locations,
        deals=deals,
    )


@bp.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
def edit_customer(customer_id):
    customer = deal_service.get_customer(customer_id)
    if customer is None:
        return "Customer not found", 404
    if request.method == "POST":
        ok, result = deal_service.update_customer(
            customer_id,
            request.form.get("name"),
            pib=request.form.get("pib"),
            mb=request.form.get("mb"),
            billing_address=request.form.get("billing_address"),
            city=request.form.get("city"),
            country=request.form.get("country"),
            email=request.form.get("email"),
            phone=request.form.get("phone"),
            notes=request.form.get("notes"),
        )
        if not ok:
            return render_template("deals/customer_form.html",
                                   customer=request.form, error=result), 200
        # Archive is its own toggle on the detail page; the form does not
        # touch it (explicit set_customer_archived route below).
        flash("Customer saved.", "success")
        return redirect(url_for("deals.view_customer", customer_id=customer_id))
    return render_template("deals/customer_form.html", customer=customer)


@bp.route("/customers/<int:customer_id>/archive", methods=["POST"])
def archive_customer(customer_id):
    archive = request.form.get("archive") == "1"
    ok, message = deal_service.set_customer_archived(customer_id, archive)
    if not ok:
        flash(message, "error")
    return redirect(url_for("deals.view_customer", customer_id=customer_id))


@bp.route("/customers/<int:customer_id>/locations/new", methods=["POST"])
def create_location(customer_id):
    ok, result = deal_service.create_location(
        customer_id,
        request.form.get("name"),
        address=request.form.get("address"),
        city=request.form.get("city"),
        contact_name=request.form.get("contact_name"),
        contact_phone=request.form.get("contact_phone"),
        notes=request.form.get("notes"),
    )
    if not ok:
        flash(result, "error")
    else:
        flash("Location added.", "success")
    return redirect(url_for("deals.view_customer", customer_id=customer_id))


@bp.route("/locations/<int:location_id>/edit", methods=["POST"])
def edit_location(location_id):
    location = deal_service.get_location(location_id)
    if location is None:
        return "Location not found", 404
    ok, result = deal_service.update_location(
        location_id,
        request.form.get("name"),
        address=request.form.get("address"),
        city=request.form.get("city"),
        contact_name=request.form.get("contact_name"),
        contact_phone=request.form.get("contact_phone"),
        notes=request.form.get("notes"),
    )
    if not ok:
        flash(result, "error")
    else:
        flash("Location saved.", "success")
    return redirect(url_for("deals.view_customer",
                            customer_id=location["customer_id"]))
