"""Offer core routes: landing, login/logout, NBS rate endpoint, asset serving."""
from flask import jsonify, redirect, request, send_from_directory, url_for

from ..app import bp, APP_ASSETS_DIR, get_nbs_rate

from qp_crm.services import contact_service


@bp.route("/api/nbs_eur_rate")
def api_nbs_eur_rate():
    rate = get_nbs_rate("eur")
    if rate is None:
        return jsonify({"success": False, "message": "Neuspešno preuzimanje kursa sa NBS."}), 500
    return jsonify({"success": True, "rate": rate})


@bp.route("/api/contact/<int:contact_id>")
def api_contact(contact_id):
    """Musterija autofill feed for the offer form's step-1 picker
    (musterija-first, P5-unification).

    Mirrors the rent contract form's in-place fill: the picker JS fetches
    this JSON and fills the musterija fields WITHOUT a page reload -- a
    reload on the new-offer URL would drop the param on edit pages and
    visually reset the picker (user report 2026-09-22). Snapshot fields
    stay user-editable after the fill (issuance-time snapshot rule).
    """
    contact = contact_service.get_contact(contact_id)
    if contact is None:
        return jsonify({}), 404
    full_name = " ".join(
        part for part in (contact["first_name"], contact["last_name"]) if part
    ) or contact["display_name"]
    # Site picker feed (2026-09-24 model): the contact's MAIN billing
    # address IS the default site (virtual id 0 = MAIN_LOCATION_ID); extra
    # objects come from contact_locations. The form JS fills the location
    # select from this list; picking one overwrites client_address with
    # that site's address (snapshot — saved with the offer).
    sites = contact_service.location_choices(contact_id)
    return jsonify({
        "contact_id": contact["id"],
        "name": full_name,
        "address": contact["billing_address"] or "",
        "city": contact["city"] or "",
        "postal_code": (contact["postal_code"] or "")
        if "postal_code" in contact.keys() else "",
        "email": contact["email"] or "",
        "phone": contact["phone"] or "",
        "pib": contact["pib"] or "",
        "mb": contact["mb"] or "",
        "country": contact["country"] or "",
        "sites": sites,
    })

# /product-image route: shared implementation (also on pricing and sale)

@bp.route("/asset/<path:filename>")
def app_asset(filename):
    return send_from_directory(APP_ASSETS_DIR, filename)

@bp.route("/")
def index():
    return redirect(url_for("offer.list_offers"))

@bp.route("/login", methods=["GET", "POST"])
def login():
    # Phase 3: ONE unified login on the top-level app (/login); redirect
    # keeps old bookmarks alive.
    return redirect(url_for("auth.login", next=url_for("offer.index")))

@bp.route("/logout")
def logout():
    # Unified logout everywhere (Phase 3 step 3).
    return redirect(url_for("auth.logout"))
