import os
import sys

# Ensure shared modules can be imported
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.append(CURRENT_DIR)

from flask import Flask, render_template, send_from_directory
from werkzeug.middleware.dispatcher import DispatcherMiddleware

# Import the existing apps
# Note: These imports might trigger some initialization code, which is fine.
# We assume they have `if __name__ == "__main__":` blocks to prevent running servers.
from pricing.app import app as pricing_app, init_db as pricing_init_db, migrate_schema as pricing_migrate_schema
from offer.app import app as offer_app, init_db as offer_init_db
from admin.app import app as admin_app, init_db as admin_init_db
from shared.config import STATIC_DIR, APP_ASSETS_DIR

# Initialize the main landing app
# We explicitly set static_folder to the shared one so it can serve css/js for the landing page
# AND for the sub-apps if they generate URLs pointing to /static
app = Flask(__name__, template_folder='templates', static_folder=STATIC_DIR, static_url_path='/static')

@app.route("/")
def index():
    return render_template("landing.html")

@app.route("/app_assets/<path:filename>")
def app_assets(filename):
    return send_from_directory(APP_ASSETS_DIR, filename)

from shared.utils import _, get_current_language

# Inject translation helpers into all apps
def inject_i18n():
    lang = get_current_language()
    return dict(_=lambda text: _(text, lang), current_lang=lang)

for sub_app in [pricing_app, offer_app, admin_app, app]:
    sub_app.context_processor(inject_i18n)

# Merge the applications using DispatcherMiddleware
application = DispatcherMiddleware(app, {
    '/pricing': pricing_app,
    '/offer': offer_app,
    '/admin': admin_app
})

if __name__ == "__main__":
    from werkzeug.serving import run_simple
    
    # Run database initializations and migrations
    print("Initializing databases...")
    pricing_init_db()
    pricing_migrate_schema()
    offer_init_db()
    admin_init_db()
    
    # We use run_simple to run the WSGI application
    # This replaces app.run() for the combined app
    print("-------------------------------------------------------")
    print("Starting Merged Link QP-CRM on port 5000")
    print("Access at: http://localhost:5000")
    print("-------------------------------------------------------")
    
    # use_reloader=True allows auto-restart on code changes (like debug=True)
    # use_debugger=True enables the interactive debugger
    run_simple('0.0.0.0', 5000, application, use_reloader=True, use_debugger=True, threaded=True)
