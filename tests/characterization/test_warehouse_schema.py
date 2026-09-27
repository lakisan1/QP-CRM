"""P5-T1 schema tests: warehouse tables + products tracking regime.

Spec tests for the NEW P5 tables (the module is new, so these pin intended
behavior):

* a fresh DB creates equipment / stock_movements / reservations /
  equipment_shortfalls and the products tracking columns;
* every products row defaults to tracking_regime='untracked' (existing
  catalogs carry zero tracking burden — amendment 5);
* the idempotent ALTERs upgrade a legacy DB that predates P5 (only the
  products columns; legacy DBs predate the warehouse tables entirely);
* migrate_warehouse drops the retired rent_equipment orphan table;
* the closed sets are consistent (every value has a Serbian label).
"""

import sqlite3

import pytest

from qp_crm.shared.db import get_db
from qp_crm.shared.schema import (
    CUSTODIAN_TYPES,
    EQUIPMENT_STATUS_LABELS,
    EQUIPMENT_STATUS_VALUES,
    MOVEMENT_REASON_LABELS,
    MOVEMENT_REASON_VALUES,
    TRACKING_REGIMES,
    add_column_if_missing,
    create_warehouse_tables,
    migrate_warehouse,
)


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


def _columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table});")}


def test_fresh_schema_has_warehouse_tables():
    conn = get_db()
    for table in ("equipment", "stock_movements", "reservations",
                  "equipment_shortfalls"):
        assert conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?;",
            (table,),
        ).fetchone()[0] == 1, table
    conn.close()


def test_products_gained_tracking_columns():
    conn = get_db()
    cols = _columns(conn, "products")
    assert {"tracking_regime", "min_stock", "unit_base", "pack_size"} <= cols
    conn.close()


def test_new_products_default_untracked():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (name, category, item_type) VALUES ('P5 Test Deo', 'Test', 'proizvod');")
    pid = cur.lastrowid
    row = cur.execute(
        "SELECT tracking_regime FROM products WHERE id = ?;", (pid,)).fetchone()
    cur.execute("DELETE FROM products WHERE id = ?;", (pid,))
    conn.commit()
    conn.close()
    assert row["tracking_regime"] == "untracked"


def test_equipment_columns_canonical():
    conn = get_db()
    cols = _columns(conn, "equipment")
    assert {"product_id", "name_snapshot", "serial_number", "custodian_type",
            "custodian_contact_id", "since_date", "status",
            "expected_return_at", "notes", "created_at"} <= cols
    assert {"product_id", "equipment_id", "name_snapshot", "qty", "direction",
            "reason", "contact_id", "note", "moved_at", "moved_by"} <= _columns(conn, "stock_movements")
    assert {"product_id", "equipment_id", "qty", "for_whom", "created_at",
            "released_at"} <= _columns(conn, "reservations")
    assert {"equipment_id", "part_product_id", "part_name", "taken_at",
            "po_ref", "closed_at"} <= _columns(conn, "equipment_shortfalls")
    conn.close()


def test_equipment_default_custodian_and_status():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO equipment (name_snapshot, since_date) VALUES ('Test dizalica', '2026-09-25');")
    eid = cur.lastrowid
    row = cur.execute(
        "SELECT custodian_type, status FROM equipment WHERE id = ?;", (eid,)
    ).fetchone()
    cur.execute("DELETE FROM equipment WHERE id = ?;", (eid,))
    conn.commit()
    conn.close()
    assert row["custodian_type"] == "warehouse"
    assert row["status"] == "in_stock"


def test_legacy_products_table_upgrades_idempotently():
    """A legacy products table (pre-P5 columns) gains the regime columns
    via the ALTERs; re-running the migration is a no-op."""
    legacy = sqlite3.connect(":memory:")
    legacy.row_factory = sqlite3.Row
    legacy.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            brand TEXT,
            photo_path TEXT
        );
    """)
    legacy.execute(
        "INSERT INTO products (name) VALUES ('Legacy deo');")
    cur = legacy.cursor()
    # The P5 ALTER fragment, applied the way migrate_pricing does it.
    add_column_if_missing(cur, "products", "tracking_regime TEXT NOT NULL DEFAULT 'untracked'")
    add_column_if_missing(cur, "products", "min_stock REAL")
    add_column_if_missing(cur, "products", "unit_base TEXT")
    add_column_if_missing(cur, "products", "pack_size REAL")
    row = cur.execute(
        "SELECT tracking_regime FROM products WHERE name='Legacy deo';").fetchone()
    assert row["tracking_regime"] == "untracked"
    # second pass: no error
    add_column_if_missing(cur, "products", "tracking_regime TEXT NOT NULL DEFAULT 'untracked'")
    legacy.close()


def test_migrate_warehouse_drops_rent_equipment():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE rent_equipment (id INTEGER PRIMARY KEY, name TEXT);")
    conn.execute("INSERT INTO rent_equipment (name) VALUES ('orphan');")
    cur = conn.cursor()
    migrate_warehouse(cur)
    # gone
    count = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='rent_equipment';"
    ).fetchone()[0]
    assert count == 0
    # idempotent: dropping an absent table is fine
    migrate_warehouse(cur)
    conn.close()


def test_closed_sets_consistent():
    # every DB value has exactly one Serbian label
    assert len(TRACKING_REGIMES) == 3
    assert set(CUSTODIAN_TYPES) == {"warehouse", "customer", "scrap"}
    assert len(EQUIPMENT_STATUS_LABELS) == len(EQUIPMENT_STATUS_VALUES)
    assert len(MOVEMENT_REASON_LABELS) == len(MOVEMENT_REASON_VALUES)
    # no empty labels (the UI renders them directly)
    assert all(EQUIPMENT_STATUS_LABELS.values())
    assert all(MOVEMENT_REASON_LABELS.values())
