"""Orders module (P5-UI rework batch B): purchase orders & ordering.

The commercial-side app: what to order (open shortfall debts + coverage
gaps), the PO ledger (supplier, lines, expected arrival, status), and
receiving (each arrived line appends the inbound ledger movement and
auto-closes its shortfall). The warehouse operator never comes here —
their stock math updates automatically on receive.

Blueprint on the single QP-CRM app at /orders; per-user grant 'orders'
(MODULE_CHOICES v6); admins bypass.
"""
import os

from flask import Blueprint

from qp_crm.shared.config import STATIC_DIR
from qp_crm.shared.db import get_db
from qp_crm.shared.web import require_module

bp = Blueprint("orders", __name__, template_folder="templates")

bp.before_request(require_module("orders"))


def init_db():
    """Thin wrapper — the DDL lives in shared/schema.py (single source)."""
    from qp_crm.shared.schema import create_order_tables

    conn = get_db()
    cur = conn.cursor()
    create_order_tables(cur)
    conn.commit()
    conn.close()


@bp.context_processor
def inject_helpers():
    """Template helpers every orders page expects."""
    from qp_crm.shared.schema import ORDER_STATUS_LABELS
    from qp_crm.shared.web import get_date_format, get_theme
    from qp_crm.shared.utils import format_amount, format_date

    fmt = get_date_format()
    return dict(
        format_amount=format_amount,
        format_date=lambda d: format_date(d, fmt),
        theme=get_theme(),
        order_status_labels=ORDER_STATUS_LABELS,
    )


from . import routes  # noqa: E402,F401

if __name__ == "__main__":
    # Standalone dev run (python -m qp_crm.orders.app) -- throwaway app.
    from flask import Flask

    standalone = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    standalone.register_blueprint(bp, url_prefix="/orders")
    standalone.secret_key = os.environ.get("ORDERS_SECRET_KEY", "crm_orders_secret_key_change_me")
    standalone.config["SESSION_COOKIE_NAME"] = "orders_session"
    init_db()
    standalone.run(host="0.0.0.0", debug=True, port=5010)
