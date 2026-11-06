"""P-6 User logs — global SQLite trigger audit (2026-11-06).

Pinned behavior:

* audit_log table + AFTER INSERT/UPDATE/DELETE triggers exist on every
  business table (blacklist approach: enumerated from sqlite_master);
* a write to a business table logs one row per action — table_name, row_id
  (the table's id column, NULL for id-less config tables), action
  ('created'/'updated'/'deleted'), user_id/username, source
  ('web'/'api'/'system') and a UTC ts;
* outside a request context the actor is NULL/'system'; inside a request the
  actor comes from Flask g (populate_audit_context) and the API path stamps
  the per-user key holder as source='api';
* excluded tables (users, api_keys, global_settings, site_products, the log
  tables, ...) get NO triggers.
"""

import pytest

from qp_crm.main import app
from qp_crm.shared.db import get_db


def _insert_product(name):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (name) VALUES (?)", (name,))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid


def _audit_rows(table_name, row_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE table_name = ? AND row_id = ? ORDER BY id;",
        (table_name, row_id),
    ).fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------------ triggers

def test_triggers_cover_business_tables_and_respect_blacklist(temp_db):
    conn = get_db()
    triggers = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger';"
        ).fetchall()
    ]
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%';"
        ).fetchall()
    ]
    conn.close()

    assert "audit_log" in tables

    # Business tables get all three triggers.
    for t in ("products", "offers", "rent_contracts", "stock_movements", "contacts"):
        assert f"audit_{t}_ins" in triggers
        assert f"audit_{t}_upd" in triggers
        assert f"audit_{t}_del" in triggers

    # Blacklist: no trigger on the log itself or high-churn/technical tables.
    for t in ("audit_log", "api_audit", "login_audit", "api_keys",
              "users", "user_modules", "global_settings", "site_products"):
        assert not any(name.startswith(f"audit_{t}_") for name in triggers)


# ------------------------------------------------------------------- writes

def test_crud_is_logged_with_system_source(temp_db):
    name = "audit-crud-product"
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (name) VALUES (?)", (name,))
    pid = cur.lastrowid
    cur.execute("UPDATE products SET description = ? WHERE id = ?", ("changed", pid))
    cur.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()

    rows = _audit_rows("products", pid)
    assert [r["action"] for r in rows] == ["created", "updated", "deleted"]
    # The human label is captured at write time from the row itself.
    assert [r["record_label"] for r in rows] == [name, name, name]
    # No request context here -> system actor.
    assert all(r["source"] == "system" for r in rows)
    assert all(r["user_id"] is None and r["username"] is None for r in rows)
    assert all(r["ts"] for r in rows)


def test_price_audit_carries_parent_product_name(temp_db):
    """prices has no name column — its label is the PARENT product's name,
    resolved by a subquery in the trigger."""
    name = "audit-price-product"
    pid = _insert_product(name)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO prices (product_id, date, base_price) VALUES (?, '2026-01-01', 100.0)",
        (pid,),
    )
    conn.commit()
    price_id = cur.lastrowid
    conn.close()

    rows = _audit_rows("prices", price_id)
    assert len(rows) == 1
    assert rows[0]["action"] == "created"
    assert rows[0]["record_label"] == name


# -------------------------------------------------------------- attribution

def test_web_attribution_via_request_context(temp_db):
    from flask import g

    name = "audit-web-product"
    with app.test_request_context("/"):
        g.audit_user_id = 777
        g.audit_username = "tester"
        g.audit_source = "web"
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO products (name) VALUES (?)", (name,))
        conn.commit()
        pid = cur.lastrowid
        conn.close()

    rows = _audit_rows("products", pid)
    assert len(rows) == 1
    assert rows[0]["action"] == "created"
    assert rows[0]["user_id"] == 777
    assert rows[0]["username"] == "tester"
    assert rows[0]["source"] == "web"


def test_api_write_attributed_to_key_holder(temp_db):
    from qp_crm.shared.auth import issue_user_api_key

    conn = get_db()
    uid = conn.execute("SELECT id FROM users WHERE username = 'offer'").fetchone()["id"]
    conn.close()
    raw, _ = issue_user_api_key(uid, "audit-api-test")

    client = app.test_client()
    resp = client.post(
        "/api/v1/products",
        headers={"Authorization": f"Bearer {raw}"},
        json={"name": "audit-api-product", "item_type": "proizvod"},
    )
    assert resp.status_code in (200, 201)

    conn = get_db()
    pid = conn.execute(
        "SELECT id FROM products WHERE name = 'audit-api-product'"
    ).fetchone()["id"]
    conn.close()

    rows = _audit_rows("products", pid)
    assert len(rows) == 1
    assert rows[0]["action"] == "created"
    assert rows[0]["source"] == "api"
    assert rows[0]["username"] == "offer"
    assert rows[0]["user_id"] == uid


# ---------------------------------------------------------------------- UI

def test_admin_audit_page_renders_and_is_admin_only(temp_db, admin_client):
    from conftest import login_client

    _insert_product("audit-page-product")

    resp = admin_client.get("/admin/audit")
    assert resp.status_code == 200
    assert "Istorija izmena".encode() in resp.data

    # Staff cannot open the admin audit page (admin blueprint gate).
    staff = login_client(app.test_client(), "pricing")
    assert staff.get("/admin/audit").status_code == 403
