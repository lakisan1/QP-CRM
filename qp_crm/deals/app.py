"""Deals module (Phase 4): the deals spine.

Blueprint on the single QP-CRM app, mounted at /deals by main.py — same
pattern as offer/rent/admin after Phase 2 stage 1. The module owns:

  * customers + customer_locations + deals + deal_events (schema in
    shared/schema.py, single source);
  * the deals thread UI (customers, locations, deal timeline, pipeline);
  * the derived-status read model (statuses come from deal_service, they
    are never stored and never hand-set except through document links).

Access: require_module("deals") — per-user app access like pricing/offer/
rent/sale (MODULE_CHOICES v3 in shared/auth.py); admins bypass grants.
"""
import os

from flask import Blueprint, Flask

from qp_crm.shared.config import APP_DATA_DIR, DATABASE, IMAGE_DIR, APP_ASSETS_DIR, STATIC_DIR
from qp_crm.shared.db import get_db
from qp_crm.shared.web import require_module

bp = Blueprint("deals", __name__, template_folder="templates")

# Per-user app access gate (Phase 4): staff need the 'deals' grant.
bp.before_request(require_module("deals"))


def init_db():
    """Thin wrapper -- the DDL lives in shared/schema.py (single source).

    Runs in the boot sequence after rent_init_db (see wsgi.py / main.py).
    The offers link columns are created by offer_init_db's
    migrate_offer_tables (Phase 4 edit) AND here via migrate_deals --
    both are idempotent, so boot order does not matter for correctness;
    keeping one copy inside each owner module preserves the historical
    pattern where each module's init_db upgrades what it owns.
    """
    from qp_crm.shared.schema import create_deals_tables, migrate_deals

    conn = get_db()
    cur = conn.cursor()
    create_deals_tables(cur)
    migrate_deals(cur)
    conn.commit()
    conn.close()


@bp.context_processor
def inject_helpers():
    """Template helpers every deals page expects (same set the other
    business modules inject)."""
    from qp_crm.shared.web import get_date_format, get_theme
    from qp_crm.shared.utils import format_amount, format_date

    fmt = get_date_format()
    return dict(
        format_amount=format_amount,
        format_date=lambda d: format_date(d, fmt),
        theme=get_theme(),
    )


# Phase 4: route groups live in deals/routes/; importing them registers
# their @bp.route functions on the blueprint defined above.
from . import routes  # noqa: E402,F401

if __name__ == "__main__":
    # Standalone dev run (python -m qp_crm.deals.app) -- throwaway app,
    # same as the other modules' standalone blocks.
    from flask import Flask

    standalone = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    standalone.register_blueprint(bp, url_prefix="/deals")
    standalone.secret_key = os.environ.get("DEALS_SECRET_KEY", "crm_deals_secret_key_change_me")
    standalone.config["SESSION_COOKIE_NAME"] = "deals_session"
    init_db()
    standalone.run(host="0.0.0.0", debug=True, port=5007)
