"""Purchase-order services (P5-UI rework batch B): the commercial side.

The orders app is for the person who WATCHES stock, ORDERS and RESERVES
(user's role split 2026-09-27); the warehouse operator only intakes/
out-takes. Conventions inherited from the warehouse services:

  * NO deletes — a cancelled PO keeps its rows (status 'cancelled');
  * po_number PO-YYYY-NNN from a global counter (invoice pattern);
  * a received line appends the inbound ledger movement automatically
    (the warehouse operator does NOT re-enter it) and auto-closes any
    shortfall the line replaces (po_ref = PO number);
  * supplier is free text in v1 (open question #12: partner rows later).
"""
from datetime import date, datetime, timezone

from qp_crm.shared.db import get_db

from qp_crm.shared.schema import (
    ORDER_STATUS_LABELS,
    ORDER_STATUS_VALUES,
    TRACKING_REGIMES,
)


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today():
    return date.today().isoformat()


def _next_po_number(conn):
    """PO-YYYY-NNN, global per year (invoice_counters pattern, own table)."""
    year = date.today().year
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS po_counters (
            year INTEGER PRIMARY KEY, last INTEGER NOT NULL
        );
        """
    )
    row = conn.execute(
        "SELECT last FROM po_counters WHERE year = ?;", (year,)).fetchone()
    last = (row["last"] if row else 0) + 1
    if row:
        conn.execute("UPDATE po_counters SET last = ? WHERE year = ?;", (last, year))
    else:
        conn.execute("INSERT INTO po_counters (year, last) VALUES (?, ?);", (year, last))
    return f"PO-{year}-{last:03d}"


def create_order(supplier_name, lines, expected_at=None, note=None,
                 created_by=None):
    """Open a purchase order with its lines. Returns (ok, id-or-message).

    lines: iterable of dicts {product_id?, name_snapshot?, qty,
    shortfall_id?}. A line needs product_id OR name_snapshot; qty > 0.
    The PO starts as 'ordered' regardless of who is typing it —
    receiving is a separate, deliberate act.
    """
    supplier = (supplier_name or "").strip()
    if not supplier:
        return False, "Dobavljač je obavezan."
    clean_lines = []
    for line in lines or []:
        pid = line.get("product_id") or None
        snap = (line.get("name_snapshot") or "").strip() or None
        try:
            qty = float(line.get("qty"))
        except (TypeError, ValueError):
            return False, "Svaka stavka mora imati količinu (broj)."
        if qty <= 0:
            return False, "Količina stavke mora biti veća od nule."
        if pid is None and not snap:
            return False, "Stavka mora imati proizvod ili naziv (temp stavka)."
        clean_lines.append({"product_id": pid, "name_snapshot": snap,
                            "qty": qty,
                            "shortfall_id": line.get("shortfall_id") or None})
    if not clean_lines:
        return False, "Narudžbina mora imati bar jednu stavku."

    conn = get_db()
    cur = conn.cursor()
    po_number = _next_po_number(cur)
    cur.execute(
        """
        INSERT INTO purchase_orders (po_number, supplier_name, ordered_at,
                                     expected_at, status, note, created_by,
                                     created_at)
        VALUES (?, ?, ?, ?, 'ordered', ?, ?, ?);
        """,
        (po_number, supplier, _today(), expected_at or None,
         (note or "").strip() or None, created_by, _utcnow_iso()),
    )
    po_id = cur.lastrowid
    for line in clean_lines:
        cur.execute(
            """
            INSERT INTO po_lines (po_id, product_id, name_snapshot, qty,
                                  shortfall_id, received_at, received_qty)
            VALUES (?, ?, ?, ?, ?, NULL, NULL);
            """,
            (po_id, line["product_id"], line["name_snapshot"],
             line["qty"], line["shortfall_id"]),
        )
    conn.commit()
    conn.close()
    return True, po_id


def get_order(po_id):
    """The PO header with its lines (names resolved live)."""
    conn = get_db()
    order = conn.execute(
        "SELECT * FROM purchase_orders WHERE id = ?;", (po_id,)).fetchone()
    if order is None:
        conn.close()
        return None
    lines = conn.execute(
        """
        SELECT l.*, p.name AS product_name,
               s.part_name AS shortfall_part, s.closed_at AS shortfall_closed
        FROM po_lines l
        LEFT JOIN products p ON p.id = l.product_id
        LEFT JOIN equipment_shortfalls s ON s.id = l.shortfall_id
        WHERE l.po_id = ? ORDER BY l.id;
        """,
        (po_id,),
    ).fetchall()
    conn.close()
    return {"header": order, "lines": lines}


def list_orders(status=None, active_only=False):
    """POs with line counts; newest first. active_only hides terminal ones."""
    conn = get_db()
    sql = """
        SELECT o.*,
               (SELECT COUNT(*) FROM po_lines l WHERE l.po_id = o.id) AS line_count,
               (SELECT COUNT(*) FROM po_lines l WHERE l.po_id = o.id
                  AND l.received_at IS NULL) AS open_lines
        FROM purchase_orders o
    """
    clauses, params = [], []
    if active_only:
        clauses.append("o.status IN ('ordered', 'partially')")
    if status in ORDER_STATUS_VALUES:
        clauses.append("o.status = ?")
        params.append(status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY o.id DESC;"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def receive_line(line_id, received_by=None):
    """Mark one line as arrived: ledger in + auto-close its shortfall.

    Returns (ok, message-or-None). The movement reason is 'purchase_in'
    (the goods physically entered the warehouse). A linked shortfall
    closes with po_ref = the receiving PO number — the debt note from the
    machine page settles itself (vision §'cannibalize': two taps).
    Idempotence: an already-received line is rejected (row stays).
    """
    conn = get_db()
    line = conn.execute(
        "SELECT * FROM po_lines WHERE id = ?;", (line_id,)).fetchone()
    if line is None:
        conn.close()
        return False, "Stavka ne postoji."
    if line["received_at"] is not None:
        conn.close()
        return False, "Stavka je već primljena."
    order = conn.execute(
        "SELECT * FROM purchase_orders WHERE id = ?;", (line["po_id"],)).fetchone()
    if order["status"] in ("received", "cancelled"):
        conn.close()
        return False, "Narudžbina je zatvorena — stavka ne može da se primi."

    cur = conn.cursor()
    now = _utcnow_iso()
    cur.execute(
        "UPDATE po_lines SET received_at = ?, received_qty = ? WHERE id = ?;",
        (now, line["qty"], line_id),
    )
    # ledger in — the warehouse stock math picks this up automatically
    cur.execute(
        """
        INSERT INTO stock_movements (product_id, equipment_id, name_snapshot,
                                     qty, direction, reason, contact_id,
                                     note, moved_at, moved_by)
        VALUES (?, NULL, ?, ?, 'in', 'purchase_in', NULL, ?, ?, ?);
        """,
        (line["product_id"], line["name_snapshot"], line["qty"],
         f"Prijava narudžbine {order['po_number']}", now, received_by),
    )
    # auto-close the linked shortfall (po_ref fills in the PO number)
    if line["shortfall_id"] is not None:
        cur.execute(
            """
            UPDATE equipment_shortfalls
            SET closed_at = ?, po_ref = COALESCE(NULLIF(po_ref, ''), ?)
            WHERE id = ? AND closed_at IS NULL;
            """,
            (now, order["po_number"], line["shortfall_id"]),
        )
    # recompute the PO status from its lines
    counts = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN received_at IS NULL THEN 1 ELSE 0 END) AS open
        FROM po_lines WHERE po_id = ?;
        """,
        (line["po_id"],),
    ).fetchone()
    new_status = "received" if not counts["open"] else "partially"
    cur.execute("UPDATE purchase_orders SET status = ? WHERE id = ?;",
                (new_status, line["po_id"]))
    conn.commit()
    conn.close()
    return True, new_status


def cancel_order(po_id):
    """Cancel a not-fully-received PO. Terminal; rows stay."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE purchase_orders SET status = 'cancelled'
        WHERE id = ? AND status IN ('ordered', 'partially');
        """,
        (po_id,),
    )
    cancelled = cur.rowcount
    conn.commit()
    conn.close()
    return (True, None) if cancelled else (False, "Narudžbina nije aktivna.")


def open_shortfalls_for_ordering():
    """The 'what do we need to order' list: open shortfall debts + tracked
    products under min_stock (the coverage gap), one row each."""
    conn = get_db()
    debts = conn.execute(
        """
        SELECT s.id, s.part_name, s.part_product_id, s.taken_at,
               e.name_snapshot AS equipment_name, e.serial_number
        FROM equipment_shortfalls s
        JOIN equipment e ON e.id = s.equipment_id
        WHERE s.closed_at IS NULL
        ORDER BY s.taken_at;
        """
    ).fetchall()
    gaps = []
    for product in conn.execute(
        """
        SELECT id, name, min_stock FROM products
        WHERE tracking_regime = 'qty' AND min_stock IS NOT NULL;
        """
    ).fetchall():
        on_hand = conn.execute(
            """
            SELECT COALESCE(SUM(CASE direction WHEN 'in' THEN qty ELSE -qty END), 0) AS n
            FROM stock_movements WHERE product_id = ?;
            """,
            (product["id"],),
        ).fetchone()["n"] or 0.0
        reserved = conn.execute(
            "SELECT COALESCE(SUM(qty), 0) AS n FROM reservations "
            "WHERE product_id = ? AND released_at IS NULL;",
            (product["id"],),
        ).fetchone()["n"] or 0.0
        available = on_hand - reserved
        if available < product["min_stock"]:
            gaps.append({"product_id": product["id"], "name": product["name"],
                         "min_stock": product["min_stock"], "available": available})
    conn.close()
    return {"debts": debts, "gaps": gaps}
