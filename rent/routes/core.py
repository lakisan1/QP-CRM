"""Rent core routes: landing redirect, login/logout."""
from flask import redirect, render_template, request, session, url_for

from ..app import bp, check_password


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if check_password("rent", request.form.get("password")):
            session['rent_authenticated'] = True
            return redirect(url_for('rent.index'))
        else:
            error = "Pogrešna lozinka"
    return render_template("rent/rent_login.html", error=error)


@bp.route("/logout")
def logout():
    session.pop('rent_authenticated', None)
    return redirect('/')


# ─── PMT helper ────────────────────────────────────────────────────────────────


@bp.route("/")
def index():
    return redirect(url_for("rent.list_contracts"))
