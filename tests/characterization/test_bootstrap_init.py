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

import sqlite3

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
        # Emulate a pre-P5 products table by dropping the tracking columns.
        #
        # DO NOT "simplify" this into ALTER TABLE products RENAME TO tmp and
        # a rebuild. Since SQLite 3.25 the default behaviour of RENAME is to
        # REWRITE the foreign-key clauses of every OTHER table to point at the
        # new name, and PRAGMA legacy_alter_table=ON does NOT reliably
        # suppress that here (measured on sqlite 3.45.1: offer_items, prices
        # and product_aliases all came back declaring
        # `REFERENCES "products_pre_p5"(id)`). Dropping the temp table then
        # leaves the whole database pointing at a table that no longer
        # exists, and every later INSERT into those tables dies with
        # `no such table: main.products_pre_p5` — failures that surface far
        # away, in unrelated test files, looking like someone else's bug.
        # DROP COLUMN touches only `products` and cannot do that. It needs
        # SQLite >= 3.35 (2021); the guard below keeps old-SQLite hosts
        # honest instead of silently testing nothing.
        if sqlite3.sqlite_version_info < (3, 35, 0):
            pytest.skip(f"ALTER TABLE DROP COLUMN needs SQLite >= 3.35, have {sqlite3.sqlite_version}")
        for column in ("tracking_regime", "min_stock", "unit_base", "pack_size"):
            cur.execute(f"ALTER TABLE products DROP COLUMN {column};")
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


def test_no_schema_object_points_at_a_table_that_does_not_exist():
    """General integrity guard, and the regression guard for the rename trap.

    A previous version of the recovery test above rebuilt `products` via
    ALTER TABLE ... RENAME TO products_pre_p5. SQLite rewrote the FK clauses
    of every child table to the temp name and then the temp table was
    dropped, leaving the whole schema dangling — later inserts failed with
    `no such table: main.products_pre_p5`. This asserts that nothing in
    sqlite_master names a table that is not actually present, so that class
    of breakage can never come back silently.
    """
    conn = get_db()
    try:
        present = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';").fetchall()
        }
        objects = conn.execute(
            "SELECT type, name, tbl_name FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'trigger', 'view');").fetchall()
    finally:
        conn.close()
    dangling = [
        f"{r['type']} {r['name']} -> {r['tbl_name']}"
        for r in objects
        if r["tbl_name"] and r["tbl_name"] not in present
    ]
    assert dangling == [], f"schema objects pointing at missing tables: {dangling}"


def test_referencing_tables_still_accept_inserts_after_the_recovery():
    """The concrete failure the rename trap produced: inserting into the
    tables that carry a products(id) foreign key. Exercises the FK for real."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (name, item_type) VALUES ('FK guard product', 'proizvod');")
        pid = cur.lastrowid
        cur.execute(
            "INSERT INTO prices (product_id, date, base_price) "
            "VALUES (?, '2026-01-01', 10.0);",
            (pid,),
        )
        cur.execute(
            "INSERT INTO product_aliases (alias, product_id) VALUES ('FK guard alias', ?);",
            (pid,),
        )
        conn.commit()
    finally:
        conn.close()
