"""Unified authentication blueprint (Phase 3 step 3).

ONE login for the whole stack, mounted on the top-level app at /login and
/logout: previously each module had its own password gate, login page and
session flag. The per-app login URLs (/pricing/login, /offer/login,
/rent/login, /admin/login) remain reachable as redirects to the unified
login so existing bookmarks do not break (the redirects live in each
module's routes/core.py).

Session shape after login (ONE shared qp_session cookie, path=/):
    user_id, username, role            -- the authenticated identity
    (per-module *_authenticated flags are gone -- role gates, Phase 3 step 4;
     the old must_change_password session flag is gone too -- password
     changes live exclusively in Admin -> Users)

Session fixation protection: session.clear() BEFORE the identity is written
(new session id material on every login).
"""

from flask import Blueprint, Flask, redirect, render_template, request, session, url_for

from qp_crm.shared.auth import (
    attempt_login,
    clear_login_failures,
    is_login_locked,
    log_login_attempt,
    register_login_failure,
)
from qp_crm.shared.config import STATIC_DIR
from qp_crm.shared.web import safe_next_url

bp = Blueprint("auth", __name__, template_folder="templates")


@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = request.remote_addr or "unknown"

        # In-process lockout (Phase 3 step 8): after too many failures for
        # this (ip, username) pair, the password is not even checked.
        locked, remaining = is_login_locked(username, ip)
        if locked:
            log_login_attempt(username, ip, False,
                              f"lockout: {remaining}s remaining")
            error = (f"Previše neuspelih pokušaja. Pokušajte ponovo za "
                     f"{max(remaining // 60 + 1, 1)} min.")
            return render_template("auth/login.html", error=error)

        user = attempt_login(username, password)
        if user:
            clear_login_failures(username, ip)
            log_login_attempt(username, ip, True, "ok")
            # Session cycling: invalidate any pre-authentication session
            # state, then establish the new identity (fixation defence).
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            # Sliding 8h session: PERMANENT_SESSION_LIFETIME + refresh on
            # every request keeps the cookie alive while the user works.
            session.permanent = True
            dest = safe_next_url()
            return redirect(dest or "/")
        register_login_failure(username, ip)
        log_login_attempt(username, ip, False, "bad credentials")
        error = "Pogrešno korisničko ime ili lozinka"
    return render_template("auth/login.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


# NOTE: the old self-service /change-password page is REMOVED (user request:
# password changes live exclusively in Admin -> Users, where an admin sets a
# user's new password via the save form's optional 'New password' field).
# The users.must_change_password column still exists but is no longer read
# anywhere; the admin save route keeps it at 0.


if __name__ == "__main__":
    # Standalone dev run (python -m qp_crm.auth.app).
    standalone = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    standalone.register_blueprint(bp)
    standalone.secret_key = "qp_crm_unified_secret_key_change_me"
    standalone.run(port=5007, debug=True)
