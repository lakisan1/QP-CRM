"""P1-T1 infra guard: the suite must never touch the real app_data tree.

If shared.config patching in conftest.py ever stops working (e.g. someone
imports an app module before conftest, or adds a new path constant), these
checks fail BEFORE any money-path test can silently run against production
data.
"""

import os

from conftest import TEST_DATABASE, TEST_APP_DATA_DIR, TEST_ASSETS_DIR


def test_config_paths_point_into_temp_tree():
    import shared.config as config

    assert config.DATABASE == TEST_DATABASE
    assert config.APP_DATA_DIR == TEST_APP_DATA_DIR
    assert config.APP_ASSETS_DIR == TEST_ASSETS_DIR


def test_shared_db_reads_the_temp_database():
    # shared.db binds DATABASE from shared.config at ITS import time - it
    # must have picked up the patched value, not the repo's app_data path.
    import shared.db as db
    import shared.config as config

    assert db.DATABASE == config.DATABASE
    assert "/tmp/qp-crm-tests/" in db.DATABASE


def test_temp_db_is_not_the_repo_db():
    repo_db = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "app_data", "pricing.db",
    )
    assert TEST_DATABASE != repo_db


def test_temp_db_is_initialized(temp_db, conn_factory):
    """The session init sequence must have created the core tables."""
    with conn_factory() as conn:
        cur = conn.cursor()
        for table in (
            "products", "global_settings", "price_rounding_rules",
            "offers", "offer_items", "pdf_templates", "text_presets",
            "rent_clients", "rent_equipment", "rent_contracts",
            "rent_templates", "rent_contract_documents",
        ):
            cur.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?;",
                (table,),
            )
            assert cur.fetchone()[0] == 1, f"table {table} missing after init"
