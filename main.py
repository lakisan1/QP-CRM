import os

from flask import Flask, render_template, send_from_directory

# Import the existing apps
# Note: These imports might trigger some initialization code, which is fine.
# We assume they have `if __name__ == "__main__":` blocks to prevent running servers.
from pricing.app import init_db as pricing_init_db, migrate_schema as pricing_migrate_schema, bp as pricing_bp
from offer.app import init_db as offer_init_db, bp as offer_bp
from admin.app import init_db as admin_init_db, bp as admin_bp
from rent.app import init_db as rent_init_db, bp as rent_bp
from settings.app import bp as settings_bp
from sale.app import bp as sale_bp
from pricing.api_v1 import api_v1
from shared.config import STATIC_DIR, APP_ASSETS_DIR

# ---------------------------------------------------------------------------
# Phase 2 consolidation COMPLETE: ONE Flask application, no
# DispatcherMiddleware. The landing page, /static, /app_assets, the API v1
# blueprint and all six module blueprints live on this single app with the
# URL prefixes unchanged: /pricing /offer /rent /admin /sale /settings.
#
# Session unification: previously every sub-app had its own secret key and
# its own session cookie (pricing_session, offer_session, rent_session,
# admin_session, sale_readonly_session, settings' default "session"). There
# is now ONE session cookie ("qp_session") signed with ONE secret
# (QP_SECRET_KEY). Per-module login state is kept in per-module session
# flags (pricing_authenticated, offer_authenticated, rent_authenticated,
# admin_authenticated), so logging into one module still does not unlock
# another. Existing users are logged out once when the cookie name changes
# -- expected and harmless on a LAN deployment.
# ---------------------------------------------------------------------------

# Initialize the main app
# We explicitly set static_folder to the shared one so it can serve css/js for
# the landing page AND for the module pages that generate URLs pointing to
# /static (identical to what every classic sub-app mounted before).
app = Flask(__name__, template_folder='templates', static_folder=STATIC_DIR, static_url_path='/static')
app.secret_key = os.environ.get("QP_SECRET_KEY", "qp_crm_unified_secret_key_change_me")
app.config['SESSION_COOKIE_NAME'] = 'qp_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Register API v1 blueprint on the top-level app (NOT under a module prefix)
app.register_blueprint(api_v1, url_prefix="/api/v1")

# Pilot module blueprint (Phase 2 stage 1): settings at the same /settings prefix
app.register_blueprint(settings_bp, url_prefix="/settings")

# Sale module blueprint (Phase 2 stage 1): same /sale prefix, open access
app.register_blueprint(sale_bp, url_prefix="/sale")

# Pricing module blueprint (Phase 2 stage 1): same /pricing prefix, login-gated.
# Registered BEFORE offer on purpose: both pricing and offer register an
# app-wide 'format_date' template filter, and Flask lets the last
# registration win. Offer's variant (fmt=None optional argument) is the
# superset that pricing's templates also accept; stage 2 replaces both with
# one shared filter.
app.register_blueprint(pricing_bp, url_prefix="/pricing")

# Offer module blueprint (Phase 2 stage 1): same /offer prefix, login-gated.
app.register_blueprint(offer_bp, url_prefix="/offer")

# Rent module blueprint (Phase 2 stage 1): same /rent prefix, login-gated.
app.register_blueprint(rent_bp, url_prefix="/rent")

# Admin module blueprint (Phase 2 stage 1): same /admin prefix, login-gated.
# Last module port -- DispatcherMiddleware is gone from here on.
app.register_blueprint(admin_bp, url_prefix="/admin")

@app.route("/")
def index():
    return render_template("landing.html")

@app.route("/app_assets/<path:filename>")
def app_assets(filename):
    return send_from_directory(APP_ASSETS_DIR, filename)

from shared.utils import _, get_current_language

# Inject translation helpers into the whole app: every module page resolves
# `_`/current_lang from this app-level processor (previously main.py
# registered the same loop on all six sub-apps, so this preserves behavior).
def inject_i18n():
    lang = get_current_language()
    return dict(_=lambda text: _(text, lang), current_lang=lang)

app.context_processor(inject_i18n)

# The WSGI callable is now the single Flask app itself.
application = app

if __name__ == "__main__":
    from werkzeug.serving import run_simple

    # Run database initializations and migrations
    print("Initializing databases...")
    pricing_init_db()
    pricing_migrate_schema()
    offer_init_db()
    admin_init_db()
    rent_init_db()

    # We use run_simple to run the WSGI application
    # This replaces app.run() for the combined app
    print("-------------------------------------------------------")
    print("Starting Merged Link QP-CRM on port 5000")
    print("Access at: http://localhost:5000")
    print("-------------------------------------------------------")

    # use_reloader=True allows auto-restart on code changes (like debug=True)
    # use_debugger=True enables the interactive debugger
    run_simple('0.0.0.0', 5000, application, use_reloader=True, use_debugger=True, threaded=True)
