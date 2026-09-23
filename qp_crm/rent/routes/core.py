"""Rent core routes: landing redirect, login/logout."""
from flask import redirect, url_for

from ..app import bp


@bp.route("/login", methods=["GET", "POST"])
def login():
    # Phase 3: ONE unified login on the top-level app (/login); redirect
    # keeps old bookmarks alive.
    return redirect(url_for("auth.login", next=url_for("rent.index")))


@bp.route("/logout")
def logout():
    # Unified logout everywhere (Phase 3 step 3).
    return redirect(url_for("auth.logout"))


# ─── PMT helper ────────────────────────────────────────────────────────────────


@bp.route("/")
def index():
    return redirect(url_for("rent.list_contracts"))
