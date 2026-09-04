"""Offer core routes: landing, login/logout, NBS rate endpoint, asset serving."""
from flask import jsonify, redirect, request, send_from_directory, url_for

from ..app import bp, APP_ASSETS_DIR, get_nbs_rate


@bp.route("/api/nbs_eur_rate")
def api_nbs_eur_rate():
    rate = get_nbs_rate("eur")
    if rate is None:
        return jsonify({"success": False, "message": "Neuspešno preuzimanje kursa sa NBS."}), 500
    return jsonify({"success": True, "rate": rate})

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
