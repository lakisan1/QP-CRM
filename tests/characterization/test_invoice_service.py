"""Phase 4.x (invoices + payments) service tests.

Pinned behavior of qp_crm/services/invoice_service.py plus the paid
extension of deal_service.derived_status:

* invoice codes allocate from the GLOBAL per-year bucket (F-YYYY-NNN) --
  user decision 2026-09-16, one sequence for all invoices;
* issuance COPIES the offer's frozen client snapshot + item lines
  (issuance-time snapshot, blueprint §4) and takes the gross from the
  offer ITEMS (the offer row's total_gross stays 0 until an edit
  recalculates);
* one live invoice per offer (re-issue only after void);
* payments: positive amounts only, voided invoices closed; a deal is
  'paid' when >=1 non-voided invoice exists and every one is covered;
* precedence closed > paid > won > offered > new.
"""

import pytest

from qp_crm.services import deal_service, invoice_service
from qp_crm.shared.db import get_db


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


def _make_won_deal(name, title, gross=1200.0, item_gross=None):
    """customer -> deal -> offer(+items) -> acceptance tap. Returns ids."""
    ok, cid = deal_service.create_customer(name)
    assert ok, cid
    ok, did = deal_service.create_deal(cid, title)
    assert ok, did
    conn = get_db()
    conn.execute(
        "INSERT INTO offers (offer_number, date, client_name, client_pib, "
        "client_address, currency) VALUES (?, '2026-09-16', ?, '100222333', "
        "'Adresa 1', 'EUR');",
        (f"OFF-{did}", name),
    )
    offer_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("UPDATE offers SET deal_id = ? WHERE id = ?;", (did, offer_id))
    conn.execute(
        "INSERT INTO offer_items (offer_id, line_order, item_name, quantity, "
        "unit_price, discount_percent, line_net) VALUES (?, 0, 'Lift', 1, ?, 0, ?);",
        (offer_id, item_gross or gross, item_gross or gross),
    )
    conn.commit()
    conn.close()
    ok, _ = deal_service.record_offer_accepted(did, offer_id)
    assert ok
    return did, offer_id


def test_invoice_codes_global_per_year():
    """F-YYYY-NNN from ONE global bucket (no per-customer series)."""
    d1, o1 = _make_won_deal("Inv Kupac A", "Global bucket 1")
    d2, o2 = _make_won_deal("Inv Kupac B", "Global bucket 2")
    ok1, inv1 = invoice_service.issue_invoice_from_offer(d1, o1)
    ok2, inv2 = invoice_service.issue_invoice_from_offer(d2, o2)
    assert ok1 and ok2
    c1 = invoice_service.invoice_with_details(inv1)["invoice"]["code"]
    c2 = invoice_service.invoice_with_details(inv2)["invoice"]["code"]
    year = c1.split("-")[1]
    assert c1.startswith(f"F-{year}-") and c2.startswith(f"F-{year}-")
    assert int(c1.split("-")[2]) < int(c2.split("-")[2])


def test_invoice_counter_survives_boot_replay():
    ok, did = deal_service.create_customer("Boot Kupac")
    did, offer_id = _make_won_deal("Boot Kupac", "Boot replay deal")
    ok, inv = invoice_service.issue_invoice_from_offer(did, offer_id)
    code1 = invoice_service.invoice_with_details(inv)["invoice"]["code"]

    from qp_crm.deals.app import init_db
    init_db()  # idempotent boot replay

    ok2, did2 = deal_service.create_customer("Boot Kupac")
    did2, offer2 = _make_won_deal("Boot Kupac", "Boot replay deal 2")
    ok3, inv2 = invoice_service.issue_invoice_from_offer(did2, offer2)
    code2 = invoice_service.invoice_with_details(inv2)["invoice"]["code"]
    assert int(code1.split("-")[2]) < int(code2.split("-")[2])


def test_issuance_copies_snapshot_and_items():
    did, offer_id = _make_won_deal("Snapshot Kupac", "Snapshot deal")
    # _make_won_deal already inserted one line; add a second so the copy
    # demonstrably preserves order
    conn = get_db()
    conn.execute(
        "INSERT INTO offer_items (offer_id, line_order, item_name, "
        "item_description, quantity, unit_price, discount_percent, line_net) "
        "VALUES (?, 1, 'Traka', 'PTI traka 2m', 2, 500.0, 0, 1000.0);",
        (offer_id,),
    )
    conn.commit()
    conn.close()

    ok, inv = invoice_service.issue_invoice_from_offer(did, offer_id)
    assert ok, inv
    det = invoice_service.invoice_with_details(inv)
    assert det["invoice"]["client_name"] == "Snapshot Kupac"
    assert det["invoice"]["client_pib"] == "100222333"
    assert det["invoice"]["source_offer_id"] == offer_id
    assert det["invoice"]["deal_id"] == did
    assert len(det["items"]) == 2
    assert det["items"][1]["description"] == "Traka"
    assert det["items"][1]["qty"] == 2
    # gross = sum of BOTH item lines (1200 default + 1000 added)
    assert det["invoice"]["total_gross"] == 2200.0


def test_one_live_invoice_per_offer():
    did, offer_id = _make_won_deal("Dup Kupac", "Dup invoice deal")
    ok1, inv1 = invoice_service.issue_invoice_from_offer(did, offer_id)
    assert ok1
    ok2, msg = invoice_service.issue_invoice_from_offer(did, offer_id)
    assert ok2 is False
    assert "already has an invoice" in msg
    # after void the offer can be re-invoiced
    invoice_service.void_invoice(inv1)
    ok3, inv2 = invoice_service.issue_invoice_from_offer(did, offer_id)
    assert ok3


def test_issue_requires_offer_on_deal():
    ok, did = deal_service.create_customer("Wrong Kupac")
    did, offer_id = _make_won_deal("Wrong Kupac", "Wrong deal")
    ok2, did2 = deal_service.create_customer("Drugi Kupac")
    ok3, did3 = deal_service.create_deal(  # noqa: F841
        deal_service.get_customer(2)["id"], "Strani posao")
    ok4, msg = invoice_service.issue_invoice_from_offer(did3, offer_id)
    assert ok4 is False
    assert "not found on this deal" in msg


def test_paid_derivation_matrix():
    did, offer_id = _make_won_deal("Paid Kupac", "Paid matrix deal", gross=1000.0)
    assert deal_service.derive_status(did) == "won"

    ok, inv = invoice_service.issue_invoice_from_offer(did, offer_id)
    assert deal_service.derive_status(did) == "won"  # invoiced != paid

    invoice_service.record_payment(inv, 400.0)
    assert deal_service.derive_status(did) == "won"  # partial

    invoice_service.record_payment(inv, 600.0)
    assert deal_service.derive_status(did) == "paid"  # covered

    # void -> back to won (nothing payable left)
    invoice_service.void_invoice(inv)
    assert deal_service.derive_status(did) == "won"


def test_payment_validation():
    did, offer_id = _make_won_deal("Valid Kupac", "Valid deal")
    ok, inv = invoice_service.issue_invoice_from_offer(did, offer_id)
    assert invoice_service.record_payment(inv, 0) == (False, "Payment amount must be positive.")
    assert invoice_service.record_payment(inv, -5)[0] is False
    assert invoice_service.record_payment(inv, "abc")[0] is False
    assert invoice_service.record_payment(999999, 10.0) == (False, "Invoice not found.")


def test_voided_invoice_stops_counting():
    did, offer_id = _make_won_deal("Void Kupac", "Void counting deal")
    ok, inv = invoice_service.issue_invoice_from_offer(did, offer_id)
    invoice_service.record_payment(inv, 1200.0)
    assert deal_service.derive_status(did) == "paid"
    invoice_service.void_invoice(inv)
    assert deal_service.derive_status(did) == "won"
    # payments on a voided invoice are rejected (money frozen for audit)
    assert invoice_service.record_payment(inv, 10.0) == \
        (False, "Invoice is voided -- payments are closed.")


def test_overpay_marks_paid_and_keeps_payment():
    did, offer_id = _make_won_deal("Over Kupac", "Overpay deal", gross=100.0)
    ok, inv = invoice_service.issue_invoice_from_offer(did, offer_id)
    invoice_service.record_payment(inv, 150.0)  # overpay counts as covered
    det = invoice_service.invoice_with_details(inv)
    assert det["is_paid"] is True
    assert deal_service.derive_status(did) == "paid"


def test_issue_writes_timeline_events():
    did, offer_id = _make_won_deal("Event Kupac", "Event deal")
    invoice_service.issue_invoice_from_offer(did, offer_id)
    events = deal_service.list_events(did)
    bodies = [e["body"] for e in events]
    assert any("Invoice issued" in b for b in bodies)


def test_close_still_wins_precedence():
    did, offer_id = _make_won_deal("Close Kupac", "Close deal")
    ok, inv = invoice_service.issue_invoice_from_offer(did, offer_id)
    invoice_service.record_payment(inv, 1200.0)
    assert deal_service.derive_status(did) == "paid"
    deal_service.close_deal(did, True)
    assert deal_service.derive_status(did) == "closed"  # close wins


def test_deal_invoice_summary_excludes_voided():
    did, offer_id = _make_won_deal("Summary Kupac", "Summary deal")
    ok, inv = invoice_service.issue_invoice_from_offer(did, offer_id)
    invoice_service.void_invoice(inv)
    assert invoice_service.deal_invoice_summary(did) == []
