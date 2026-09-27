"""P5 warehouse service guardrail tests.

The module's integration tests exercise the happy paths; these pin the
VALIDATION BRANCHES — the rules that keep the ledger trustworthy. Each one
corresponds to a guarantee the P5 blueprint makes:

* regime is a closed set and switching it never destroys ledger history;
* a customer custodian must name a real contact, and internal custodians
  (warehouse/scrap) must not carry a stale contact;
* scrap is terminal;
* every rejection returns (False, message) instead of raising — routes
  render these as flash errors, so a raise would be a 500;
* reads resolve names at read time and support their filters;
* duplicate serial numbers are ALLOWED (uniqueness is unenforceable in
  practice) — recorded here so nobody "fixes" it into a constraint.
"""

import pytest

from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


def _scalar(sql, params=()):
    conn = get_db()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


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
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO contacts (kind, display_name, created_at, archived) "
            "VALUES ('company', ?, datetime('now'), 0);",
            (name,),
        )
        cid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    return cid


# ---------------------------------------------------------------------------
# set_tracking_regime
# ---------------------------------------------------------------------------

def test_set_regime_rejects_unknown_value():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Regime deo")
    ok, message = wh.set_tracking_regime(pid, "teleport")
    assert not ok and "režim" in message


def test_set_regime_rejects_missing_product():
    from qp_crm.services import warehouse_service as wh
    ok, message = wh.set_tracking_regime(999999, "qty")
    assert not ok and "ne postoji" in message


def test_set_regime_persists_all_fields_and_keeps_history():
    """Switching regime must NOT delete the old ledger — the operator
    reconciles with a stocktake movement instead."""
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Regime deo 2", regime="qty")
    wh.record_movement(product_id=pid, qty=7, direction="in", reason="purchase_in")
    ok, _ = wh.set_tracking_regime(pid, "serialized", min_stock=2.0,
                                   unit_base="kom", pack_size=10.0)
    assert ok
    row = _scalar("SELECT * FROM products WHERE id = ?;", (pid,))
    assert row["tracking_regime"] == "serialized"
    assert row["min_stock"] == 2.0 and row["unit_base"] == "kom"
    assert row["pack_size"] == 10.0
    # the qty history survived the switch
    assert wh.qty_on_hand(pid) == 7


# ---------------------------------------------------------------------------
# register_equipment validation
# ---------------------------------------------------------------------------

def test_register_rejects_unknown_custodian_and_status():
    from qp_crm.services import warehouse_service as wh
    ok, message = wh.register_equipment(name_snapshot="X", custodian_type="moon")
    assert not ok and "čuvar" in message.lower()
    ok, message = wh.register_equipment(name_snapshot="X", status="exploded")
    assert not ok and "status" in message.lower()


def test_register_customer_requires_contact():
    from qp_crm.services import warehouse_service as wh
    ok, message = wh.register_equipment(name_snapshot="Bez kontakta",
                                        custodian_type="customer")
    assert not ok and "kontakt" in message.lower()


def test_register_requires_a_name():
    """No catalog product and no manual name -> rejected, not a nameless row."""
    from qp_crm.services import warehouse_service as wh
    ok, message = wh.register_equipment(name_snapshot="   ")
    assert not ok and "naziv" in message.lower()


def test_register_internal_custodian_drops_contact():
    """warehouse/scrap custodians must not keep a stale contact id."""
    from qp_crm.services import warehouse_service as wh
    cid = _new_contact("Neki kontakt")
    ok, eid = wh.register_equipment(name_snapshot="Interna mašina",
                                    custodian_type="warehouse",
                                    custodian_contact_id=cid)
    assert ok
    row = _scalar("SELECT custodian_contact_id FROM equipment WHERE id = ?;", (eid,))
    assert row["custodian_contact_id"] is None


def test_register_derives_status_from_custodian():
    """register and transition must agree: no status given -> derive from the
    custodian. Before this, register defaulted to 'in_stock' unconditionally,
    so a machine handed to a customer still claimed to be in stock."""
    from qp_crm.services import warehouse_service as wh
    cid = _new_contact("Kupac derivacija")
    ok, at_customer = wh.register_equipment(name_snapshot="Deriv kupac",
                                            custodian_type="customer",
                                            custodian_contact_id=cid)
    assert ok
    assert wh.get_equipment(at_customer)["status"] == "delivered"
    ok, scrapped = wh.register_equipment(name_snapshot="Deriv rashod",
                                         custodian_type="scrap")
    assert ok
    assert wh.get_equipment(scrapped)["status"] == "scrapped"
    ok, in_house = wh.register_equipment(name_snapshot="Deriv magacin")
    assert ok
    assert wh.get_equipment(in_house)["status"] == "in_stock"


def test_register_explicit_status_still_wins():
    """An operator who names a status (e.g. loaned) keeps it."""
    from qp_crm.services import warehouse_service as wh
    cid = _new_contact("Kupac eksplicitno")
    ok, eid = wh.register_equipment(name_snapshot="Deriv eksplicitno",
                                    custodian_type="customer",
                                    custodian_contact_id=cid,
                                    status="loaned")
    assert ok
    assert wh.get_equipment(eid)["status"] == "loaned"


def test_duplicate_serial_numbers_are_blocked_within_product():
    """2026-09-27 user request (unified intake): a serial the warehouse has
    seen must be RETURNED via transition, not silently re-registered — the
    intake form offers 'return it' and the service blocks same-product
    duplicates. Different-product copies (temp registrations, multi-site)
    remain allowed: the duplicate check is scoped to product_id."""
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Dup proizvod", regime="serialized")
    ok1, _ = wh.register_equipment(product_id=pid, serial_number="DUP-1")
    assert ok1
    # same product, case-insensitive: blocked
    ok2, msg = wh.register_equipment(product_id=pid, serial_number="dup-1")
    assert not ok2 and "već postoji" in msg
    # different product: allowed (temp/other-site copy)
    pid2 = _new_product("Dup proizvod 2", regime="serialized")
    ok3, _ = wh.register_equipment(product_id=pid2, serial_number="DUP-1")
    assert ok3
    row = _scalar("SELECT COUNT(*) AS c FROM equipment WHERE serial_number = 'DUP-1';")
    assert row["c"] == 2


def test_name_snapshot_is_frozen_from_catalog_at_registration():
    """The snapshot survives a later rename — that is its whole purpose."""
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Staro ime mašine", regime="serialized")
    ok, eid = wh.register_equipment(product_id=pid)
    assert ok
    conn = get_db()
    try:
        conn.execute("UPDATE products SET name = 'Novo ime mašine' WHERE id = ?;", (pid,))
        conn.commit()
    finally:
        conn.close()
    assert wh.get_equipment(eid)["name_snapshot"] == "Staro ime mašine"
    # ...while the live catalog name is resolved alongside it
    assert wh.get_equipment(eid)["product_name"] == "Novo ime mašine"


# ---------------------------------------------------------------------------
# transition_equipment validation
# ---------------------------------------------------------------------------

def test_transition_rejects_unknown_custodian_status_and_missing_equipment():
    from qp_crm.services import warehouse_service as wh
    ok, eid = wh.register_equipment(name_snapshot="Trans mašina")
    assert ok
    ok, message = wh.transition_equipment(eid, "moon")
    assert not ok and "čuvar" in message.lower()
    ok, message = wh.transition_equipment(eid, "warehouse", status="exploded")
    assert not ok and "status" in message.lower()
    ok, message = wh.transition_equipment(999999, "warehouse")
    assert not ok and "ne postoji" in message.lower()


def test_transition_to_customer_requires_contact():
    from qp_crm.services import warehouse_service as wh
    ok, eid = wh.register_equipment(name_snapshot="Trans mašina 2")
    assert ok
    ok, message = wh.transition_equipment(eid, "customer")
    assert not ok and "kontakt" in message.lower()


def test_transition_default_statuses():
    """warehouse->in_stock, customer->delivered, scrap->scrapped."""
    from qp_crm.services import warehouse_service as wh
    cid = _new_contact("Kupac default status")
    ok, eid = wh.register_equipment(name_snapshot="Status mašina")
    assert ok
    wh.transition_equipment(eid, "customer", custodian_contact_id=cid)
    assert wh.get_equipment(eid)["status"] == "delivered"
    wh.transition_equipment(eid, "warehouse")
    assert wh.get_equipment(eid)["status"] == "in_stock"
    wh.transition_equipment(eid, "scrap")
    assert wh.get_equipment(eid)["status"] == "scrapped"


def test_transition_reason_follows_status():
    """loan/test_demo produce their own reasons; scrap always wins."""
    from qp_crm.services import warehouse_service as wh
    cid = _new_contact("Kupac razlog")
    ok, eid = wh.register_equipment(name_snapshot="Razlog mašina")
    assert ok
    wh.transition_equipment(eid, "customer", custodian_contact_id=cid,
                            status="test_demo")
    wh.transition_equipment(eid, "scrap", status="scrapped")
    # equipment_history is OLDEST FIRST, so the scrap is the last entry --
    # this also pins the ordering contract itself.
    history = wh.equipment_history(eid)
    assert [m["reason"] for m in history] == ["test_demo", "scrap"]
    # ...and the ledger view is the exact reverse (newest first).
    ledger = wh.list_movements(equipment_id=eid)
    assert [m["reason"] for m in ledger] == ["scrap", "test_demo"]


# ---------------------------------------------------------------------------
# reads / filters
# ---------------------------------------------------------------------------

def test_equipment_list_filters_and_search():
    from qp_crm.services import warehouse_service as wh
    cid = _new_contact("Filter kupac")
    ok, eid = wh.register_equipment(name_snapshot="Filter mašina ALFA",
                                    serial_number="FLT-1",
                                    custodian_type="customer",
                                    custodian_contact_id=cid)
    assert ok
    assert any(e["id"] == eid for e in wh.list_equipment(custodian_type="customer"))
    assert any(e["id"] == eid for e in wh.list_equipment(contact_id=cid))
    assert any(e["id"] == eid for e in wh.list_equipment(search="ALFA"))
    assert any(e["id"] == eid for e in wh.list_equipment(search="FLT-1"))
    # a real status filter narrows the result set...
    delivered = wh.list_equipment(status="delivered")
    assert all(e["status"] == "delivered" for e in delivered)
    assert any(e["id"] == eid for e in delivered)
    # ...while an unknown one is ignored rather than returning nothing
    assert any(e["id"] == eid for e in wh.list_equipment(status="bogus"))


def test_reservation_rejects_missing_product():
    from qp_crm.services import warehouse_service as wh
    ok, message = wh.create_reservation(product_id=999999, qty=1, for_whom="X")
    assert not ok and "ne postoji" in message


def test_reservations_filter_by_product():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Rez filter deo", regime="qty")
    other = _new_product("Rez filter deo 2", regime="qty")
    ok, rid = wh.create_reservation(product_id=pid, qty=2, for_whom="Filter X")
    assert ok
    mine = wh.list_reservations(active_only=True, product_id=pid)
    assert [r["id"] for r in mine] == [rid]
    assert wh.list_reservations(active_only=True, product_id=other) == []


def test_movements_filters_by_product_and_equipment():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Filter deo", regime="qty")
    wh.record_movement(product_id=pid, qty=3, direction="in", reason="purchase_in")
    assert len(wh.list_movements(product_id=pid)) == 1
    ok, eid = wh.register_equipment(name_snapshot="Filter mašina BETA")
    assert ok
    wh.transition_equipment(eid, "scrap")
    assert len(wh.list_movements(equipment_id=eid)) == 1


def test_list_shortfalls_active_filter():
    from qp_crm.services import warehouse_service as wh
    ok, eid = wh.register_equipment(name_snapshot="Dug mašina")
    assert ok
    ok, sid = wh.create_shortfall(eid, part_name="Deo X")
    assert ok
    assert len(wh.list_shortfalls(equipment_id=eid, active_only=True)) == 1
    wh.close_shortfall(sid)
    assert len(wh.list_shortfalls(equipment_id=eid, active_only=True)) == 0
    assert len(wh.list_shortfalls(equipment_id=eid)) == 1  # row still there


def test_close_shortfall_rejects_already_closed():
    from qp_crm.services import warehouse_service as wh
    ok, eid = wh.register_equipment(name_snapshot="Dug mašina 2")
    assert ok
    ok, sid = wh.create_shortfall(eid, part_name="Deo Y")
    wh.close_shortfall(sid)
    ok, message = wh.close_shortfall(sid)
    assert not ok and "nije otvoren" in message


def test_create_shortfall_requires_part_name_or_product():
    from qp_crm.services import warehouse_service as wh
    ok, eid = wh.register_equipment(name_snapshot="Dug mašina 3")
    assert ok
    ok, message = wh.create_shortfall(eid, part_name="  ")
    assert not ok and "naziv" in message.lower()
    ok, message = wh.create_shortfall(999999, part_name="Deo")
    assert not ok and "ne postoji" in message.lower()


def test_create_shortfall_uses_catalog_name_when_id_given():
    from qp_crm.services import warehouse_service as wh
    part = _new_product("Ležaj iz kataloga")
    ok, eid = wh.register_equipment(name_snapshot="Dug mašina 4")
    ok, sid = wh.create_shortfall(eid, part_product_id=part)
    assert ok
    rows = wh.list_shortfalls(equipment_id=eid)
    assert rows[0]["part_name"] == "Ležaj iz kataloga"
    assert rows[0]["part_product_name"] == "Ležaj iz kataloga"


# ---------------------------------------------------------------------------
# reservations
# ---------------------------------------------------------------------------

def test_reservation_rejects_non_qty_product_and_unknown_targets():
    from qp_crm.services import warehouse_service as wh
    untracked = _new_product("Rez untracked")
    ok, message = wh.create_reservation(product_id=untracked, qty=1, for_whom="X")
    assert not ok and "qty" in message
    zero = _new_product("Rez nula", regime="qty")
    ok, message = wh.create_reservation(product_id=zero, qty=0, for_whom="X")
    assert not ok and "veća od nule" in message
    ok, message = wh.create_reservation(equipment_id=999999, for_whom="X")
    assert not ok and "ne postoji" in message


def test_reserve_a_specific_machine_and_list_with_names():
    from qp_crm.services import warehouse_service as wh
    ok, eid = wh.register_equipment(name_snapshot="Rezervisana mašina",
                                    serial_number="REZ-1")
    assert ok
    ok, rid = wh.create_reservation(equipment_id=eid, for_whom="Za posao 42")
    assert ok
    rows = [r for r in wh.list_reservations(active_only=True) if r["id"] == rid]
    assert rows and rows[0]["equipment_name"] == "Rezervisana mašina"
    assert rows[0]["for_whom"] == "Za posao 42"
    # released reservations drop out of the active list but stay listable
    wh.release_reservation(rid)
    assert not [r for r in wh.list_reservations(active_only=True) if r["id"] == rid]
    assert [r for r in wh.list_reservations(active_only=False) if r["id"] == rid]


# ---------------------------------------------------------------------------
# movements
# ---------------------------------------------------------------------------

def test_record_movement_validation_branches():
    from qp_crm.services import warehouse_service as wh
    ok, message = wh.record_movement(direction="sideways", reason="sale",
                                     name_snapshot="X")
    assert not ok and "smer" in message.lower()
    ok, message = wh.record_movement(direction="in", reason="teleport",
                                     name_snapshot="X")
    assert not ok and "razlog" in message.lower()
    ok, message = wh.record_movement(direction="in", reason="sale")
    assert not ok and "proizvod" in message.lower()
    ok, message = wh.record_movement(product_id=999999, qty=1, direction="in",
                                     reason="purchase_in")
    assert not ok and "ne postoji" in message.lower()


def test_temp_product_movement_needs_no_catalog_row():
    from qp_crm.services import warehouse_service as wh
    ok, mid = wh.record_movement(name_snapshot="Ad-hoc šraf", qty=4,
                                 direction="in", reason="purchase_in")
    assert ok
    rows = wh.list_movements()
    row = [m for m in rows if m["id"] == mid][0]
    assert row["product_id"] is None and row["name_snapshot"] == "Ad-hoc šraf"


def test_movement_records_counterparty_for_read_time_resolution():
    from qp_crm.services import warehouse_service as wh
    cid = _new_contact("Dobavljač d.o.o.")
    pid = _new_product("Nabavni deo", regime="qty")
    ok, mid = wh.record_movement(product_id=pid, qty=10, direction="in",
                                 reason="purchase_in", contact_id=cid)
    assert ok
    row = [m for m in wh.list_movements(product_id=pid) if m["id"] == mid][0]
    assert row["contact_name"] == "Dobavljač d.o.o."
    assert row["product_name"] == "Nabavni deo"


def test_scrap_movement_reduces_qty_balance():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Rashod deo", regime="qty")
    wh.record_movement(product_id=pid, qty=10, direction="in", reason="purchase_in")
    wh.record_movement(product_id=pid, qty=4, direction="out", reason="scrap")
    assert wh.qty_on_hand(pid) == 6


# ---------------------------------------------------------------------------
# intake_inbound / outtake (unified form services, user request 2026-09-27)
# ---------------------------------------------------------------------------

def test_intake_inbound_qty_validation():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Intake qty guard", regime="qty")
    ok, msg = wh.intake_inbound(pid, qty="nije-broj")
    assert not ok and "broj" in msg
    ok, msg = wh.intake_inbound(pid, qty="0")
    assert not ok and "veća od nule" in msg
    ok, msg = wh.intake_inbound(pid, qty="3")
    assert ok


def test_intake_inbound_rejects_untracked_and_bad_reason():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Intake untracked")  # untracked default
    ok, msg = wh.intake_inbound(pid, qty="1")
    assert not ok and "praćenje" in msg
    pid_q = _new_product("Intake bad reason", regime="qty")
    ok, msg = wh.intake_inbound(pid_q, qty="1", reason="nepoznat")
    assert not ok and "Nepoznat razlog" in msg


def test_intake_inbound_serialized_requires_serials():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Intake no serials", regime="serialized")
    ok, msg = wh.intake_inbound(pid, serial_numbers=["", "  "])
    assert not ok and "serijski" in msg.lower()


def test_intake_inbound_unknown_product():
    from qp_crm.services import warehouse_service as wh
    ok, msg = wh.intake_inbound(999999, qty="1")
    assert not ok and "ne postoji" in msg


def test_outtake_qty_requires_positive_number():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Outtake qty guard", regime="qty")
    ok, msg = wh.outtake(pid, qty="-2")
    assert not ok
    ok, msg = wh.outtake(pid, qty=None)
    assert not ok


def test_outtake_serialized_scrapped_rejected():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Outtake scrap guard", regime="serialized")
    ok, eid = wh.register_equipment(product_id=pid, serial_number="SCR-1")
    assert ok
    ok, _ = wh.transition_equipment(eid, custodian_type="scrap")
    assert ok
    ok, msg = wh.outtake(pid, serial_numbers=["SCR-1"], reason="sale")
    assert not ok and "rashodovana" in msg.lower()


def test_outtake_reason_maps_to_status():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Outtake status map", regime="serialized")
    cust = _new_contact("Kupac mapiranje")
    ok, eid = wh.register_equipment(product_id=pid, serial_number="MAP-1")
    assert ok
    ok, _ = wh.outtake(pid, serial_numbers=["MAP-1"], reason="loan",
                       contact_id=cust)
    assert ok
    assert wh.get_equipment(eid)["status"] == "loaned"


def test_intake_inbound_return_reason_known_serial():
    """Return flow: known machine back in — transition, not new row."""
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Intake return flow", regime="serialized")
    ok, eid = wh.register_equipment(product_id=pid, serial_number="RET-1")
    assert ok
    ok, _ = wh.transition_equipment(eid, custodian_type="scrap")
    assert ok
    # scrapped machine cannot come back through intake either
    ok, msg = wh.intake_inbound(pid, serial_numbers=["RET-1"], reason="return")
    assert not ok and "Rashodovana" in msg


def test_outtake_qty_happy_path_and_bad_reason():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Outtake qty happy", regime="qty")
    ok, msg = wh.outtake(pid, qty="2", reason="nepoznat")
    assert not ok and "Nepoznat razlog" in msg
    ok, result = wh.outtake(pid, qty="2", reason="sale")
    assert ok and result["product_name"] == "Outtake qty happy"
    assert wh.qty_on_hand(pid) == -2


def test_outtake_untracked_rejected():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Outtake untracked")
    ok, msg = wh.outtake(pid, qty="1")
    assert not ok and "praćenje" in msg


def test_outtake_qty_non_numeric_and_zero():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Outtake qty edge", regime="qty")
    ok, msg = wh.outtake(pid, qty="abc", reason="sale")
    assert not ok and "broj" in msg
    ok, msg = wh.outtake(pid, qty="0", reason="sale")
    assert not ok and "veća od nule" in msg


def test_outtake_serialized_empty_serials_and_dupe():
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Outtake serial edges", regime="serialized")
    ok, msg = wh.outtake(pid, serial_numbers=[""], reason="sale")
    assert not ok and "serijski" in msg.lower()
    ok, _ = wh.register_equipment(product_id=pid, serial_number="DUP-OUT")
    assert ok
    ok, msg = wh.outtake(pid, serial_numbers=["DUP-OUT", "dup-out"], reason="sale")
    assert not ok and "dva puta" in msg


def test_intake_inbound_duplicate_across_known_and_new():
    """Mixed intake: one known serial (returns) + one new (registers)."""
    from qp_crm.services import warehouse_service as wh
    pid = _new_product("Intake mixed", regime="serialized")
    ok, eid = wh.register_equipment(product_id=pid, serial_number="MIX-1")
    assert ok
    ok, _ = wh.transition_equipment(eid, custodian_type="customer",
                                    custodian_contact_id=_new_contact("Mix kupac"))
    assert ok
    ok, result = wh.intake_inbound(pid, serial_numbers=["MIX-1", "MIX-2"])
    assert ok
    assert result["returned"] == 1 and result["registered"] == 1
    assert wh.warehouse_equipment_count(pid) == 2
