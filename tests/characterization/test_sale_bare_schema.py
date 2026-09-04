"""Regression for the phase-2 bug-fix stage (board card "BUG - sale
module: list_sale 500s on uninitialized schema (no own init_db, unguarded
global_settings read)").

On a bare/recreated schema (restore_db edge cases, future split
deployments, fresh test DBs), GET /sale/pricelist used to raise
sqlite3.OperationalError 'no such table: global_settings' -> 500. After
the fix the sale module degrades to a clean empty state (list) and a
clean 404 (product view).

Uses its own throwaway DB patched into qp_crm.shared.db.DATABASE so the
shared session fixture DB stays untouched.
"""

import os
import sqlite3

import pytest


@pytest.fixture
def bare_schema_client(temp_db):
    """Test client whose get_db() points at a fresh DB with NO tables."""
    from qp_crm.shared import config, db
    from qp_crm.main import app

    bare = os.path.join(os.path.dirname(config.DATABASE), "bare-schema-test.db")
    if os.path.exists(bare):
        os.remove(bare)
    sqlite3.connect(bare).close()  # exists, but zero tables

    old_db_attr = db.DATABASE
    old_cfg = config.DATABASE
    db.DATABASE = bare
    config.DATABASE = bare
    try:
        yield app.test_client()
    finally:
        db.DATABASE = old_db_attr
        config.DATABASE = old_cfg
        os.remove(bare)


def test_pricelist_renders_empty_state_on_bare_schema(bare_schema_client):
    response = bare_schema_client.get("/sale/pricelist")
    assert response.status_code == 200
    assert b"Pr leggings" in response.data or b"pricelist" in response.data.lower()


def test_view_product_404_on_bare_schema(bare_schema_client):
    response = bare_schema_client.get("/sale/product/1")
    assert response.status_code == 404
