"""Core pricing routes: NBS rate API, index, login and logout."""

from flask import jsonify, redirect, render_template, request, session, url_for

from ..app import bp, check_password, get_nbs_rate

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
    error = None
    if request.method == "POST":
        if check_password("pricing", request.form.get("password")):
            session["pricing_authenticated"] = True
            return redirect(url_for('pricing.index'))
        else:
            error = "Pogrešna lozinka"
    return render_template("pricing/login.html", error=error)

@bp.route("/logout")
def logout():
    session.pop('authenticated', None)
    return redirect('/')
