"""Offer core routes: landing, login/logout, NBS rate endpoint, asset serving."""
from flask import jsonify, redirect, render_template, request, send_from_directory, session, url_for

from ..app import bp, APP_ASSETS_DIR, check_password, get_nbs_rate


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
    error = None
    if request.method == "POST":
        if check_password("offer", request.form.get("password")):
            session["offer_authenticated"] = True
            return redirect(url_for('offer.index'))
        else:
            error = "Pogrešna lozinka"
    return render_template("offer/login.html", error=error)

@bp.route("/logout")
def logout():
    session.pop('authenticated', None)
    return redirect('/')
