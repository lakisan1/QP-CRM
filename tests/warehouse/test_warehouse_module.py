"""P5 warehouse module integration tests.

Pins the module end to end through the real app (login → page → form),
the regime gate, the no-delete rules, and the coverage math:

* staff WITHOUT the warehouse grant get 403; admin bypasses;
* equipment registration (catalog + temp), transition (custody change
  writes the evidence movement), scrap-then-reuse rejection;
* qty movement ledger (Σin − Σout), untracked rejection,
  stocktake_adjustment requires a note;
* reservations: for_whom required, exactly one subject, release sets
  released_at (row stays);
* shortfalls: create from machine page, close (row stays);
* coverage/ATP: available = on_hand − reserved; serialized count =
  warehouse instances; untracked products invisible.
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
    c.get("/login")  # establish the session CSRF token
    with c.session_transaction() as session:
        session["_csrf_token"] = session.get("_csrf_token") or "tok"
    return c


def _scalar(sql, params=()):
    """One value from a short-lived connection (ALWAYS closed — a leaked
    connection holds a read lock and makes the next write 'database is
    locked' under WAL)."""
    conn = get_db()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def _admin(client):
    login_client(client, "admin", DEFAULT_PASSWORDS["admin"])


def _user_id(username):
    return _scalar("SELECT id FROM users WHERE username = ?;", (username,))["id"]


def _grant_warehouse(username):
    from qp_crm.shared.auth import get_user_modules, set_user_modules
    uid = _user_id(username)
    modules = sorted(set(get_user_modules(uid)) | {"warehouse"})
    set_user_modules(uid, modules)
    return uid


def _new_product(name, regime="untracked"):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (name, item_type, tracking_regime) VALUES (?, 'proizvod', ?);",
            (name, regime),
        )
        pid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return pid


def _new_contact(name):
    """A real directory row — custody transitions to a customer reference
    contacts(id) and FK enforcement is ON in the test DB."""
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO contacts (kind, display_name, created_at, archived)
            VALUES ('company', ?, datetime('now'), 0);
            """,
            (name,),
        )
        cid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return cid


# ---------------------------------------------------------------------------
# access
# ---------------------------------------------------------------------------

def _staff_without_warehouse(client):
    """A staff user with all modules EXCEPT warehouse (the 403 fixture)."""
    login_client(client, "rent")
    from qp_crm.shared.auth import get_user_modules, set_user_modules
    uid = _user_id("rent")
    modules = [m for m in get_user_modules(uid) if m != "warehouse"]
    set_user_modules(uid, modules)


def test_staff_without_grant_gets_403(client):
    _staff_without_warehouse(client)
    assert client.get("/warehouse/equipment").status_code == 403


def test_staff_with_grant_sees_pages(client):
    login_client(client, "rent")
    _grant_warehouse("rent")
    for path in ("/warehouse/equipment", "/warehouse/movements",
                 "/warehouse/reservations", "/warehouse/coverage",
                 "/warehouse/equipment/new", "/warehouse/movements/new",
                 "/warehouse/reservations/new"):
        assert client.get(path).status_code == 200, path


def test_admin_bypasses_grant(client):
    _admin(client)
    assert client.get("/warehouse/equipment").status_code == 200


def test_anonymous_redirects_to_login(client):
    r = client.get("/warehouse/equipment")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


# ---------------------------------------------------------------------------
# equipment
# ---------------------------------------------------------------------------

def test_register_equipment_with_catalog_product(client):
    _admin(client)
    pid = _new_product("Dizalica P5T")
    tok = csrf_token_for(client)
    r = client.post("/warehouse/equipment/new", data={
        "_csrf_token": tok,
        "product_id": str(pid),
        "serial_number": "SN-001",
        "custodian_type": "warehouse",
        "status": "in_stock",
    })
    assert r.status_code == 302
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM equipment WHERE serial_number = 'SN-001';").fetchone()
    conn.close()
    assert row is not None
    assert row["product_id"] == pid
    assert row["name_snapshot"] == "Dizalica P5T"  # resolved from catalog
    assert row["custodian_type"] == "warehouse"


def test_register_temp_equipment_without_catalog(client):
    _admin(client)
    tok = csrf_token_for(client)
    client.post("/warehouse/equipment/new", data={
        "_csrf_token": tok,
        "name_snapshot": "Ad-hoc kolica",
        "custodian_type": "warehouse",
    })
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM equipment WHERE name_snapshot = 'Ad-hoc kolica';").fetchone()
    conn.close()
    assert row is not None and row["product_id"] is None


def test_transition_writes_evidence_movement(client):
    _admin(client)
    pid = _new_product("PTI lanac P5T")
    cust = _new_contact("Kupac Transition DOO")
    tok = csrf_token_for(client)
    client.post("/warehouse/equipment/new", data={
        "_csrf_token": tok, "product_id": str(pid),
        "serial_number": "SN-TR", "custodian_type": "warehouse"})
    eid = _scalar(
        "SELECT id FROM equipment WHERE serial_number='SN-TR';")["id"]
    r = client.post(f"/warehouse/equipment/{eid}/transition", data={
        "_csrf_token": tok, "custodian_type": "customer",
        "custodian_contact_id": str(cust), "status": "loaned",
        "note": "posuđen firmi XYZ"})
    assert r.status_code == 302
    conn = get_db()
    eq = conn.execute(
        "SELECT * FROM equipment WHERE id = ?;", (eid,)).fetchone()
    mv = conn.execute(
        "SELECT * FROM stock_movements WHERE equipment_id = ? ORDER BY id DESC LIMIT 1;",
        (eid,)).fetchone()
    conn.close()
    assert eq["custodian_type"] == "customer" and eq["status"] == "loaned"
    assert mv["direction"] == "out" and mv["reason"] == "loan"


def test_scrapped_cannot_return_to_circulation(client):
    _admin(client)
    tok = csrf_token_for(client)
    client.post("/warehouse/equipment/new", data={
        "_csrf_token": tok, "name_snapshot": "Staro kolo",
        "custodian_type": "warehouse"})
    eid = _scalar(
        "SELECT id FROM equipment WHERE name_snapshot='Staro kolo';")["id"]
    client.post(f"/warehouse/equipment/{eid}/transition", data={
        "_csrf_token": tok, "custodian_type": "scrap"})
    r = client.post(f"/warehouse/equipment/{eid}/transition", data={
        "_csrf_token": tok, "custodian_type": "warehouse"})
    assert r.status_code == 302  # redirect back with the flash error
    eq = _scalar("SELECT custodian_type FROM equipment WHERE id = ?;", (eid,))
    assert eq["custodian_type"] == "scrap"


# ---------------------------------------------------------------------------
# movements
# ---------------------------------------------------------------------------

def test_qty_movement_ledger_balance():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Vijak M8", regime="qty")
    ok, _ = wh.record_movement(product_id=pid, qty=100, direction="in",
                               reason="purchase_in")
    assert ok
    ok, _ = wh.record_movement(product_id=pid, qty=30, direction="out",
                               reason="free_issue")
    assert ok
    assert wh.qty_on_hand(pid) == 70


def test_untracked_product_rejected():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Nepraćeni deo")
    ok, message = wh.record_movement(product_id=pid, qty=5, direction="in",
                                     reason="purchase_in")
    assert not ok and "qty" in message


def test_stocktake_adjustment_requires_note():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Kabal 5m", regime="qty")
    ok, message = wh.record_movement(product_id=pid, qty=2, direction="out",
                                     reason="stocktake_adjustment")
    assert not ok and "napomenu" in message.lower() or "napomena" in message.lower()


def test_movement_form_roundtrip(client):
    _admin(client)
    pid = _new_product("Ulje 1L", regime="qty")
    tok = csrf_token_for(client)
    r = client.post("/warehouse/movements/new", data={
        "_csrf_token": tok, "product_id": str(pid), "qty": "12",
        "direction": "in", "reason": "purchase_in"})
    assert r.status_code == 302
    assert _scalar(
        "SELECT COUNT(*) AS c FROM stock_movements WHERE product_id = ?;",
        (pid,))["c"] == 1


# ---------------------------------------------------------------------------
# reservations
# ---------------------------------------------------------------------------

def test_reservation_requires_for_whom():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Rezervisan deo", regime="qty")
    ok, message = wh.create_reservation(product_id=pid, qty=3)
    assert not ok and "za koga" in message


def test_reservation_exactly_one_subject():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Rez deo 2", regime="qty")
    ok, _ = wh.create_reservation(product_id=pid, equipment_id=1, qty=1,
                                  for_whom="X")
    assert not ok
    ok, rid = wh.create_reservation(product_id=pid, qty=2, for_whom="Delta LLC")
    assert ok


def test_release_sets_released_at_row_stays():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Rez deo 3", regime="qty")
    ok, rid = wh.create_reservation(product_id=pid, qty=1, for_whom="Job 9")
    ok, _ = wh.release_reservation(rid)
    assert ok
    row = _scalar("SELECT released_at FROM reservations WHERE id = ?;", (rid,))
    assert row["released_at"] is not None  # row stays, flagged released
    ok, _ = wh.release_reservation(rid)
    assert not ok  # double release rejected


def test_atp_available_minus_reserved():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("ATP deo", regime="qty")
    wh.record_movement(product_id=pid, qty=10, direction="in", reason="purchase_in")
    wh.create_reservation(product_id=pid, qty=4, for_whom="Kupac A")
    assert wh.product_available(pid) == 6


# ---------------------------------------------------------------------------
# shortfalls
# ---------------------------------------------------------------------------

def test_shortfall_create_and_close():
    from qp_crm.services import warehouse_service as wh
    ok, eid = wh.register_equipment(name_snapshot="Mašina D")
    assert ok
    ok, sid = wh.create_shortfall(eid, part_name="Ležaj 6204", po_ref="PO-1")
    assert ok
    assert wh.open_shortfall_count(eid) == 1
    ok, _ = wh.close_shortfall(sid)
    assert ok
    assert wh.open_shortfall_count(eid) == 0
    # row stays (no deletes)
    row = _scalar(
        "SELECT closed_at FROM equipment_shortfalls WHERE id = ?;", (sid,))
    assert row["closed_at"] is not None


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------

def test_coverage_rows_gate_untracked():
    from qp_crm.services import warehouse_service as wh
    _new_product("Untracked X")  # stays untracked
    pid_q = _new_product("Tracked Q", regime="qty")
    wh.record_movement(product_id=pid_q, qty=5, direction="in", reason="purchase_in")
    pid_s = _new_product("Tracked S", regime="serialized")
    wh.register_equipment(product_id=pid_s, serial_number="S-1")
    wh.register_equipment(product_id=pid_s, serial_number="S-2")
    rows = {r["id"]: r for r in wh.coverage_rows()}
    assert "Untracked X" not in {r["name"] for r in rows.values()}
    assert rows[pid_q]["available"] == 5
    assert rows[pid_s]["warehouse_count"] == 2


def test_serialized_count_equals_instances():
    """Acceptance: serialized count = instance count (derived, no ledger)."""
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Ser. masina B", regime="serialized")
    cust = _new_contact("Kupac Serijski DOO")
    ok, _ = wh.register_equipment(product_id=pid, serial_number="A")
    assert ok
    ok, _ = wh.register_equipment(product_id=pid, serial_number="B")
    assert ok
    ok, eid = wh.register_equipment(product_id=pid, serial_number="C")
    assert ok
    # C leaves the warehouse on loan to a real contact (FK enforced)
    ok, _ = wh.transition_equipment(eid, "customer", custodian_contact_id=cust)
    assert ok
    assert wh.warehouse_equipment_count(pid) == 2
