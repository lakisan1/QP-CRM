"""
WSGI entrypoint for QP-CRM under a production WSGI server (gunicorn).

    gunicorn --preload --bind 0.0.0.0:5000 qp_crm.wsgi:application

WHY DATABASE INIT LIVES HERE
----------------------------
main.py creates and migrates the SQLite schemas only inside its
`if __name__ == "__main__":` block (main.py:61-70). That block never runs
under gunicorn: gunicorn merely imports this module and serves the WSGI
callable named `application`. On a fresh volume the server would come up
with a missing schema and every DB-backed page would fail.

This module therefore replays the exact same init sequence at import time,
before `application` is exposed. The init functions are idempotent —
CREATE TABLE IF NOT EXISTS everywhere, ALTER TABLE wrapped in
"column already exists" guards, INSERT OR IGNORE / count-checked seeding —
so re-running them on an existing volume is a cheap no-op.

Fork safety: none of the init functions keeps a SQLite connection open once
it returns (connection close verified at pricing/app.py:244,
pricing/app.py:349, offer/app.py:183, admin/app.py:44/99/135,
rent/app.py:251). All connections come from qp_crm.shared.db.get_db(), which opens
a fresh per-call connection, and no module-level connections exist anywhere
in the codebase — so forking workers after a --preload import is safe.
--preload is recommended anyway: init then runs exactly once in the master
instead of racing between workers on a cold volume.
"""

import os

from qp_crm.shared.config import APP_DATA_DIR, IMAGE_DIR, APP_ASSETS_DIR

# 1) Ensure writable directories exist BEFORE anything touches SQLite or the
#    filesystem. On a fresh volume sqlite3.connect() cannot create
#    app_data/pricing.db when app_data/ is missing ("unable to open database
#    file"). IMAGE_DIR (app_data/product_images) and APP_ASSETS_DIR
#    (app_assets) are the other on-disk locations the apps read from and
#    write to (product photos, logo, PDF footer, favicon).
for _directory in (APP_DATA_DIR, IMAGE_DIR, APP_ASSETS_DIR):
    os.makedirs(_directory, exist_ok=True)

# 2) Run the DB init/migration sequence in the same order as `python -m qp_crm.main`
#    (main.py:66-70), importing each function from the same module main.py
#    imports it from (main.py:15-20).
#    Deliberately NO try/except here: if initialization fails, the import of
#    this module fails and gunicorn refuses to boot with a full traceback,
#    instead of silently serving an empty schema.
print("Initializing databases (wsgi.py)...", flush=True)

from qp_crm.pricing.app import init_db as pricing_init_db, migrate_schema as pricing_migrate_schema  # noqa: E402
from qp_crm.offer.app import init_db as offer_init_db  # noqa: E402
from qp_crm.admin.app import init_db as admin_init_db  # noqa: E402
from qp_crm.rent.app import init_db as rent_init_db  # noqa: E402

pricing_init_db()
pricing_migrate_schema()
offer_init_db()
admin_init_db()
rent_init_db()

print("Database initialization complete.", flush=True)

# 3) The WSGI application object gunicorn serves (`qp_crm.wsgi:application`):
#    the DispatcherMiddleware merging the landing app with the six sub-apps
#    (main.py:52-59). Importing `qp_crm.main` at this point also loads the remaining
#    sub-apps (sale, settings, pricing.api_v1) exactly as a normal
#    `python -m qp_crm.main` run would; the four modules above are already in
#    sys.modules, so their module-level code is not executed twice.
from qp_crm.main import application  # noqa: E402, F401
