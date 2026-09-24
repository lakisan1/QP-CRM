"""Directory routes (P5-pre): list, add/edit, detail, archive, locations.

No delete anywhere: contacts archive (set_contact_archived) -- documents
that reference a contact keep resolving it by id (rename-safe, amendment
6b). Role and kind filters come from the fixed schema lists.
"""
from flask import flash, redirect, render_template, request, url_for

from ..app import bp
from qp_crm.services import contact_service
from qp_crm.shared.countries import get_country_list
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
        "postal_code": request.form.get("postal_code"),
        "country": request.form.get("country"),
        "email": request.form.get("email"),
        "phone": request.form.get("phone"),
        "job_title": request.form.get("job_title"),
        "notes": request.form.get("notes"),
    }


def _form_roles():
    """Checked role boxes (unknown values ignored by the service)."""
    return request.form.getlist("roles")


@bp.route("/")
def index():
    return redirect(url_for("contacts.list_contacts"))


@bp.route("/contacts")
def list_contacts():
    search = request.args.get("search", "")
    show_archived = request.args.get("archived") == "1"
    kind = request.args.get("kind") or None
    role = request.args.get("role") or None
    country = request.args.get("country") or None
    roles = [role] if role in CONTACT_ROLES else None
    # Pagination (2026-09-24 user request): the 2000+ contact list renders
    # one page at a time -- same model as the offer list, page size from
    # the shared 'default_items_per_page' setting (Settings app). An
    # out-of-range page (stale ?page= after a delete or filter change)
    # clamps to the LAST page instead of rendering an empty table.
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = _items_per_page()
    contacts, total_count = contact_service.list_contacts(
        include_archived=show_archived, search=search, roles=roles, kind=kind,
        country=country, page=page, per_page=per_page)
    import math
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 1
    if page > total_pages:
        return redirect(url_for("contacts.list_contacts", page=total_pages,
                                search=search, kind=kind, role=role,
                                country=country,
                                archived=(1 if show_archived else 0)))
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
        country=country or "",
        countries=get_country_list(),
        kinds=CONTACT_KINDS,
        all_roles=CONTACT_ROLES,
        current_page=page,
        total_pages=total_pages,
        total_count=total_count,
    )


def _items_per_page():
    """Shared page size (Settings -> default_items_per_page), offer-list
    fallback of 25 when the setting is absent or unparsable."""
    from qp_crm.shared.auth import get_db
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM global_settings WHERE key = 'default_items_per_page';"
    ).fetchone()
    conn.close()
    try:
        return max(int(row["value"]), 1) if row else 25
    except (ValueError, TypeError):
        return 25


def _safe_return_to():
    """Validated ?return_to= target (musterija-first flow, P5-unification).

    Only same-site absolute paths under /offer or /rent are accepted --
    the two picker consumers -- so the param cannot smuggle an open
    redirect (same discipline as shared.web.safe_next_url). The create
    form re-submits the value as a hidden field, so request.values (GET
    arg or POST field) carries the return target through the round-trip.
    """
    candidate = request.values.get("return_to") or ""
    if (candidate.startswith("/offer/") or candidate.startswith("/rent/")) \
            and not candidate.startswith("//"):
        return candidate
    return None


@bp.route("/contacts/new", methods=["GET", "POST"])
def new_contact():
    return_to = _safe_return_to()
    if request.method == "POST":
        ok, result = contact_service.create_contact(
            request.form.get("display_name"),
            kind=request.form.get("kind", "company"),
            roles=_form_roles(),
            fields=_form_fields(),
        )
        if not ok:
            return render_template("contacts/form.html",
                                   contact=None, error=result,
                                   countries=get_country_list(),
                                   return_to=return_to), 200
        flash("Kontakt sačuvan.", "success")
        # Musterija-first flow: when the user came from a document form
        # (Ponude/Rent 'Dodaj novu musteriju'), land back there with the
        # new party already selected -- the document form pre-fills the
        # musterija fields from ?contact_id (offers) / picker autofill
        # (rent). Without return_to the normal directory detail follows.
        if return_to:
            separator = "&" if "?" in return_to else "?"
            return redirect(f"{return_to}{separator}contact_id={result}")
        return redirect(url_for("contacts.view_contact", contact_id=result))
    return render_template(
        "contacts/form.html",
        contact=None,
        countries=get_country_list(),
        return_to=return_to,
    )


@bp.route("/contacts/<int:contact_id>")
def view_contact(contact_id):
    contact = contact_service.get_contact(contact_id)
    if contact is None:
        return "Kontakt nije pronađen.", 404
    locations = contact_service.list_contact_locations(contact_id)
    documents = contact_service.linked_documents(contact_id)
    # login username for the account link (read-only display here; the
    # link itself is managed in Admin -> Users -> 'Kontakt u imeniku')
    linked_username = None
    if contact["user_id"]:
        from qp_crm.shared.auth import get_user_by_id
        linked_user = get_user_by_id(contact["user_id"])
        linked_username = linked_user["username"] if linked_user else None
    return render_template(
        "contacts/detail.html",
        contact=contact,
        locations=locations,
        documents=documents,
        linked_username=linked_username,
        countries=get_country_list(),
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
                                   contact=contact, error=result,
                                   countries=get_country_list()), 200
        # Archive is its own toggle on the detail page; the form does not
        # touch it (explicit archive route below).
        flash("Kontakt sačuvan.", "success")
        return redirect(url_for("contacts.view_contact", contact_id=contact_id))
    return render_template(
        "contacts/form.html",
        contact=contact,
        countries=get_country_list(),
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
        postal_code=request.form.get("postal_code"),
        country=request.form.get("country"),
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
        postal_code=request.form.get("postal_code"),
        country=request.form.get("country"),
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
