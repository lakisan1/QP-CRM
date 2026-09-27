"""Warehouse test package fixtures.

SHARED-DATABASE HYGIENE
-----------------------
The whole suite runs against ONE session-scoped database (conftest.py's
`temp_db`), and the pricing products list is PAGINATED (`ORDER BY name ASC`,
`LIMIT` from the `default_items_per_page` setting). That combination makes
leftover rows contagious: a module that quietly adds products changes which
rows other modules see on page 1. This package did exactly that — its
products pushed a smoke test's freshly created product off the first page
and failed a test it had nothing to do with.

So everything this package creates is removed again at the end of the
module, children first (foreign keys are enforced). The application is
archive-only; a TEST cleaning up after itself is not the same thing.
"""

import pytest

from qp_crm.shared.db import get_db

# Foreign-key-safe deletion order: referencing tables before referenced ones.
_CLEANUP_ORDER = (
    "stock_movements",
    "reservations",
    "equipment_shortfalls",
    "equipment",
    "product_aliases",
    "products",
    "contacts",
)


@pytest.fixture(scope="module", autouse=True)
def _cleanup_created_rows():
    """Delete every row this module created, leaving the DB as it was found."""
    def _max_id(table):
        conn = get_db()
        try:
            return conn.execute(
                f"SELECT COALESCE(MAX(id), 0) AS m FROM {table};").fetchone()["m"]
        finally:
            conn.close()

    marks = {table: _max_id(table) for table in _CLEANUP_ORDER}
    yield
    conn = get_db()
    try:
        cur = conn.cursor()
        for table in _CLEANUP_ORDER:
            cur.execute(f"DELETE FROM {table} WHERE id > ?;", (marks[table],))
        conn.commit()
    finally:
        conn.close()
