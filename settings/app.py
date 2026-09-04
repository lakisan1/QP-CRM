import os
import secrets
import sys
from flask import Blueprint, Flask, render_template, request, make_response, redirect, session

# Ensure shared modules can be imported
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from shared.config import STATIC_DIR
from shared.utils import _, get_current_language
from shared.web import get_theme

# ---------------------------------------------------------------------------
# Phase 2 stage 1 (pilot): settings is a Blueprint on the single QP-CRM app
# instead of its own Flask instance.
#
# What moved where:
#   * Flask(...) instance, secret key, SESSION_COOKIE_* config -> the single
#     app in main.py (one session/secret/cookie for the whole stack; the
#     per-app SETTINGS_SECRET_KEY env var is no longer read).
#   * app.context_processor -> bp.context_processor (fires for /settings
#     requests only, exactly like the old per-app processor).
#   * @app.route -> @bp.route with the blueprint registered at the same
#     /settings prefix in main.py -- URLs are unchanged.
#   * template "settings.html" is namespaced as "settings/settings.html"
#     because the unified Jinja environment would otherwise resolve the
#     name collision (pricing/ and offer/ ship dead settings.html copies)
#     by blueprint registration order.
# ---------------------------------------------------------------------------

bp = Blueprint("settings", __name__, template_folder="templates")

def _csrf_token():
    """Return (and create if needed) a per-session CSRF token."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]

@bp.context_processor
def inject_helpers():
    lang = get_current_language()
    return dict(theme=get_theme(), _=lambda text: _(text, lang), current_lang=lang, csrf_token=_csrf_token())

@bp.route("/", methods=["GET", "POST"])
def settings_index():
    if request.method == "POST":
        # CSRF protection
        if request.form.get("_csrf_token") != session.get("_csrf_token"):
            return "CSRF token mismatch", 400

        theme = request.form.get("theme", "dark")
        date_format = request.form.get("date_format", "YYYY-MM-DD")

        # Redirect back to the central landing page (/)
        resp = make_response(redirect("/"))

        # Set cookies for 1 year
        max_age_seconds = 60 * 60 * 24 * 365
        resp.set_cookie(
            'theme', theme,
            max_age=max_age_seconds, path='/',
            httponly=True, samesite='Lax',
            secure=os.environ.get("SETTINGS_SECURE_COOKIES", "0") == "1"
        )
        resp.set_cookie(
            'date_format', date_format,
            max_age=max_age_seconds, path='/',
            httponly=True, samesite='Lax',
            secure=os.environ.get("SETTINGS_SECURE_COOKIES", "0") == "1"
        )

        return resp

    current_theme = request.cookies.get('theme', 'dark')
    current_date_format = request.cookies.get('date_format', 'YYYY-MM-DD')

    return render_template("settings/settings.html", current_theme=current_theme, current_date_format=current_date_format)

if __name__ == "__main__":
    # Standalone dev run (python settings/app.py) -- previously this module's
    # own Flask instance; now the blueprint mounted on a throwaway app with
    # the same URL prefix and port.
    standalone = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    standalone.register_blueprint(bp, url_prefix="/settings")
    standalone.secret_key = os.environ.get("SETTINGS_SECRET_KEY", secrets.token_hex(32))
    standalone.run(port=5006, debug=True)
