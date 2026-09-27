"""Orders module tests (P5-UI rework batch B).

Pins the commercial side end to end: PO numbering (PO-YYYY-NNN global
counter), line validation (product or temp name, qty > 0), receiving a
line (ledger movement appended automatically + shortfall auto-closed
with po_ref), status transitions (ordered → partially → received,
cancel terminal), the 'what to order' board (debts + min-stock gaps),
and the per-user grant gate (staff without 'orders' get 403).
"""

import pytest

from conftest import csrf_token_for, login_client

from qp_crm.shared.auth import DEFAULT_PASSWORDS
from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


@pytest.fixture()
def client():
    from qp_crm.main import app
    c = app.test_client()
    c.get("/login")
    with c.session_transaction() as session:
        session["_csrf_token"] = session.get("_csrf_token") or "tok"
    return c


def _scalar(sql, params=()):
    conn = get_db()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _new_product(name, regime="untracked", min_stock=None):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (name, item_type, tracking_regime, min_stock) "
            "VALUES (?, 'proizvod', ?, ?);",
            (name, regime, min_stock),
        )
        pid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return pid


def _order_in_db(po_id):
    return _scalar("SELECT * FROM purchase_orders WHERE id = ?;", (po_id,))


# ---------------------------------------------------------------------------
# service: create_order
# ---------------------------------------------------------------------------

def test_create_order_numbering_is_global_sequential():
    from qp_crm.services import order_service as orders
    pid = _new_product("PO num proizvod", regime="qty")
    ok1, po1 = orders.create_order("Dobavljač 1", [{"product_id": pid, "qty": 5}])
    ok2, po2 = orders.create_order("Dobavljač 2", [{"product_id": pid, "qty": 2}])
    assert ok1 and ok2
    n1 = _scalar("SELECT po_number FROM purchase_orders WHERE id = ?;", (po1,))["po_number"]
    n2 = _scalar("SELECT po_number FROM purchase_orders WHERE id = ?;", (po2,))["po_number"]
    assert n1.startswith("PO-") and n2.startswith("PO-")
    assert n1 != n2


def test_create_order_validation():
    from qp_crm.services import order_service as orders
    pid = _new_product("PO validacija", regime="qty")
    ok, msg = orders.create_order("", [{"product_id": pid, "qty": 1}])
    assert not ok and "Dobavljač" in msg
    ok, msg = orders.create_order("X", [])
    assert not ok and "stavku" in msg
    ok, msg = orders.create_order("X", [{"product_id": pid, "qty": 0}])
    assert not ok and "veća od nule" in msg
    ok, msg = orders.create_order("X", [{"qty": 2}])  # no product, no name
    assert not ok and "naziv" in msg
    ok, po = orders.create_order("X", [{"name_snapshot": "Temp stavka", "qty": 2}])
    assert ok
    assert _order_in_db(po)["status"] == "ordered"


# ---------------------------------------------------------------------------
# service: receive_line (ledger + auto-close shortfall)
# ---------------------------------------------------------------------------

def test_receive_line_appends_ledger_and_closes_shortfall():
    from qp_crm.services import order_service as orders
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Prijem sa dugom", regime="qty")
    ok, po = orders.create_order(
        "Dobavljač duga",
        [{"product_id": pid, "qty": 3}])
    assert ok
    # an open shortfall on a machine references this line's product
    ok, eid = wh.register_equipment(name_snapshot="Mašina sa dugom")
    assert ok
    ok, short = wh.create_shortfall(eid, part_product_id=pid)
    assert ok
    # link the shortfall to the PO line (the needed-board flow does this)
    conn = get_db()
    try:
        line = conn.execute(
            "SELECT id FROM po_lines WHERE po_id = ?;", (po,)).fetchone()
        conn.execute(
            "UPDATE po_lines SET shortfall_id = ? WHERE id = ?;",
            (short, line["id"]))
        conn.commit()
        line_id = line["id"]
    finally:
        conn.close()
    ok, msg = orders.receive_line(line_id)
    assert ok
    # ledger movement appended automatically
    assert wh.qty_on_hand(pid) == 3
    # shortfall auto-closed with po_ref = PO number
    row = _scalar("SELECT closed_at, po_ref FROM equipment_shortfalls WHERE id = ?;", (short,))
    assert row["closed_at"] is not None
    assert (row["po_ref"] or "").startswith("PO-")
    # PO status became 'received'
    assert _order_in_db(po)["status"] == "received"
    # idempotence: receiving again is rejected
    ok, msg = orders.receive_line(line_id)
    assert not ok and "već primljena" in msg


def test_receive_line_sets_partially_then_received():
    from qp_crm.services import order_service as orders
    pid = _new_product("Delimični prijem", regime="qty")
    ok, po = orders.create_order("D", [
        {"product_id": pid, "qty": 1},
        {"product_id": pid, "qty": 2},
    ])
    assert ok
    lines = _scalar("SELECT id FROM po_lines WHERE po_id = ? ORDER BY id;", (po,))
    second = _scalar(
        "SELECT id FROM po_lines WHERE po_id = ? ORDER BY id DESC LIMIT 1;", (po,))
    ok, status = orders.receive_line(second["id"])
    assert ok and status == "partially"
    assert _order_in_db(po)["status"] == "partially"
    ok, status = orders.receive_line(lines["id"])
    assert ok and status == "received"
    assert _order_in_db(po)["status"] == "received"


def test_cancel_order_terminal():
    from qp_crm.services import order_service as orders
    pid = _new_product("Otkazivanje", regime="qty")
    ok, po = orders.create_order("D", [{"product_id": pid, "qty": 1}])
    assert ok
    ok, _ = orders.cancel_order(po)
    assert ok
    assert _order_in_db(po)["status"] == "cancelled"
    ok, msg = orders.cancel_order(po)
    assert not ok and "nije aktivna" in msg


def test_needed_board_lists_debts_and_gaps():
    from qp_crm.services import order_service as orders
    from qp_crm.services import warehouse_service as wh
    pid_gap = _new_product("Min stanje proizvod", regime="qty", min_stock=10)
    pid_ok = _new_product("Dovoljno proizvod", regime="qty", min_stock=2)
    wh.record_movement(product_id=pid_ok, qty=5, direction="in", reason="purchase_in")
    data = orders.open_shortfalls_for_ordering()
    gap_ids = {g["product_id"] for g in data["gaps"]}
    assert pid_gap in gap_ids and pid_ok not in gap_ids


# ---------------------------------------------------------------------------
# module gate + pages
# ---------------------------------------------------------------------------

def test_staff_without_orders_grant_gets_403(client):
    login_client(client, "rent")
    # conftest provisions staff with ALL MODULE_CHOICES grants — strip
    # 'orders' to model an account the admin hasn't granted it to
    from qp_crm.shared.auth import get_user_modules, set_user_modules
    uid = _scalar("SELECT id FROM users WHERE username = 'rent';")["id"]
    set_user_modules(uid, [m for m in get_user_modules(uid) if m != "orders"])
    r = client.get("/orders/list")
    assert r.status_code == 403


def test_admin_sees_orders_pages(client):
    login_client(client, "admin", DEFAULT_PASSWORDS["admin"])
    for path in ("/orders/list", "/orders/needed", "/orders/new"):
        assert client.get(path).status_code == 200, path


def test_order_form_roundtrip_and_receive(client):
    login_client(client, "admin", DEFAULT_PASSWORDS["admin"])
    pid = _new_product("Form roundtrip", regime="qty")
    tok = csrf_token_for(client)
    r = client.post("/orders/new", data={
        "_csrf_token": tok,
        "supplier_name": "Kamion DOO",
        "expected_at": "2026-10-15",
        "line_product": [str(pid)],
        "line_name": [""],
        "line_qty": ["7"],
        "line_shortfall": [""],
    }, follow_redirects=False)
    assert r.status_code == 302
    po = _scalar("SELECT id FROM purchase_orders ORDER BY id DESC LIMIT 1;")["id"]
    # detail page shows the line waiting
    r = client.get(f"/orders/{po}")
    assert r.status_code == 200
    assert "Čeka se" in r.get_data(as_text=True)
    # receive it
    line_id = _scalar("SELECT id FROM po_lines WHERE po_id = ?;", (po,))["id"]
    r = client.post(f"/orders/lines/{line_id}/receive", data={
        "_csrf_token": tok, "po_id": str(po),
    }, follow_redirects=False)
    assert r.status_code == 302
    from qp_crm.services import warehouse_service as wh
    assert wh.qty_on_hand(pid) == 7
    assert _scalar("SELECT status FROM purchase_orders WHERE id = ?;", (po,))["status"] == "received"


# ---------------------------------------------------------------------------
# planning (Komercijala): reservations + coverage + equipment map
# ---------------------------------------------------------------------------

def test_planning_pages_under_orders_grant(client):
    login_client(client, "admin", DEFAULT_PASSWORDS["admin"])
    for path in ("/orders/reservations", "/orders/reservations/new",
                 "/orders/coverage", "/orders/equipment-map"):
        assert client.get(path).status_code == 200, path


def test_warehouse_reservations_moved_out(client):
    """Old /warehouse/reservations + /warehouse/coverage are gone (the
    operator app no longer carries commercial views)."""
    login_client(client, "admin", DEFAULT_PASSWORDS["admin"])
    assert client.get("/warehouse/reservations").status_code == 404
    assert client.get("/warehouse/coverage").status_code == 404


def test_reservation_roundtrip_in_komercijala(client):
    login_client(client, "admin", DEFAULT_PASSWORDS["admin"])
    pid = _new_product("Rez prod", regime="qty")
    tok = csrf_token_for(client)
    r = client.post("/orders/reservations/new", data={
        "_csrf_token": tok, "product_id": str(pid), "qty": "2",
        "for_whom": "Kupac Petrović", "note": "",
    }, follow_redirects=False)
    assert r.status_code == 302
    row = _scalar(
        "SELECT for_whom, released_at FROM reservations WHERE product_id = ?;", (pid,))
    assert row["for_whom"] == "Kupac Petrović" and row["released_at"] is None
    rid = _scalar("SELECT id FROM reservations WHERE product_id = ?;", (pid,))["id"]
    r = client.post(f"/orders/reservations/{rid}/release", data={
        "_csrf_token": tok}, follow_redirects=False)
    assert r.status_code == 302
    row = _scalar("SELECT released_at FROM reservations WHERE id = ?;", (rid,))
    assert row["released_at"] is not None


def test_equipment_map_shows_custodian(client):
    from qp_crm.services import warehouse_service as wh
    login_client(client, "admin", DEFAULT_PASSWORDS["admin"])
    pid = _new_product("Map proizvod", regime="serialized")
    ok, _ = wh.register_equipment(product_id=pid, serial_number="MAP-E1")
    assert ok
    r = client.get("/orders/equipment-map")
    html = r.get_data(as_text=True)
    assert "MAP-E1" in html and "Magacin" in html
