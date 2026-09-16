"""Phase 4 (deals spine) service tests.

Pinned behavior of qp_crm/services/deal_service.py:

* deal codes allocate per-year (D-YYYY-NNN) from the deal_counters row,
  strictly increasing, and survive a counter-row race via UNIQUE(code);
* deal status is DERIVED (never stored): new -> offered (offer linked)
  -> won (accepted-offer decision event) -> closed (hand close wins);
* customers archive, never delete; locations validate ownership;
* the timeline records every state change (creation, links, acceptance).

The service layer is exercised directly against the throwaway DB --
HTTP-level coverage lives in tests/smoke/test_deals_pages.py.
"""

import pytest

from qp_crm.services import deal_service


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


@pytest.fixture()
def customer_id():
    ok, cid = deal_service.create_customer("Test Kupac d.o.o.", pib="100001234",
                                           mb="20000123", city="Novi Sad")
    assert ok, cid
    return cid


def test_deal_codes_increment_per_year(customer_id):
    ok1, d1 = deal_service.create_deal(customer_id, "Prvi posao")
    ok2, d2 = deal_service.create_deal(customer_id, "Drugi posao")
    assert ok1 and ok2
    c1 = deal_service.get_deal(d1)["code"]
    c2 = deal_service.get_deal(d2)["code"]
    year = c1.split("-")[1]
    assert c1.startswith(f"D-{year}-")
    assert c2.startswith(f"D-{year}-")
    assert int(c1.split("-")[2]) < int(c2.split("-")[2])


def test_deal_counter_resumes_after_reboot(temp_db, customer_id):
    """deal_counters is the single arbiter: a new boot (init re-run) must
    NOT reset the numbering."""
    ok, d1 = deal_service.create_deal(customer_id, "Pre restarta")
    code1 = deal_service.get_deal(d1)["code"]

    from qp_crm.deals.app import init_db
    init_db()  # idempotent boot replay

    ok2, d2 = deal_service.create_deal(customer_id, "Posle restarta")
    code2 = deal_service.get_deal(d2)["code"]
    assert int(code1.split("-")[2]) < int(code2.split("-")[2])


def test_deal_requires_customer_and_title():
    assert deal_service.create_deal(999999, "X") == (False, "Customer not found.")
    ok, cid = deal_service.create_customer("No Title d.o.o.")
    assert deal_service.create_deal(cid, "   ")[0] is False


def test_location_must_belong_to_customer(customer_id):
    ok, loc = deal_service.create_location(customer_id, "Radionica A")
    assert ok
    ok2, cid2 = deal_service.create_customer("Drugi Kupac d.o.o.")
    assert deal_service.create_deal(cid2, "Pogrešna lokacija",
                                    location_id=loc) == \
        (False, "Location does not belong to this customer.")


def test_customer_archive_not_delete(customer_id):
    ok, _ = deal_service.set_customer_archived(customer_id, True)
    assert ok
    row = deal_service.get_customer(customer_id)
    assert row["archived"] == 1  # row still exists -- no delete path
    # default lists hide archived, explicit include shows it
    assert deal_service.get_customer(customer_id)["name"]
    listed = [c["id"] for c in deal_service.list_customers(include_archived=True)]
    assert customer_id in listed
    assert customer_id not in [c["id"] for c in deal_service.list_customers()]


def test_derived_status_lifecycle(customer_id):
    ok, deal_id = deal_service.create_deal(customer_id, "Lifecycle posao")
    assert deal_service.derive_status(deal_id) == "new"

    # link an offer directly (as the offer route would)
    from qp_crm.shared.db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO offers (offer_number, date, client_name, currency, total_gross) "
        "VALUES ('P4-LC-1', '2026-09-16', 'Test Kupac d.o.o.', 'EUR', 1000.0);")
    offer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("UPDATE offers SET deal_id = ? WHERE id = ?;", (deal_id, offer_id))
    conn.commit()
    conn.close()
    assert deal_service.derive_status(deal_id) == "offered"

    # acceptance tap -> won
    ok, _ = deal_service.record_offer_accepted(deal_id, offer_id)
    assert ok
    assert deal_service.derive_status(deal_id) == "won"

    # hand close -> closed (close wins while closed_at is set)
    deal_service.close_deal(deal_id, True)
    assert deal_service.derive_status(deal_id) == "closed"

    # reopen -> back to the link-derived status (won: the event remains)
    deal_service.close_deal(deal_id, False)
    assert deal_service.derive_status(deal_id) == "won"


def test_unlink_reverts_status(customer_id):
    ok, deal_id = deal_service.create_deal(customer_id, "Unlink posao")
    from qp_crm.shared.db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO offers (offer_number, date, client_name) "
        "VALUES ('P4-UL-1', '2026-09-16', 'Test Kupac d.o.o.');")
    offer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("UPDATE offers SET deal_id = ? WHERE id = ?;", (deal_id, offer_id))
    conn.commit()
    conn.close()
    assert deal_service.derive_status(deal_id) == "offered"

    # unlink -> back to new (the link event remains in the timeline, but
    # no offer is linked any more)
    conn = get_db()
    conn.execute("UPDATE offers SET deal_id = NULL WHERE id = ?;", (offer_id,))
    conn.commit()
    conn.close()
    assert deal_service.derive_status(deal_id) == "new"


def test_creation_opens_the_timeline(customer_id):
    ok, deal_id = deal_service.create_deal(customer_id, "Timeline posao")
    events = deal_service.list_events(deal_id)
    assert len(events) == 1
    assert events[0]["event_type"] == "note"
    assert "Timeline posao" in events[0]["body"]


def test_event_type_validation(customer_id):
    ok, deal_id = deal_service.create_deal(customer_id, "Event posao")
    assert deal_service.add_event(deal_id, "bogus_type", "x")[0] is False
    ok, eid = deal_service.add_event(deal_id, "call", "zvao kupac")
    assert ok
    events = deal_service.list_events(deal_id)
    assert events[-1]["event_type"] == "call"


def test_pipeline_groups_by_derived_status(customer_id):
    ok, deal_id = deal_service.create_deal(customer_id, "Pipeline posao")
    from qp_crm.shared.db import get_db
    conn = get_db()
    conn.execute(
        "INSERT INTO offers (offer_number, date, client_name, currency, total_gross, deal_id) "
        "VALUES ('P4-PL-1', '2026-09-16', 'Test Kupac d.o.o.', 'EUR', 2500.0, ?);",
        (deal_id,))
    conn.commit()
    conn.close()

    board = deal_service.pipeline_board()
    assert deal_id in [d["id"] for d in board["offered"]]
    # per-deal offer value, per currency, computed at read time
    entry = next(d for d in board["offered"] if d["id"] == deal_id)
    assert entry["offer_values"] == [{"currency": "EUR", "value": 2500.0}]


def test_rename_customer_resolves_live(customer_id):
    """Rename is safe by design: everything links by id, names resolve at
    read time (blueprint §4 alias/merge rule)."""
    ok, deal_id = deal_service.create_deal(customer_id, "Rename posao")
    deal_service.update_customer(customer_id, "Preimenovano a.d.")
    assert deal_service.get_deal(deal_id)["customer_name"] == "Preimenovano a.d."
