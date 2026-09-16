"""Deal services (Phase 4): master data, numbering, timeline, derived status.

Business logic for the deals spine; route modules keep HTTP concerns
(services-layer pattern, P2 stage 4). Conventions enforced here:

  * NO deletes: customers archive (archived flag); locations/deals/events
    have no delete path anywhere in this module.
  * Names resolve at read time: callers store ids, views join for the name.
  * Deal code D-YYYY-NNN from the per-year deal_counters row -- global
    per-year sequence (blueprint §5); retry loop guards the SQLite single
    writer against the (unlikely) concurrent-code race via UNIQUE(code).
  * Deal status is DERIVED, never stored:
      new      -- no linked documents and no decision events yet
      offered  -- >=1 offer linked (and none accepted)
      won      -- an accepted-offer decision event recorded (the one hand
                  tap the model allows)
      paid     -- >=1 non-voided invoice on the deal and every one of them
                  is fully covered by payments (Phase 4.x; derived from
                  SUM(payments) vs invoice totals, never stored)
      closed   -- deals.closed_at set (hand close)
    Precedence: closed > paid > won > offered > new.
    The only hand-set state is the acceptance tap: a 'decision' event with
    linked_doc_type='offer_accepted'.
"""
import sqlite3
from datetime import date, datetime, timezone

from qp_crm.shared.db import get_db


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# master data: customers
# ---------------------------------------------------------------------------

def list_customers(include_archived=False, search=""):
    """Customers for lists/pickers; names resolved live at read time."""
    conn = get_db()
    cur = conn.cursor()
    sql = "SELECT * FROM customers"
    clauses, params = [], []
    if not include_archived:
        clauses.append("archived = 0")
    if search:
        clauses.append("(name LIKE ? OR pib LIKE ? OR mb LIKE ? OR city LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like, like]
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY name COLLATE NOCASE;"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_customer(customer_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM customers WHERE id = ?;", (customer_id,))
    row = cur.fetchone()
    conn.close()
    return row


def create_customer(name, pib="", mb="", billing_address="", city="",
                    country="", email="", phone="", notes=""):
    """Create a customer. Returns (ok, id_or_message)."""
    name = (name or "").strip()
    if not name:
        return False, "Customer name is required."
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO customers (name, pib, mb, billing_address, city, country,
                               email, phone, notes, created_at, archived)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0);
        """,
        (name, (pib or "").strip(), (mb or "").strip(), (billing_address or "").strip(),
         (city or "").strip(), (country or "").strip(), (email or "").strip(),
         (phone or "").strip(), (notes or "").strip(), _utcnow_iso()),
    )
    customer_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, customer_id


def update_customer(customer_id, name, pib="", mb="", billing_address="",
                    city="", country="", email="", phone="", notes="",
                    archived=None):
    """Edit master data. Rename is safe by design: everything links by id."""
    name = (name or "").strip()
    if not name:
        return False, "Customer name is required."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM customers WHERE id = ?;", (customer_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Customer not found."
    cur.execute(
        """
        UPDATE customers
        SET name = ?, pib = ?, mb = ?, billing_address = ?, city = ?,
            country = ?, email = ?, phone = ?, notes = ?
        WHERE id = ?;
        """,
        (name, (pib or "").strip(), (mb or "").strip(), (billing_address or "").strip(),
         (city or "").strip(), (country or "").strip(), (email or "").strip(),
         (phone or "").strip(), (notes or "").strip(), customer_id),
    )
    if archived is not None:
        cur.execute("UPDATE customers SET archived = ? WHERE id = ?;",
                    (1 if archived else 0, customer_id))
    conn.commit()
    conn.close()
    return True, customer_id


def set_customer_archived(customer_id, archived):
    """Archive (never delete) a customer. Returns (ok, message)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM customers WHERE id = ?;", (customer_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Customer not found."
    cur.execute("UPDATE customers SET archived = ? WHERE id = ?;",
                (1 if archived else 0, customer_id))
    conn.commit()
    conn.close()
    return True, "ok"


# ---------------------------------------------------------------------------
# master data: locations
# ---------------------------------------------------------------------------

def list_locations(customer_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM customer_locations WHERE customer_id = ? ORDER BY id;",
        (customer_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_location(location_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM customer_locations WHERE id = ?;", (location_id,))
    row = cur.fetchone()
    conn.close()
    return row


def create_location(customer_id, name, address="", city="", contact_name="",
                    contact_phone="", notes=""):
    """Create a site under a customer. Returns (ok, id_or_message)."""
    name = (name or "").strip()
    if not name:
        return False, "Location name is required."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM customers WHERE id = ?;", (customer_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Customer not found."
    cur.execute(
        """
        INSERT INTO customer_locations (customer_id, name, address, city,
                                        contact_name, contact_phone, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (customer_id, name, (address or "").strip(), (city or "").strip(),
         (contact_name or "").strip(), (contact_phone or "").strip(),
         (notes or "").strip()),
    )
    location_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, location_id


def update_location(location_id, name, address="", city="", contact_name="",
                    contact_phone="", notes=""):
    name = (name or "").strip()
    if not name:
        return False, "Location name is required."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM customer_locations WHERE id = ?;", (location_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Location not found."
    cur.execute(
        """
        UPDATE customer_locations
        SET name = ?, address = ?, city = ?, contact_name = ?, contact_phone = ?, notes = ?
        WHERE id = ?;
        """,
        (name, (address or "").strip(), (city or "").strip(),
         (contact_name or "").strip(), (contact_phone or "").strip(),
         (notes or "").strip(), location_id),
    )
    conn.commit()
    conn.close()
    return True, location_id


# ---------------------------------------------------------------------------
# deals: numbering + CRUD
# ---------------------------------------------------------------------------

def _next_deal_code(cur, year):
    """Increment the per-year counter and return the new code.

    Caller owns the transaction; UNIQUE(code) + retry in create_deal is
    the race guard (blueprint §5: per-year counter + retry).
    """
    cur.execute(
        "INSERT INTO deal_counters (year, last_number) VALUES (?, 0) "
        "ON CONFLICT(year) DO NOTHING;",
        (year,),
    )
    cur.execute(
        "UPDATE deal_counters SET last_number = last_number + 1 WHERE year = ? "
        "RETURNING last_number;",
        (year,),
    )
    row = cur.fetchone()
    return f"D-{year}-{row['last_number']:03d}"


def create_deal(customer_id, title, location_id=None, owner_user_id=None,
                author_user_id=None):
    """Open a deal thread. Returns (ok, id_or_message).

    The creation itself is logged as the first timeline event (event_type
    'note') so every thread starts with its birth record.
    """
    title = (title or "").strip()
    if not title:
        return False, "Deal title is required."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM customers WHERE id = ?;", (customer_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Customer not found."
    if location_id:
        cur.execute("SELECT customer_id FROM customer_locations WHERE id = ?;",
                    (location_id,))
        loc = cur.fetchone()
        if loc is None or loc["customer_id"] != customer_id:
            conn.close()
            return False, "Location does not belong to this customer."

    year = date.today().year
    # Retry loop: UNIQUE(code) makes the counter row the single arbiter;
    # on the (unlikely) duplicate race, re-read and retry.
    for _attempt in range(3):
        try:
            code = _next_deal_code(cur, year)
            cur.execute(
                """
                INSERT INTO deals (code, customer_id, location_id, title,
                                   owner_user_id, created_at, closed_at)
                VALUES (?, ?, ?, ?, ?, ?, NULL);
                """,
                (code, customer_id, location_id or None, title,
                 owner_user_id, _utcnow_iso()),
            )
            deal_id = cur.lastrowid
            break
        except sqlite3.IntegrityError:
            conn.rollback()
    else:
        conn.close()
        return False, "Could not allocate a deal code."

    cur.execute(
        """
        INSERT INTO deal_events (deal_id, event_type, author_user_id, body, created_at)
        VALUES (?, 'note', ?, ?, ?);
        """,
        (deal_id, author_user_id, f"Deal created: {title}", _utcnow_iso()),
    )
    conn.commit()
    conn.close()
    return True, deal_id


def get_deal(deal_id):
    """The deal row plus resolved master names (read-time resolution)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT d.*, c.name AS customer_name, c.pib AS customer_pib,
               c.mb AS customer_mb, c.billing_address AS customer_billing_address,
               c.city AS customer_city, c.country AS customer_country,
               c.email AS customer_email, c.phone AS customer_phone,
               l.name AS location_name, l.address AS location_address,
               l.city AS location_city, l.contact_name AS location_contact_name,
               l.contact_phone AS location_contact_phone,
               u.username AS owner_username
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        LEFT JOIN customer_locations l ON l.id = d.location_id
        LEFT JOIN users u ON u.id = d.owner_user_id
        WHERE d.id = ?;
        """,
        (deal_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def list_deals(status="", customer_id=None, search=""):
    """Deals for the list/pipeline with resolved names + derived status.

    Filtering by derived status happens in Python: status is a read-model
    property of (links + events), not a stored column.
    """
    conn = get_db()
    cur = conn.cursor()
    sql = """
        SELECT d.*, c.name AS customer_name, l.name AS location_name
        FROM deals d
        JOIN customers c ON c.id = d.customer_id
        LEFT JOIN customer_locations l ON l.id = d.location_id
    """
    clauses, params = [], []
    if customer_id:
        clauses.append("d.customer_id = ?")
        params.append(customer_id)
    if search:
        clauses.append("(d.title LIKE ? OR d.code LIKE ? OR c.name LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like]
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY d.created_at DESC, d.id DESC;"
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["status"] = derive_status(r["id"])
    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def close_deal(deal_id, closed=True):
    """Hand close (the only hand state besides the acceptance tap)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE deals SET closed_at = ? WHERE id = ?;",
                (_utcnow_iso() if closed else None, deal_id))
    conn.commit()
    conn.close()
    return True, "ok"


# ---------------------------------------------------------------------------
# timeline events
# ---------------------------------------------------------------------------

EVENT_TYPES = ("call", "email", "meeting", "note", "document", "decision")


def add_event(deal_id, event_type, body="", author_user_id=None,
              linked_doc_type=None, linked_doc_id=None, created_at=None):
    """Append a timeline event. Returns (ok, id_or_message).

    event_type must be from the fixed set (blueprint §2 sketch); document
    and decision events carry the linked doc reference.
    """
    if event_type not in EVENT_TYPES:
        return False, f"Unknown event type: {event_type}"
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM deals WHERE id = ?;", (deal_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Deal not found."
    cur.execute(
        """
        INSERT INTO deal_events (deal_id, event_type, author_user_id, body,
                                 linked_doc_type, linked_doc_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (deal_id, event_type, author_user_id, (body or "").strip(),
         linked_doc_type, linked_doc_id, created_at or _utcnow_iso()),
    )
    event_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, event_id


def list_events(deal_id):
    """Timeline, oldest first (a thread reads top-down)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT e.*, u.username AS author_username
        FROM deal_events e
        LEFT JOIN users u ON u.id = e.author_user_id
        WHERE e.deal_id = ?
        ORDER BY e.created_at, e.id;
        """,
        (deal_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_event(deal_id, event_id):
    """Remove a hand-written event (typo fix). Document/decision events
    created by linking are managed by the link code, not deleted here --
    but a decision tap may be undone the same way it was made: by deleting
    the event. Links on offers stay; status re-derives."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT event_type FROM deal_events WHERE id = ? AND deal_id = ?;",
                (event_id, deal_id))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return False, "Event not found."
    cur.execute("DELETE FROM deal_events WHERE id = ?;", (event_id,))
    conn.commit()
    conn.close()
    return True, "ok"


# ---------------------------------------------------------------------------
# derived status (the read model)
# ---------------------------------------------------------------------------

def derived_status_for(deal_row, offer_rows, event_rows,
                       invoices_all_paid=False, invoices_count=0):
    """Pure derivation over fetched rows -- unit-testable without HTTP.

    offer_rows: rows of offers where deal_id = deal (any is_template value;
    templates are offers too until linked off).
    event_rows: the deal's timeline events.

    Precedence (Phase 4.x): closed > paid > won > offered > new.
      closed: deals.closed_at set (hand close wins -- no further activity)
      paid:   every non-voided invoice fully covered by payments AND at
              least one invoice exists (passed in via invoices_all_paid
              + invoices_count)
      won:    a 'decision' event with linked_doc_type='offer_accepted'
      offered: >=1 offer linked
      new:    otherwise
    """
    if deal_row is not None and _row_get(deal_row, "closed_at"):
        return "closed"
    if invoices_count and invoices_all_paid:
        return "paid"
    events = [dict(e) for e in (event_rows or [])]
    for e in events:
        if e.get("event_type") == "decision" and \
                e.get("linked_doc_type") == "offer_accepted":
            return "won"
    if offer_rows:
        return "offered"
    return "new"


def _row_get(row, key, default=None):
    """sqlite3.Row has no .get()/attr access; dict rows and Rows both work
    through item access guarded by a try (Row raises IndexError)."""
    try:
        value = row[key]
        return default if value is None else value
    except (IndexError, KeyError, TypeError):
        return default


def derive_status(deal_id):
    """Derive the status of one deal from its links (see module docstring)."""
    from qp_crm.services import invoice_service
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM deals WHERE id = ?;", (deal_id,))
    deal = cur.fetchone()
    if deal is None:
        conn.close()
        return None
    cur.execute("SELECT id FROM offers WHERE deal_id = ?;", (deal_id,))
    offers = cur.fetchall()
    cur.execute("SELECT * FROM deal_events WHERE deal_id = ?;", (deal_id,))
    events = cur.fetchall()
    cur.execute(
        "SELECT COUNT(*) AS n, "
        "SUM(CASE WHEN voided_at IS NULL THEN 1 ELSE 0 END) AS active "
        "FROM invoices WHERE deal_id = ?;", (deal_id,))
    inv_row = cur.fetchone()
    conn.close()
    # paid only counts NON-voided invoices; voided-only => not paid
    active = inv_row["active"] or 0
    all_paid = False
    if active:
        all_paid = invoice_service.deal_is_paid(deal_id)
    return derived_status_for(deal, offers, events,
                              invoices_all_paid=all_paid,
                              invoices_count=active)


def record_offer_accepted(deal_id, offer_id, author_user_id=None):
    """The acceptance tap (open question #9, recommended option (a)).

    Records a 'decision' event referencing the accepted offer; status
    derives to 'won' from this event. Returns (ok, message).
    """
    ok, result = add_event(
        deal_id, "decision",
        body="Offer accepted",
        author_user_id=author_user_id,
        linked_doc_type="offer_accepted",
        linked_doc_id=offer_id,
    )
    return ok, ("ok" if ok else result)


def deal_with_offers(deal_id):
    """Everything the deal thread page needs: deal, events, linked offers,
    invoices (with paid/remaining), derived status."""
    from qp_crm.services import invoice_service
    deal = get_deal(deal_id)
    if deal is None:
        return None, [], [], [], None
    events = list_events(deal_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, offer_number, date, client_name, total_gross, currency, deal_id
        FROM offers WHERE deal_id = ? ORDER BY date, id;
        """,
        (deal_id,),
    )
    offers = cur.fetchall()
    conn.close()
    invoices = invoice_service.deal_invoice_summary(deal_id)
    active = len(invoices)
    all_paid = active > 0 and all(inv["is_paid"] for inv in invoices)
    status = derived_status_for(deal, offers, events,
                                invoices_all_paid=all_paid,
                                invoices_count=active)
    return deal, offers, events, invoices, status


def record_offer_linked(deal_id, offer_id, author_user_id=None, linked=False):
    """Timeline record for offer link/unlink (written by the offer routes)."""
    verb = "Offer linked" if linked else "Offer unlinked"
    return add_event(
        deal_id, "document", body=f"{verb}: {offer_id}",
        author_user_id=author_user_id,
        linked_doc_type="offer", linked_doc_id=offer_id,
    )


# ---------------------------------------------------------------------------
# pipeline read model
# ---------------------------------------------------------------------------

def pipeline_board():
    """Deals grouped by derived status for the pipeline screen.

    Value per deal = SUM of linked offers' total_gross, reported per
    currency (offers may differ). No stored totals: computed at read.
    """
    deals = list_deals()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT deal_id, currency, SUM(COALESCE(total_gross, 0)) AS value
        FROM offers WHERE deal_id IS NOT NULL
        GROUP BY deal_id, currency;
        """
    )
    values = {}
    for row in cur.fetchall():
        values.setdefault(row["deal_id"], []).append(
            {"currency": row["currency"] or "", "value": row["value"] or 0.0}
        )
    conn.close()
    board = {"new": [], "offered": [], "won": [], "paid": [], "closed": []}
    for d in deals:
        d["offer_values"] = values.get(d["id"], [])
        board.setdefault(d["status"], []).append(d)
    return board
