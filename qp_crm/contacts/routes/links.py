"""Contact ↔ customer/location link routes (P5-pre).

A directory entry may be attached to P4 customers/customer_locations rows
(the deal spine) -- e.g. the on-site contact person of a workshop. Links
are additive facts; they are removed by unticking is_primary/using the
delete checkbox, but the CONTACT itself is only ever archived.
"""
from flask import flash, redirect, request, url_for

from ..app import bp
from qp_crm.services import contact_service


@bp.route("/contacts/<int:contact_id>/links/new", methods=["POST"])
def create_link(contact_id):
    ok, result = contact_service.create_link(
        contact_id,
        customer_id=request.form.get("customer_id", type=int),
        location_id=request.form.get("location_id", type=int),
        relation=request.form.get("relation"),
        is_primary=request.form.get("is_primary") == "1",
        notes=request.form.get("notes"),
    )
    if not ok:
        flash(result, "error")
    else:
        flash("Veza sačuvana.", "success")
    return redirect(url_for("contacts.view_contact", contact_id=contact_id))


@bp.route("/contacts/<int:contact_id>/links/<int:link_id>/delete", methods=["POST"])
def delete_link(contact_id, link_id):
    ok, message = contact_service.delete_link(contact_id, link_id)
    if not ok:
        flash(message, "error")
    else:
        flash("Veza obrisana.", "success")
    return redirect(url_for("contacts.view_contact", contact_id=contact_id))
