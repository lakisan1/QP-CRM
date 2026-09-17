import os

from flask import Flask, redirect, render_template, send_from_directory, session, url_for

# Import the existing apps
# Note: These imports might trigger some initialization code, which is fine.
# We assume they have `if __name__ == "__main__":` blocks to prevent running servers.
from qp_crm.pricing.app import init_db as pricing_init_db, migrate_schema as pricing_migrate_schema, bp as pricing_bp
from qp_crm.offer.app import init_db as offer_init_db, bp as offer_bp
from qp_crm.admin.app import init_db as admin_init_db, bp as admin_bp
from qp_crm.rent.app import init_db as rent_init_db, bp as rent_bp
from qp_crm.deals.app import init_db as deals_init_db, bp as deals_bp
from qp_crm.contacts.app import init_db as contacts_init_db, bp as contacts_bp
from qp_crm.settings.app import bp as settings_bp
from qp_crm.sale.app import bp as sale_bp
from qp_crm.pricing.api_v1 import api_v1
from qp_crm.shared.config import BASE_DIR, STATIC_DIR, APP_ASSETS_DIR

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
# template_folder must be absolute since the qp_crm/ package move: a bare
# 'templates' would resolve against qp_crm/ (this module's root_path), but the
# landing templates live at <repo root>/templates/ — anchored via BASE_DIR.
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'), static_folder=STATIC_DIR, static_url_path='/static')
app.secret_key = os.environ.get("QP_SECRET_KEY", "qp_crm_unified_secret_key_change_me")
app.config['SESSION_COOKIE_NAME'] = 'qp_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_PATH'] = '/'
# Session timeout (Phase 3 step 8): 8h sliding window. login sets
# session.permanent = True; with SESSION_REFRESH_EACH_REQUEST (default True)
# the cookie is re-issued on every response, so the 8h clock restarts on
# activity and an idle browser is logged out after 8h.
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['SESSION_REFRESH_EACH_REQUEST'] = True

# TLS / reverse-proxy posture (user decision: nginx fronts the app on its own
# port). QP_HTTPS_ONLY=1 -> Secure cookie + https scheme + HSTS + ProxyFix;
# QP_PUBLIC_DOMAIN -> advertised domain metadata (must match nginx
# server_name). Both env vars default OFF/empty, preserving today's
# plain-HTTP LAN behavior exactly (see qp_crm/shared/tls.py).
from qp_crm.shared.tls import configure_app, wrap_wsgi  # noqa: E402
configure_app(app)

# Unified login (Phase 3 step 3): ONE /login + /logout for the whole stack on
# the top-level app. The per-module login pages now redirect here (their
# bookmarks keep working); the per-module session flags are replaced by the
# session identity (user_id/username/role) that require_login/require_role
# check.
from qp_crm.auth.app import bp as auth_bp
app.register_blueprint(auth_bp)

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

# Deals module blueprint (Phase 4): the deals spine (customers, locations,
# deals threads, pipeline) at /deals, per-user grant 'deals'.
app.register_blueprint(deals_bp, url_prefix="/deals")

# Contacts module blueprint (P5-pre): the shared directory (companies AND
# persons; client/supplier/employee/external collaborator roles) at
# /contacts, per-user grant 'contacts'.
app.register_blueprint(contacts_bp, url_prefix="/contacts")

# CSRF on ALL state-changing routes (Phase 3 step 5): the settings app's
# per-session token pattern generalized into shared/web.py and wired once at
# the app level -- every POST/PUT/PATCH/DELETE on every blueprint (auth,
# settings, sale, pricing, offer, rent, admin) must carry the session token
# (form field or X-CSRF-Token header). api_v1 is exempt: it authenticates via
# the Bearer header, not ambient cookies.
from qp_crm.shared.web import check_csrf, csrf_token
app.before_request(check_csrf)

@app.route("/")
def index():
    """Landing menu. Anonymous visitors only ever see the login page
    (user request post-phase-3); logged-in users get the app cards their
    account actually opens -- staff see granted modules only, admins see
    everything plus the Admin Panel card. Sale and Settings stay public,
    so their cards show for every logged-in user."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))
    from qp_crm.shared.auth import MODULE_CHOICES, get_user_by_id, get_user_modules
    user = get_user_by_id(user_id)
    if user is None:
        # Deactivated or deleted while logged in: kill the session.
        session.clear()
        return redirect(url_for("auth.login"))
    is_admin = user["role"] == "admin"
    granted = list(MODULE_CHOICES) if is_admin else get_user_modules(user_id)
    return render_template("landing.html", is_admin=is_admin, granted=granted)

@app.route("/app_assets/<path:filename>")
def app_assets(filename):
    return send_from_directory(APP_ASSETS_DIR, filename)

from qp_crm.shared.utils import _, get_current_language

# Inject translation helpers into the whole app: every module page resolves
# `_`/current_lang from this app-level processor (previously main.py
# registered the same loop on all six sub-apps, so this preserves behavior).
def inject_i18n():
    lang = get_current_language()
    # csrf_token: available in EVERY template (Phase 3 step 5) -- the
    # settings blueprint keeps its identical local copy (same session key).
    return dict(_=lambda text: _(text, lang), current_lang=lang, csrf_token=csrf_token)

app.context_processor(inject_i18n)

# Theme: ONE app-level injection point for the per-browser 'theme' cookie
# (default 'dark', set for 1y on /settings). get_theme() reads the cookie
# directly, so it works for pre-login pages (auth/login) and for every
# blueprint that renders its own templates (offer had no processor of its
# own, which left /offer screens stuck on the dark fallback). The module
# blueprints that still register their own processor keep injecting the
# same value -- harmless, identical cookie read.
def inject_theme():
    return dict(theme=get_theme())

app.context_processor(inject_theme)

# App-wide template filters (Phase 2 stage 2): one shared 'format_date'
# (offer's superset signature: fmt optional, falls back to the stored
# date-format preference) and one shared 'md' (pricing/offer copies were
# identical). Previously each app registered its own copy on its own env.
from qp_crm.shared.web import format_date_filter, get_theme, render_markdown
app.add_template_filter(format_date_filter, 'format_date')
app.add_template_filter(render_markdown, 'md')

# The WSGI callable is now the single Flask app itself — wrapped in
# ProxyFix when QP_HTTPS_ONLY=1 (see qp_crm/shared/tls.py).
application = wrap_wsgi(app)

if __name__ == "__main__":
    from werkzeug.serving import run_simple

    # Run database initializations and migrations
    print("Initializing databases...")
    pricing_init_db()
    pricing_migrate_schema()
    offer_init_db()
    admin_init_db()
    rent_init_db()
    deals_init_db()
    contacts_init_db()

    # We use run_simple to run the WSGI application
    # This replaces app.run() for the combined app
    print("-------------------------------------------------------")
    print("Starting Merged Link QP-CRM on port 5000")
    print("Access at: http://localhost:5000")
    print("-------------------------------------------------------")

    # use_reloader=True allows auto-restart on code changes (like debug=True)
    # use_debugger=True enables the interactive debugger
    run_simple('0.0.0.0', 5000, application, use_reloader=True, use_debugger=True, threaded=True)
