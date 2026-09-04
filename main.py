import os

from flask import Flask, render_template, send_from_directory
from werkzeug.middleware.dispatcher import DispatcherMiddleware

# Import the existing apps
# Note: These imports might trigger some initialization code, which is fine.
# We assume they have `if __name__ == "__main__":` blocks to prevent running servers.
from pricing.app import app as pricing_app, init_db as pricing_init_db, migrate_schema as pricing_migrate_schema
from offer.app import app as offer_app, init_db as offer_init_db
from admin.app import app as admin_app, init_db as admin_init_db
from sale.app import app as sale_app
from rent.app import app as rent_app, init_db as rent_init_db
from settings.app import bp as settings_bp
from pricing.api_v1 import api_v1
from shared.config import STATIC_DIR, APP_ASSETS_DIR

# ---------------------------------------------------------------------------
# Phase 2 consolidation: ONE Flask application.
#
# The landing page, /static, the API v1 blueprint and the module blueprints
# live on this single app; the remaining classic sub-apps are still merged
# with DispatcherMiddleware until their blueprint migration lands
# (settings is the pilot module). URL prefixes are preserved exactly:
# /pricing /sale /offer /admin /rent stay DispatcherMiddleware mounts and
# /settings is served by the settings blueprint registered below.
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

@app.route("/")
def index():
    return render_template("landing.html")

@app.route("/app_assets/<path:filename>")
def app_assets(filename):
    return send_from_directory(APP_ASSETS_DIR, filename)

from shared.utils import _, get_current_language

# Inject translation helpers into the app (all module pages render through
# this app once their blueprint lands; the classic sub-apps keep their own
# copies until they are ported).
def inject_i18n():
    lang = get_current_language()
    return dict(_=lambda text: _(text, lang), current_lang=lang)

app.context_processor(inject_i18n)

# The classic sub-apps still mounted via DispatcherMiddleware keep receiving
# the i18n helpers on their own Flask instances (as before this refactor) --
# their templates resolve `_`/current_lang from their app's processors, not
# from the new top-level app. This loop shrinks with every blueprint port.
for _sub_app in (pricing_app, sale_app, offer_app, admin_app, rent_app):
    _sub_app.context_processor(inject_i18n)

# Merge the not-yet-ported classic sub-apps using DispatcherMiddleware.
# This mapping shrinks with every blueprint migration and disappears with
# the admin port (last module).
application = DispatcherMiddleware(app, {
    '/pricing': pricing_app,
    '/sale': sale_app,
    '/offer': offer_app,
    '/admin': admin_app,
    '/rent': rent_app
})

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
