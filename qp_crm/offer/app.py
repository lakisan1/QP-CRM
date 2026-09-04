from flask import Blueprint, Flask, render_template, request, redirect, url_for, send_from_directory, send_file, jsonify, session
import sqlite3
import os
import io
# pdfkit removed
import requests
from weasyprint import HTML, CSS
from datetime import date
from pathlib import Path

import markdown

from qp_crm.shared.config import BASE_DIR, APP_DATA_DIR, DATABASE, IMAGE_DIR, APP_ASSETS_DIR, STATIC_DIR
from qp_crm.shared.db import get_db
from qp_crm.shared.auth import check_password
from qp_crm.shared.countries import get_country_list

from qp_crm.shared.utils import format_amount, format_date, get_nbs_rate
from qp_crm.shared.web import (
    get_date_format,
    get_theme,
    make_auth_hook,
    register_product_image,
    fetch_mandatory_fields,
)
from qp_crm.services.offer_service import recalc_totals

# ---------------------------------------------------------------------------
# Phase 2 stage 1: offer is a Blueprint on the single QP-CRM app.
#
# The Flask(...) instance, secret key and SESSION_COOKIE_NAME moved to
# main.py (one session/secret/cookie; OFFER_SECRET_KEY and the offer_session
# cookie are no longer read). Routes keep the same URLs via the blueprint's
# /offer prefix in main.py. Session flag renamed 'authenticated' ->
# 'offer_authenticated': with the shared cookie, the old shared flag name
# would let an offer login unlock other modules (pricing already got its
# own flag; rent/admin had one all along). Templates live under
# offer/templates/offer/ (same-name collision safety on the unified env).
# ---------------------------------------------------------------------------

bp = Blueprint("offer", __name__, template_folder="templates")

# Per-module login hook from shared/web.py; the NBS rate endpoint stays
# publicly reachable exactly as before the consolidation.
bp.before_request(make_auth_hook(
    "offer_authenticated", "offer.login",
    exempt_endpoints=("offer.api_nbs_eur_rate",)))

def init_db():
    """Thin wrapper -- the DDL lives in shared/schema.py (single source).
    The canonical offers/offer_items definitions are the offer supersets;
    the legacy-DB ALTERs (kept idempotent) run afterwards."""
    from qp_crm.shared.schema import create_offer_tables, migrate_offer_tables

    conn = get_db()
    cur = conn.cursor()
    create_offer_tables(cur)
    migrate_offer_tables(cur)
    conn.commit()
    conn.close()


def inject_helpers():
    return dict(
        format_amount=format_amount,
        theme=get_theme(),
        enable_product_discount=get_enable_product_discount()
    )

register_product_image(bp)

def get_enable_product_discount():
    """Fetch the enable_product_discount setting."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM global_settings WHERE key = 'enable_product_discount';")
    row = cur.fetchone()
    conn.close()
    return (row["value"] == "true") if row else True

def get_mandatory_fields():
    """Fetch mandatory field settings from global_settings."""
    conn = get_db()
    cur = conn.cursor()
    settings = fetch_mandatory_fields(cur)
    conn.close()
    return settings

@bp.context_processor
def inject_helpers():
    fmt = get_date_format()
    return dict(
        format_amount=format_amount,
        format_date=lambda d: format_date(d, fmt)
    )

# Phase 2 stage 5: route groups live in offer/routes/; importing them
# registers their @bp.route functions on the blueprint defined above.
from . import routes  # noqa: E402,F401

if __name__ == "__main__":
    # Standalone dev run (python -m qp_crm.offer.app) -- previously this
    # module's own
    # Flask instance; now the blueprint mounted on a throwaway app with the
    # same URL prefix and port.
    standalone = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    standalone.register_blueprint(bp, url_prefix="/offer")
    standalone.secret_key = os.environ.get("OFFER_SECRET_KEY", "crm_offer_secret_key_change_me")
    standalone.config['SESSION_COOKIE_NAME'] = 'offer_session'
    init_db()
    standalone.run(host="0.0.0.0", debug=True, port=5001)
