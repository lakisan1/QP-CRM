"""Warehouse module (P5): stock & equipment — custody, not inventory value.

Blueprint on the single QP-CRM app, mounted at /warehouse by main.py.
The module owns (schema in shared/schema.py, single source):

  * equipment          — serialized machine instances (rows live forever);
  * stock_movements    — the single movement ledger for qty + serialized;
  * reservations       — coverage loop, free-text 'for whom';
  * equipment_shortfalls — donor-part debts between machines.

The catalog stays in pricing (one `products` table): tracking is opt-in
per product via `tracking_regime` ('untracked' default — the 254 existing
products carry zero tracking burden). QP-CRM tracks CUSTODY of machines
and DEBTS between machines; the audit warehouse software stays the
counting/inventory-value truth.

Access: require_module("warehouse") — per-user app access like every
other module (MODULE_CHOICES v5 in shared/auth.py); admins bypass grants.

User answers 2026-09-25 (shape this module):
  * NO deal links — the /deals spine is gone; reservations carry a
    free-text for_whom;
  * custodian counterparty = the contacts directory (Imenik);
  * Serbian UI labels (like the rent module);
  * no fleet vans / purchase orders yet (deferred batches).
"""
import os

from flask import Blueprint

from qp_crm.shared.config import STATIC_DIR
from qp_crm.shared.db import get_db
from qp_crm.shared.web import require_module

bp = Blueprint("warehouse", __name__, template_folder="templates")

# Per-user app access gate (P5): staff need the 'warehouse' grant.
bp.before_request(require_module("warehouse"))


def init_db():
    """Thin wrapper -- the DDL lives in shared/schema.py (single source).

    Runs in the boot sequence (see wsgi.py / main.py); idempotent. The
    migrate step drops the retired rent_equipment orphan table on legacy
    DBs (R-T8 cleanup, user answer 2026-09-25).
    """
    from qp_crm.shared.schema import create_warehouse_tables, migrate_warehouse

    conn = get_db()
    cur = conn.cursor()
    create_warehouse_tables(cur)
    migrate_warehouse(cur)
    conn.commit()
    conn.close()


@bp.context_processor
def inject_helpers():
    """Template helpers every warehouse page expects."""
    from qp_crm.shared.schema import (
        EQUIPMENT_STATUS_LABELS,
        MOVEMENT_REASON_LABELS,
    )
    from qp_crm.shared.web import get_date_format, get_theme
    from qp_crm.shared.utils import format_amount, format_date

    fmt = get_date_format()
    return dict(
        format_amount=format_amount,
        format_date=lambda d: format_date(d, fmt),
        theme=get_theme(),
        equipment_status_labels=EQUIPMENT_STATUS_LABELS,
        movement_reason_labels=MOVEMENT_REASON_LABELS,
    )


# Route groups live in warehouse/routes/; importing them registers their
# @bp.route functions on the blueprint defined above.
from . import routes  # noqa: E402,F401

if __name__ == "__main__":
    # Standalone dev run (python -m qp_crm.warehouse.app) -- throwaway app,
    # same as the other modules' standalone blocks.
    from flask import Flask

    standalone = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    standalone.register_blueprint(bp, url_prefix="/warehouse")
    standalone.secret_key = os.environ.get("WAREHOUSE_SECRET_KEY", "crm_warehouse_secret_key_change_me")
    standalone.config["SESSION_COOKIE_NAME"] = "warehouse_session"
    init_db()
    standalone.run(host="0.0.0.0", debug=True, port=5009)
