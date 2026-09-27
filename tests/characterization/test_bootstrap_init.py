"""P5 follow-up: the boot/restore init sequence has ONE definition.

The ordered init sequence used to be written out three times (wsgi.py,
main.py's __main__ block, tests/conftest.py) and would have needed a
fourth copy for the Admin -> Backup restore flow. These tests pin the
consolidated behavior:

* `init_all_modules()` creates every table any module owns;
* it is idempotent (safe to re-run on a live database — this is what makes
  it callable after a restore);
* it RECOVERS a database that predates a module: drop the P5 warehouse
  tables and the products tracking columns, re-run, and they come back.
  That is the bug this refactor closed — boot init runs once at process
  start, so restoring an older backup used to leave the restored database
  serving 500s until a container restart.
"""

import pytest

from qp_crm.shared.bootstrap import init_all_modules
from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


def _tables():
    conn = get_db()
    try:
        return {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
    finally:
        conn.close()


def _product_columns():
    conn = get_db()
    try:
        return {row["name"] for row in conn.execute("PRAGMA table_info(products);")}
    finally:
        conn.close()


def test_init_all_modules_creates_every_module_table():
    tables = _tables()
    for table in (
        # pricing
        "products", "prices", "global_settings", "price_rounding_rules",
        # offer
        "offers", "offer_items", "pdf_templates", "text_presets",
        # rent
        "rent_clients", "rent_contracts", "rent_templates",
        "rent_contract_documents",
        # contacts
        "contacts", "contact_roles", "contact_locations",
        # warehouse (P5)
        "equipment", "stock_movements", "reservations", "equipment_shortfalls",
        # auth
        "users", "user_modules",
    ):
        assert table in tables, f"{table} missing from the init sequence"


def test_init_all_modules_is_idempotent():
    """Re-running the sequence must not raise and must not lose tables."""
    before = _tables()
    init_all_modules()
    init_all_modules()
    assert _tables() == before


def test_init_all_modules_recovers_a_database_that_predates_p5():
    """Drop the P5 warehouse tables AND the tracking columns, re-run the
    sequence, and everything comes back — the restore-recovery guarantee."""
    conn = get_db()
    try:
        cur = conn.cursor()
        for table in ("stock_movements", "equipment_shortfalls", "reservations",
                      "equipment"):
            cur.execute(f"DROP TABLE IF EXISTS {table};")
        # SQLite cannot drop a column before 3.35 and this app supports older
        # files, so emulate a pre-P5 products table by rebuilding it without
        # the tracking columns.
        cur.execute("ALTER TABLE products RENAME TO products_pre_p5;")
        cur.execute("""
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                category TEXT,
                brand TEXT,
                photo_path TEXT,
                website_url TEXT,
                manufacturer_url TEXT,
                product_code TEXT,
                item_type TEXT NOT NULL DEFAULT 'proizvod'
            );
        """)
        cur.execute("""
            INSERT INTO products (name, item_type)
            SELECT name, item_type FROM products_pre_p5;
        """)
        cur.execute("DROP TABLE products_pre_p5;")
        conn.commit()
    finally:
        conn.close()

    # Sanity: the database is now genuinely pre-P5.
    assert "equipment" not in _tables()
    assert "tracking_regime" not in _product_columns()

    init_all_modules()

    # ...and the sequence restored it.
    tables = _tables()
    for table in ("equipment", "stock_movements", "reservations",
                  "equipment_shortfalls"):
        assert table in tables, f"{table} was not re-created"
    assert {"tracking_regime", "min_stock", "unit_base", "pack_size"} <= _product_columns()
