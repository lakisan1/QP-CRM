from flask import Blueprint, Flask, render_template, request, redirect, url_for, send_from_directory, send_file, session, jsonify
import requests
import sqlite3
import os
import sys
import re
import csv
import io
import zipfile
from PIL import Image
from datetime import date

# Base directory = the "QP-CRM" folder (parent of this app folder)
# We now use shared.config for this.
import sys
import os

# Ensure we can import 'shared' from parent dir
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

# Add custom_libs so we can import without root permissions
CUSTOM_LIBS_DIR = os.path.join(PARENT_DIR, 'custom_libs')
if CUSTOM_LIBS_DIR not in sys.path:
    sys.path.append(CUSTOM_LIBS_DIR)

import markdown

from shared.config import BASE_DIR, APP_DATA_DIR, DATABASE, IMAGE_DIR, STATIC_DIR
from shared.db import get_db
from shared.auth import check_password
from shared.web import (
    get_date_format,
    get_theme,
    make_auth_hook,
    register_product_image,
    save_product_image,
    download_image_from_url,
)

# import common_utils (it's in PARENT_DIR)
# we already added PARENT_DIR to sys.path above
from shared.utils import format_amount, format_date, get_nbs_rate
from shared.auth import get_api_key, generate_api_key
from services.pricing_service import apply_rounding

# ---------------------------------------------------------------------------
# Phase 2 stage 1: pricing is a Blueprint on the single QP-CRM app.
#
# The Flask(...) instance, secret key and SESSION_COOKIE_NAME moved to
# main.py (one session/secret/cookie for the whole stack; PRICING_SECRET_KEY
# and the pricing_session cookie are no longer read). Routes keep the same
# URLs via the blueprint's /pricing prefix in main.py; endpoints are
# namespaced (pricing.list_products, ...) in Python and templates, and
# templates live under pricing/templates/pricing/.
#
# Session flag renamed with the consolidation: the shared cookie would
# otherwise let a pricing login unlock other modules that still read the
# plain 'authenticated' flag (offer). rent/admin already used their own
# flags before the merge.
# ---------------------------------------------------------------------------

bp = Blueprint("pricing", __name__, template_folder="templates")

# Per-module login hook from shared/web.py (was a copy-pasted before_request
# per app; the session flag is pricing-specific so the shared cookie cannot
# unlock other modules).
bp.before_request(make_auth_hook("pricing_authenticated", "pricing.login"))


def init_db():
    """Thin wrapper -- the DDL lives in shared/schema.py (single source)."""
    from shared.schema import create_pricing_tables

    conn = get_db()
    cur = conn.cursor()
    create_pricing_tables(cur)
    conn.commit()
    conn.close()


def migrate_schema():
    """Thin wrapper -- the idempotent ALTERs live in shared/schema.py."""
    from shared.schema import migrate_pricing

    conn = get_db()
    cur = conn.cursor()
    migrate_pricing(cur)
    conn.commit()
    conn.close()


import requests

# /product-image route: shared implementation (also on offer and sale)
register_product_image(bp)



@bp.context_processor
def inject_helpers():
    return dict(
        format_amount=format_amount,
        theme=get_theme(),
    )

# ---------- END ----------

# Phase 2 stage 5: route groups live in pricing/routes/; importing them
# registers their @bp.route functions on the blueprint defined above.
from . import routes  # noqa: E402,F401

# Standalone dev runs now need the package form: `python -m pricing.app`
# (package-relative imports no longer work with `python pricing/app.py`).
if __name__ == "__main__":
    init_db()
    migrate_schema()

    # Auto-generate API key on first run if none exists
    existing_key = get_api_key()
    if not existing_key:
        new_key = generate_api_key()
        print(f"\n{'='*60}")
        print(f"  🔑 API v1: No API key found. Generated new key:")
        print(f"  {new_key}")
        print(f"  Manage this key in: Admin Panel → API Key Management")
        print(f"  Use: Authorization: Bearer {new_key}")
        print(f"{'='*60}\n")
    else:
        print(f"\n  🔑 API v1 key loaded. Manage in Admin Panel → API Key Management\n")

    app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    app.register_blueprint(bp, url_prefix="/pricing")
    app.secret_key = os.environ.get("PRICING_SECRET_KEY", "crm_pricing_secret_key_change_me")
    app.config['SESSION_COOKIE_NAME'] = 'pricing_session'
    app.run(host="0.0.0.0", port=5000, debug=True)
