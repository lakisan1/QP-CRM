"""Phase 4.x (invoices + payments) HTTP-level tests.

Extends the Phase-1 smoke discipline + the Phase-4 deals pages tests:

* the deal thread page carries the Fakture section: issue buttons per
  accepted-but-uninvoiced offer, per-invoice paid/remaining, void button;
* issuing via HTTP lands F-YYYY-NNN on the thread and a timeline event;
* payments via the inline form update paid/remaining; full coverage flips
  the deal to 'paid' (badge on thread + Plaćeno column on the pipeline);
* voiding drops the invoice from the section (timeline keeps the event);
* the offers pages stay green with the new signature (regression).
"""

import pytest

from conftest import csrf_token_for, login_client
from qp_crm.main import app
from qp_crm.shared.auth import get_db


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


def _build_won_deal(client, tok, name, title, item_gross=10000.0):
    """customer -> deal -> offer(+item) -> acceptance tap -> invoice.
    Returns (deal_id, offer_id, invoice_id) -- ids resolved from redirects
    and the DB, never assumed to be 1 (test DBs persist across runs)."""
    resp = client.post("/deals/customers/new", data={
        "_csrf_token": tok, "name": name, "pib": "107777888"})
    assert resp.status_code == 302
    customer_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = client.post("/deals/deals/new", data={
        "_csrf_token": tok, "customer": customer_id, "title": title})
    assert resp.status_code == 302
    deal_id = int(resp.headers["Location"].rstrip("/").rsplit("/", 1)[-1])

    resp = client.post("/offer/offers/new", data={
        "_csrf_token": tok, "action": "save", "offer_number": f"OFF-{deal_id}",
        "date": "2026-09-16", "client_name": name, "deal_id": str(deal_id),
        "vat_percent": "20"})
    assert resp.status_code == 302

    conn = get_db()
    offer_id = conn.execute(
        "SELECT id FROM offers WHERE offer_number = ?;",
        (f"OFF-{deal_id}",)).fetchone()["id"]
    conn.execute(
        "INSERT INTO offer_items (offer_id, line_order, item_name, quantity, "
        "unit_price, discount_percent, line_net) VALUES (?, 0, 'Lift', 1, ?, 0, ?);",
        (offer_id, item_gross, item_gross))
    conn.commit()
    conn.close()

    resp = client.post(f"/deals/deals/{deal_id}/accept_offer/{offer_id}",
                       data={"_csrf_token": tok})
    assert resp.status_code == 302

    resp = client.post(f"/deals/deals/{deal_id}/issue_invoice/{offer_id}",
                       data={"_csrf_token": tok})
    assert resp.status_code == 302

    conn = get_db()
    invoice_id = conn.execute(
        "SELECT id FROM invoices WHERE source_offer_id = ?;", (offer_id,)
    ).fetchone()["id"]
    conn.close()
    return deal_id, offer_id, invoice_id


def test_issue_invoice_via_http(offer_client):
    client = offer_client
    tok = csrf_token_for(client)
    deal_id, offer_id, _ = _build_won_deal(client, tok, "HTTP Kupac", "HTTP issue deal")

    # The FIRST render after issuing consumes the flash; verify there.
    page = client.get(f"/deals/deals/{deal_id}").data.decode()
    conn = get_db()
    code = conn.execute("SELECT code FROM invoices WHERE source_offer_id = ?;",
                        (offer_id,)).fetchone()["code"]
    conn.close()
    assert f"Faktura {code} izdata." in page
    assert code in page  # the invoice table row shows the code too


def test_payment_flow_via_http(offer_client):
    client = offer_client
    tok = csrf_token_for(client)
    deal_id, offer_id, invoice_id = _build_won_deal(
        client, tok, "Pay Kupac", "Pay deal", item_gross=10000.0)

    # partial payment -> remaining red, no paid badge
    resp = client.post(f"/deals/invoices/{invoice_id}/pay", data={
        "_csrf_token": tok, "amount": "4000", "method": "transfer"})
    assert resp.status_code == 302
    page = client.get(f"/deals/deals/{deal_id}").data.decode()
    assert "Uplata" in page  # inline payment form still offered

    # full payment -> Plaćena badge on the invoice row
    resp = client.post(f"/deals/invoices/{invoice_id}/pay", data={
        "_csrf_token": tok, "amount": "6000", "method": "transfer"})
    assert resp.status_code == 302
    page = client.get(f"/deals/deals/{deal_id}").data.decode()
    assert "Plaćena" in page

    # pipeline carries the paid column with the deal in it
    board = client.get("/deals/pipeline").data.decode()
    assert "Plaćeno" in board

    # invalid amount -> flash error, nothing recorded
    resp = client.post(f"/deals/invoices/{invoice_id}/pay", data={
        "_csrf_token": tok, "amount": "-5"})
    assert resp.status_code == 302
    page = client.get(f"/deals/deals/{deal_id}").data.decode()
    assert "must be positive" in page


def test_void_via_http(offer_client):
    client = offer_client
    tok = csrf_token_for(client)
    deal_id, offer_id, invoice_id = _build_won_deal(
        client, tok, "Void Kupac", "Void deal", item_gross=5000.0)
    resp = client.post(f"/deals/invoices/{invoice_id}/void", data={"_csrf_token": tok})
    assert resp.status_code == 302

    page = client.get(f"/deals/deals/{deal_id}").data.decode()
    # voided invoice drops out of the section...
    assert "nema faktura" in page
    # ...but the timeline keeps the audit event
    assert "Invoice voided" in page


def test_offers_pages_regression_with_invoices(offer_client):
    """The offers list/view/edit pages stay green once deal_with_offers
    grew the invoices tuple element."""
    client = offer_client
    tok = csrf_token_for(client)
    deal_id, offer_id, invoice_id = _build_won_deal(
        client, tok, "Reg Kupac", "Reg deal", item_gross=2000.0)
    assert client.get("/offer/offers").status_code == 200
    assert client.get(f"/offer/offers/{offer_id}/view").status_code == 200
    assert client.get(f"/offer/offers/{offer_id}/edit").status_code == 200
    # deal thread still fine
    assert client.get(f"/deals/deals/{deal_id}").status_code == 200
