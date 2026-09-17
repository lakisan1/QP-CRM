"""Directory routes (P5-pre): list, add/edit, detail, archive, locations.

No delete anywhere: contacts archive (set_contact_archived) -- documents
that reference a contact keep resolving it by id (rename-safe, amendment
6b). Role and kind filters come from the fixed schema lists.
"""
from flask import flash, redirect, render_template, request, url_for

from ..app import bp
from qp_crm.services import contact_service
from qp_crm.shared.schema import CONTACT_KINDS, CONTACT_ROLES


def _form_fields():
    """Whitelisted field bag from the request form (service owns defaults)."""
    return {
        "first_name": request.form.get("first_name"),
        "last_name": request.form.get("last_name"),
        "jmbg": request.form.get("jmbg"),
        "pib": request.form.get("pib"),
        "mb": request.form.get("mb"),
        "account": request.form.get("account"),
        "billing_address": request.form.get("billing_address"),
        "city": request.form.get("city"),
        "country": request.form.get("country"),
        "email": request.form.get("email"),
        "phone": request.form.get("phone"),
        "job_title": request.form.get("job_title"),
        "user_id": request.form.get("user_id", type=int),
        "notes": request.form.get("notes"),
    }


def _form_roles():
    """Checked role boxes (unknown values ignored by the service)."""
    return request.form.getlist("roles")


def _user_choices():
    """Active app login accounts (feed for the employee -> nalog link)."""
    from qp_crm.shared.auth import get_db
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, username FROM users WHERE is_active = 1 ORDER BY username;")
    rows = cur.fetchall()
    conn.close()
    return rows


@bp.route("/")
def index():
    return redirect(url_for("contacts.list_contacts"))


@bp.route("/contacts")
def list_contacts():
    search = request.args.get("search", "")
    show_archived = request.args.get("archived") == "1"
    kind = request.args.get("kind") or None
    role = request.args.get("role") or None
    roles = [role] if role in CONTACT_ROLES else None
    contacts = contact_service.list_contacts(
        include_archived=show_archived, search=search, roles=roles, kind=kind)
    # Role badges resolve in bulk (one query, not one per row).
    contacts = [dict(c) for c in contacts]
    for c in contacts:
        c["roles"] = contact_service.roles_of(c["id"])
    return render_template(
        "contacts/list.html",
        contacts=contacts,
        search=search,
        show_archived=show_archived,
        kind=kind or "",
        role=role or "",
        kinds=CONTACT_KINDS,
        all_roles=CONTACT_ROLES,
    )


@bp.route("/contacts/new", methods=["GET", "POST"])
def new_contact():
    if request.method == "POST":
        ok, result = contact_service.create_contact(
            request.form.get("display_name"),
            kind=request.form.get("kind", "company"),
            roles=_form_roles(),
            fields=_form_fields(),
        )
        if not ok:
            return render_template("contacts/form.html",
                                   contact=None, error=result), 200
        flash("Kontakt sačuvan.", "success")
        return redirect(url_for("contacts.view_contact", contact_id=result))
    return render_template(
        "contacts/form.html",
        contact=None,
        user_choices=_user_choices(),
    )


@bp.route("/contacts/<int:contact_id>")
def view_contact(contact_id):
    contact = contact_service.get_contact(contact_id)
    if contact is None:
        return "Kontakt nije pronađen.", 404
    locations = contact_service.list_contact_locations(contact_id)
    documents = contact_service.linked_documents(contact_id)
    return render_template(
        "contacts/detail.html",
        contact=contact,
        locations=locations,
        documents=documents,
    )


@bp.route("/contacts/<int:contact_id>/edit", methods=["GET", "POST"])
def edit_contact(contact_id):
    contact = contact_service.get_contact(contact_id)
    if contact is None:
        return "Kontakt nije pronađen.", 404
    if request.method == "POST":
        ok, result = contact_service.update_contact(
            contact_id,
            request.form.get("display_name"),
            kind=request.form.get("kind", "company"),
            roles=_form_roles(),
            fields=_form_fields(),
        )
        if not ok:
            contact = dict(contact)
            contact["roles"] = contact_service.roles_of(contact_id)
            return render_template("contacts/form.html",
                                   contact=contact, error=result), 200
        # Archive is its own toggle on the detail page; the form does not
        # touch it (explicit archive route below).
        flash("Kontakt sačuvan.", "success")
        return redirect(url_for("contacts.view_contact", contact_id=contact_id))
    return render_template(
        "contacts/form.html",
        contact=contact,
        user_choices=_user_choices(),
    )


@bp.route("/contacts/<int:contact_id>/archive", methods=["POST"])
def archive_contact(contact_id):
    archive = request.form.get("archive") == "1"
    ok, message = contact_service.set_contact_archived(contact_id, archive)
    if not ok:
        flash(message, "error")
    return redirect(url_for("contacts.view_contact", contact_id=contact_id))


# ---------------------------------------------------------------------------
# locations (sites of one contact)
# ---------------------------------------------------------------------------

@bp.route("/contacts/<int:contact_id>/locations/new", methods=["POST"])
def create_contact_location(contact_id):
    ok, result = contact_service.create_contact_location(
        contact_id,
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
        flash("Lokacija sačuvana.", "success")
    return redirect(url_for("contacts.view_contact", contact_id=contact_id))


@bp.route("/contacts/locations/<int:location_id>/edit", methods=["POST"])
def edit_contact_location(location_id):
    ok, message = contact_service.update_contact_location(
        location_id,
        request.form.get("name"),
        address=request.form.get("address"),
        city=request.form.get("city"),
        contact_name=request.form.get("contact_name"),
        contact_phone=request.form.get("contact_phone"),
        notes=request.form.get("notes"),
    )
    if not ok:
        flash(message, "error")
        return redirect(url_for("contacts.list_contacts"))
    from qp_crm.shared.auth import get_db
    conn = get_db()
    row = conn.execute(
        "SELECT contact_id FROM contact_locations WHERE id = ?;", (location_id,)
    ).fetchone()
    conn.close()
    if row:
        return redirect(url_for("contacts.view_contact",
                                contact_id=row["contact_id"]))
    return redirect(url_for("contacts.list_contacts"))
