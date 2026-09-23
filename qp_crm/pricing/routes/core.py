"""Core pricing routes: NBS rate API, index, login and logout."""

from flask import jsonify, redirect, url_for

from ..app import bp, get_nbs_rate

@bp.route("/api/nbs_rate/<currency>")
def api_nbs_rate(currency):
    rate = get_nbs_rate(currency)
    if rate is None:
        return jsonify({"success": False, "message": f"Neuspešno preuzimanje kursa za {currency} sa NBS."}), 500
    return jsonify({"success": True, "rate": rate})
@bp.route("/")
def index():
    return redirect(url_for("pricing.list_products"))

@bp.route("/login", methods=["GET", "POST"])
def login():
    # Phase 3: ONE unified login on the top-level app (/login). This old
    # per-app URL stays alive as a redirect so existing bookmarks work.
    return redirect(url_for("auth.login", next=url_for("pricing.index")))

@bp.route("/logout")
def logout():
    # Unified logout everywhere (Phase 3 step 3).
    return redirect(url_for("auth.logout"))
