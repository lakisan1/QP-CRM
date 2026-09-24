"""Rent catalogs: the equipment catalog lives INSIDE the contract form
(2026-09-24 user request) — the standalone /rent/equipment page is gone.
Clients were already moved to the shared directory (P5-unification).
"""
from flask import redirect, render_template, request, url_for

from ..app import bp, get_db


# ─── Clients (P5-unification: REDIRECT to the shared directory) ────────────────
@bp.route("/clients", methods=["GET", "POST"])
def list_clients():
    """Legacy /rent/clients URL: the klient base moved to the shared
    directory (Zajednički imenik, per-user grant 'contacts').

    GET  -> redirect to /contacts/contacts?role=client (the directory
            filtered to the renter role).
    POST -> legacy form/bookmark submissions are translated: the old
            rent_clients columns map onto directory fields and the entry
            is created/updated there (role=client), then the user lands
            back in the directory. No legacy row is written anymore.
    """
    if request.method == "POST":
        from qp_crm.services import contact_service

        action = request.form.get("action")
        cid = request.form.get("client_id", type=int)
        if action == "delete" and cid:
            # The old delete button archived instead -- the directory has
            # no delete path (blueprint §4 rule 5).
            contact_service.set_contact_archived(cid, True)
        elif action == "save":
            display_name = request.form.get("name", "").strip()
            fields = {
                "mb": request.form.get("mb"),
                "pib": request.form.get("pib"),
                "account": request.form.get("account"),
                "billing_address": request.form.get("address"),
                "job_title": request.form.get("representative"),
                "email": request.form.get("email"),
            }
            if display_name:
                if cid:
                    contact_service.update_contact(
                        cid, display_name, kind="company",
                        roles=["client"], fields=fields)
                else:
                    contact_service.create_contact(
                        display_name, kind="company",
                        roles=["client"], fields=fields)
        return redirect(url_for("contacts.list_contacts", role="client"))

    return redirect(url_for("contacts.list_contacts", role="client"))


# ─── Legacy /equipment URL: page removed (R-T4) ───────────────────────────────
@bp.route("/equipment", methods=["GET", "POST"])
def list_equipment():
    """The standalone equipment page is gone: the catalog is created/edited
    inline in the contract form (section 4. Oprema). Old bookmarks and the
    old header link land back on the contracts list."""
    return redirect(url_for("rent.list_contracts"))
