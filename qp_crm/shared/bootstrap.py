"""Single source of truth for the app-wide DB init/migration sequence.

WHY THIS MODULE EXISTS
----------------------
The same ordered sequence used to be written out in three places --
`qp_crm/wsgi.py` (gunicorn boot), the `__main__` block of `qp_crm/main.py`
(dev boot) and `tests/conftest.py` (test boot). A fourth copy would have
been needed for the Admin -> Backup restore flow, which also has to
re-create any tables a restored (possibly older) file is missing.
Divergence between copies is a silent-failure class: a module whose DDL is
not replayed boots into a half-missing schema.

ORDER IS LOAD-BEARING
---------------------
pricing first (offer/rent/admin/contacts all read its products and
global_settings), then the modules that depend on it, warehouse last
because it references products AND contacts, orders after warehouse
because po_lines references equipment_shortfalls:

    pricing_init_db -> pricing_migrate_schema
    -> offer_init_db -> admin_init_db -> rent_init_db
    -> contacts_init_db -> warehouse_init_db -> orders_init_db

Every function in the sequence is idempotent (CREATE TABLE IF NOT EXISTS,
"column already exists"-guarded ALTERs, INSERT OR IGNORE / count-checked
seeding), so running this on an already-initialized database is a cheap
no-op. That property is what makes it safe to call again after a restore.

CONNECTION DISCIPLINE
---------------------
Each `init_db` opens and closes its own connection via
`qp_crm.shared.db.get_db()`; none of them keeps a connection open on
return, and there are no module-level connections anywhere in the
codebase. A leaked connection would hold a SQLite WAL read lock, which
turns the next write into `database is locked` -- so do not hold a
connection across these calls.
"""


def init_all_modules():
    """Run the full ordered init/migration sequence (idempotent).

    Call this at every boot point. Deliberately does NOT swallow
    exceptions: a failed init must surface as a loud boot failure rather
    than a server that starts and then 500s on every DB-backed page.

    Returns nothing; raises whatever the first failing step raises.
    """
    from qp_crm.pricing.app import (
        init_db as pricing_init_db,
        migrate_schema as pricing_migrate_schema,
    )
    from qp_crm.offer.app import init_db as offer_init_db
    from qp_crm.admin.app import init_db as admin_init_db
    from qp_crm.rent.app import init_db as rent_init_db
    from qp_crm.contacts.app import init_db as contacts_init_db
    from qp_crm.warehouse.app import init_db as warehouse_init_db
    from qp_crm.orders.app import init_db as orders_init_db

    # Imports happen here (not at module import time) so importing this
    # module never triggers the app package import graph -- that ordering
    # is what lets conftest.py patch shared.config first.
    pricing_init_db()
    pricing_migrate_schema()
    offer_init_db()
    admin_init_db()
    rent_init_db()
    contacts_init_db()
    warehouse_init_db()
    # orders last: purchase_orders/po_lines reference products AND
    # equipment_shortfalls (warehouse tables must exist first).
    orders_init_db()
