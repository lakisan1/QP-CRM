"""Invoice + payment services (Phase 4.x): the financial tail of a deal.

Business logic for invoices/payments; route modules keep HTTP concerns
(services-layer pattern, P2 stage 4). Conventions enforced here:

  * issuance-time snapshot -- issuing an invoice COPIES the accepted
    offer's client fields + items; later edits to the offer or customer
    master data never leak into an issued invoice (blueprint §4).
  * NO deletes: invoices void (voided_at), payments are never removed
    (mistakes get a reversing entry); there is no delete path here.
  * invoice 'paid' status is DERIVED, never stored: an invoice is paid
    when SUM(payments.amount) >= total_gross; a deal is 'paid' when it
    has >=1 invoice and every non-voided invoice is paid.
  * invoice code F-YYYY-NNN from the GLOBAL per-year invoice_counters
    bucket (user decision 2026-09-16: one sequence for all invoices --
    no per-customer or per-deal series, supersedes OPEN_QUESTIONS #4).
    Same race guard as deals: UNIQUE(code) + 3-attempt retry.
"""
import sqlite3
from datetime import date, datetime, timezone

from qp_crm.services.deal_service import EVENT_TYPES, _row_get, _utcnow_iso
from qp_crm.shared.db import get_db


def _append_event(cur, deal_id, event_type, body="", author_user_id=None,
                  linked_doc_type=None, linked_doc_id=None):
    """INSERT a timeline event on the CALLER's connection.

    deal_service.add_event opens its own connection, which dead-locks
    (SQLite single-writer) when called mid-transaction -- so invoice and
    payment writes append events inline on their own transaction instead.
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event type: {event_type}")
    cur.execute(
        """
        INSERT INTO deal_events (deal_id, event_type, author_user_id, body,
                                 linked_doc_type, linked_doc_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (deal_id, event_type, author_user_id, (body or "").strip(),
         linked_doc_type, linked_doc_id, _utcnow_iso()),
    )
    return cur.lastrowid


# ---------------------------------------------------------------------------
# numbering (global per-year bucket, user-confirmed)
# ---------------------------------------------------------------------------

def _next_invoice_code(cur, year):
    """Increment the global per-year counter and return the new code.

    Caller owns the transaction; UNIQUE(code) + retry in issue_invoice
    is the race guard (same idiom as deal codes).
    """
    cur.execute(
        "INSERT INTO invoice_counters (year, last_number) VALUES (?, 0) "
        "ON CONFLICT(year) DO NOTHING;",
        (year,),
    )
    cur.execute(
        "UPDATE invoice_counters SET last_number = last_number + 1 WHERE year = ? "
        "RETURNING last_number;",
        (year,),
    )
    row = cur.fetchone()
    return f"F-{year}-{row['last_number']:03d}"


# ---------------------------------------------------------------------------
# issuance
# ---------------------------------------------------------------------------

def issue_invoice_from_offer(deal_id, offer_id, due_date=None, notes=None,
                             author_user_id=None):
    """Issue an invoice on a deal from a linked, accepted offer.

    Copies the offer's FROZEN client snapshot + item lines into the new
    invoice (issuance-time snapshot); allocates F-YYYY-NNN from the global
    bucket; writes a 'document' event on the deal timeline.

    Returns (ok, invoice_id_or_message).
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM deals WHERE id = ?;", (deal_id,))
    deal = cur.fetchone()
    if deal is None:
        conn.close()
        return False, "Deal not found."
    cur.execute(
        "SELECT * FROM offers WHERE id = ? AND deal_id = ?;",
        (offer_id, deal_id),
    )
    offer = cur.fetchone()
    if offer is None:
        conn.close()
        return False, "Offer not found on this deal."
    cur.execute(
        "SELECT id FROM invoices WHERE source_offer_id = ? AND voided_at IS NULL;",
        (offer_id,),
    )
    if cur.fetchone() is not None:
        conn.close()
        return False, "This offer already has an invoice."

    year = date.today().year
    for _attempt in range(3):
        try:
            code = _next_invoice_code(cur, year)
            # The invoice total comes from the OFFER ITEMS (the offer row's
            # total_gross is stale 0 until recalc_totals runs on edit); the
            # items are the frozen math that actually shipped.
            cur.execute(
                "SELECT COALESCE(SUM(line_net), 0) AS gross FROM offer_items "
                "WHERE offer_id = ?;",
                (offer_id,),
            )
            items_gross = cur.fetchone()["gross"] or 0.0
            cur.execute(
                """
                INSERT INTO invoices (
                    code, deal_id, customer_id, location_id, source_offer_id,
                    issue_date, due_date, currency, exchange_rate,
                    total_gross,
                    client_name, client_address, client_email, client_phone,
                    client_pib, client_mb, client_country,
                    notes, created_at, voided_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL);
                """,
                (
                    code, deal_id, deal["customer_id"], deal["location_id"],
                    offer_id, _utcnow_iso()[:10], due_date or None,
                    offer["currency"], offer["exchange_rate"] or 1.0,
                    items_gross or (offer["total_gross"] or 0.0),
                    offer["client_name"], offer["client_address"],
                    offer["client_email"], offer["client_phone"],
                    offer["client_pib"], offer["client_mb"], offer["country"],
                    notes or None, _utcnow_iso(),
                ),
            )
            invoice_id = cur.lastrowid
            # copy item lines (position preserved; the offer's frozen math
            # is copied as-is -- no recalculation at issuance)
            cur.execute(
                """
                SELECT line_order, item_name, item_description, quantity,
                       unit_price, discount_percent, line_net
                FROM offer_items WHERE offer_id = ? ORDER BY line_order, id;
                """,
                (offer_id,),
            )
            for item in cur.fetchall():
                cur.execute(
                    """
                    INSERT INTO invoice_items (
                        invoice_id, position, description, qty, unit,
                        unit_price, discount_percent, line_total
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        invoice_id, item["line_order"], item["item_name"],
                        item["quantity"], None, item["unit_price"],
                        item["discount_percent"] or 0.0,
                        item["line_net"],
                    ),
                )
            break
        except sqlite3.IntegrityError:
            conn.rollback()
    else:
        conn.close()
        return False, "Could not allocate an invoice code."

    _append_event(cur, deal_id, "document",
                  body=f"Invoice issued: {code}",
                  author_user_id=author_user_id,
                  linked_doc_type="invoice", linked_doc_id=invoice_id)
    conn.commit()
    conn.close()
    return True, invoice_id


# ---------------------------------------------------------------------------
# payments
# ---------------------------------------------------------------------------

def record_payment(invoice_id, amount, paid_at=None, method=None, reference=None,
                   note=None, created_by_user_id=None):
    """Record a payment against an invoice. Returns (ok, payment_id_or_msg).

    The payment is also logged as a timeline event on the invoice's deal
    (the thread stays the single story of the money).
    """
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return False, "Amount must be a number."
    if amount <= 0:
        return False, "Payment amount must be positive."

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE id = ?;", (invoice_id,))
    invoice = cur.fetchone()
    if invoice is None:
        conn.close()
        return False, "Invoice not found."
    if _row_get(invoice, "voided_at"):
        conn.close()
        return False, "Invoice is voided -- payments are closed."

    cur.execute(
        """
        INSERT INTO payments (invoice_id, paid_at, amount, currency, method,
                              reference, note, created_by_user_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            invoice_id, paid_at or _utcnow_iso()[:10], amount,
            invoice["currency"], method or None, reference or None,
            note or None, created_by_user_id, _utcnow_iso(),
        ),
    )
    payment_id = cur.lastrowid
    _append_event(cur, invoice["deal_id"], "document",
                  body=f"Payment recorded: {amount:.2f} {invoice['currency'] or ''} "
                       f"on {_row_get(invoice, 'code') or invoice_id}",
                  author_user_id=created_by_user_id,
                  linked_doc_type="payment", linked_doc_id=payment_id)
    conn.commit()
    conn.close()
    return True, payment_id


def void_invoice(invoice_id, author_user_id=None):
    """Void (never delete) an invoice. Returns (ok, message).

    Voided invoices drop out of the paid derivation and out of the deal's
    invoice list; their payments remain in the DB (audit) but stop counting.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT code, deal_id, voided_at FROM invoices WHERE id = ?;",
                (invoice_id,))
    invoice = cur.fetchone()
    if invoice is None:
        conn.close()
        return False, "Invoice not found."
    if _row_get(invoice, "voided_at"):
        conn.close()
        return True, "ok"  # idempotent
    cur.execute("UPDATE invoices SET voided_at = ? WHERE id = ?;",
                (_utcnow_iso(), invoice_id))
    _append_event(cur, invoice["deal_id"], "document",
                  body=f"Invoice voided: {_row_get(invoice, 'code') or invoice_id}",
                  author_user_id=author_user_id,
                  linked_doc_type="invoice_void", linked_doc_id=invoice_id)
    conn.commit()
    conn.close()
    return True, "ok"


# ---------------------------------------------------------------------------
# read model
# ---------------------------------------------------------------------------

def invoice_with_details(invoice_id):
    """Invoice row + items + payments + derived paid state for the view."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM invoices WHERE id = ?;", (invoice_id,))
    invoice = cur.fetchone()
    if invoice is None:
        conn.close()
        return None
    cur.execute(
        "SELECT * FROM invoice_items WHERE invoice_id = ? ORDER BY position, id;",
        (invoice_id,),
    )
    items = cur.fetchall()
    cur.execute(
        "SELECT * FROM payments WHERE invoice_id = ? ORDER BY paid_at, id;",
        (invoice_id,),
    )
    payments = cur.fetchall()
    conn.close()
    paid = sum(p["amount"] or 0.0 for p in payments)
    remaining = (invoice["total_gross"] or 0.0) - paid
    return {
        "invoice": invoice,
        "items": items,
        "payments": payments,
        "paid": paid,
        "remaining": remaining,
        "is_paid": remaining <= 1e-9,
        "is_voided": _row_get(invoice, "voided_at") is not None,
    }


def deal_invoice_summary(deal_id):
    """Invoices of one deal with per-invoice paid/remaining for the thread.

    Voided invoices are EXCLUDED from the paid derivation; they stay out
    of this list entirely (the timeline keeps the audit events).
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM invoices WHERE deal_id = ? AND voided_at IS NULL "
        "ORDER BY issue_date, id;",
        (deal_id,),
    )
    invoices = []
    for row in cur.fetchall():
        inv = dict(row)
        cur.execute(
            "SELECT COALESCE(SUM(amount), 0) AS paid FROM payments "
            "WHERE invoice_id = ?;",
            (row["id"],),
        )
        inv["paid"] = cur.fetchone()["paid"] or 0.0
        inv["remaining"] = (inv["total_gross"] or 0.0) - inv["paid"]
        inv["is_paid"] = inv["remaining"] <= 1e-9
        invoices.append(inv)
    conn.close()
    return invoices


def _invoice_rows_for_deals(cur, deal_ids):
    """Per-deal paid/total aggregates over non-voided invoices."""
    if not deal_ids:
        return {}
    placeholders = ",".join("?" for _ in deal_ids)
    cur.execute(
        f"""
        SELECT i.deal_id,
               i.currency,
               SUM(i.total_gross) AS total,
               COALESCE((SELECT SUM(p.amount) FROM payments p
                         JOIN invoices i2 ON i2.id = p.invoice_id
                         WHERE i2.deal_id = i.deal_id
                           AND i2.voided_at IS NULL), 0) AS paid
        FROM invoices i
        WHERE i.deal_id IN ({placeholders}) AND i.voided_at IS NULL
        GROUP BY i.deal_id, i.currency;
        """,
        deal_ids,
    )
    rows = cur.fetchall()
    conn = None  # caller owns the connection
    return {r["deal_id"]: dict(r) for r in rows}


def deal_is_paid(deal_id):
    """Derived deal-level 'paid': >=1 invoice and all invoices covered."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, total_gross FROM invoices WHERE deal_id = ? AND voided_at IS NULL;",
        (deal_id,),
    )
    invoices = cur.fetchall()
    if not invoices:
        conn.close()
        return False
    for inv in invoices:
        cur.execute("SELECT COALESCE(SUM(amount), 0) AS paid FROM payments "
                    "WHERE invoice_id = ?;", (inv["id"],))
        if (cur.fetchone()["paid"] or 0.0) < (inv["total_gross"] or 0.0) - 1e-9:
            conn.close()
            return False
    conn.close()
    return True
