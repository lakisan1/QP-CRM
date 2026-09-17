"""Contacts module (P5-pre): the shared directory (Zajednički imenik).

Blueprint on the single QP-CRM app, mounted at /contacts by main.py — same
pattern as deals (Phase 4). The module owns:

  * contacts + contact_roles + contact_links (schema in shared/schema.py,
    single source);
  * the directory UI (list with role/kind filters, add/edit form, detail
    page) shared by rent, ponude, poslovi and future radni nalozi.

Access: require_module("contacts") — per-user app access like every other
module (MODULE_CHOICES v4 in shared/auth.py); admins bypass grants.

The module is deliberately INDEPENDENT of the deals customers pages: the
directory is the wider registry (suppliers, employees, external
collaborators, partners — companies AND persons); the deals spine keeps
its own billing-focused customer screens on top of the customers table.
"""
import os

from flask import Blueprint, Flask

from qp_crm.shared.config import STATIC_DIR
from qp_crm.shared.db import get_db
from qp_crm.shared.web import require_module

bp = Blueprint("contacts", __name__, template_folder="templates")

# Per-user app access gate (P5-pre): staff need the 'contacts' grant.
bp.before_request(require_module("contacts"))


def init_db():
    """Thin wrapper -- the DDL lives in shared/schema.py (single source).

    Runs in the boot sequence after deals_init_db (see wsgi.py / main.py);
    both steps are idempotent.
    """
    from qp_crm.shared.schema import create_contacts_tables, migrate_contacts

    conn = get_db()
    cur = conn.cursor()
    create_contacts_tables(cur)
    migrate_contacts(cur)
    conn.commit()
    conn.close()


@bp.context_processor
def inject_helpers():
    """Template helpers every contacts page expects (same set the other
    business modules inject)."""
    from qp_crm.shared.schema import CONTACT_ROLES
    from qp_crm.shared.web import get_date_format, get_theme
    from qp_crm.shared.utils import format_amount, format_date

    fmt = get_date_format()
    return dict(
        format_amount=format_amount,
        format_date=lambda d: format_date(d, fmt),
        theme=get_theme(),
        contact_roles=CONTACT_ROLES,
    )


# Route groups live in contacts/routes/; importing them registers their
# @bp.route functions on the blueprint defined above.
from . import routes  # noqa: E402,F401

if __name__ == "__main__":
    # Standalone dev run (python -m qp_crm.contacts.app) -- throwaway app,
    # same as the other modules' standalone blocks.
    from flask import Flask

    standalone = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
    standalone.register_blueprint(bp, url_prefix="/contacts")
    standalone.secret_key = os.environ.get("CONTACTS_SECRET_KEY", "crm_contacts_secret_key_change_me")
    standalone.config["SESSION_COOKIE_NAME"] = "contacts_session"
    init_db()
    standalone.run(host="0.0.0.0", debug=True, port=5008)
