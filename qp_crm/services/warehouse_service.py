"""Warehouse services (P5): stock & equipment — custody, not inventory value.

Business logic for the warehouse app; route modules keep HTTP concerns
(services-layer pattern, P2 stage 4). Conventions enforced here:

  * Regime gating: ONLY tracked products appear in stock math. A product
    with tracking_regime='untracked' has no ledger, no reservations, no
    coverage — record_movements against it is rejected. 'qty' products use
    the movement ledger; 'serialized' products are counted from equipment
    instance rows (never double-tracked).
  * NO deletes: movements are never removed (a mistake gets a reversing
    movement); equipment transitions only (→ scrap/sold exits); reservations
    release (released_at); shortfalls close (closed_at).
  * id + snapshot: an equipment row keeps name_snapshot even when the
    catalog product is later renamed or the reference is a temp product
    (product_id NULL).
  * Names resolved at read time: list views JOIN products/contacts for
    display — a rename never breaks a link.
  * user answers 2026-09-25: no deal links anywhere (reservations carry a
    free-text for_whom); custodian counterparty = the contacts directory;
    Serbian labels come from the schema closed sets.
"""
from datetime import datetime, timezone

from qp_crm.shared.db import get_db

from qp_crm.shared.schema import (
    CUSTODIAN_TYPES,
    EQUIPMENT_STATUS_VALUES,
    MOVEMENT_REASON_VALUES,
    TRACKING_REGIMES,
)


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today():
    from datetime import date
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# products / regimes
# ---------------------------------------------------------------------------

def get_product(product_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM products WHERE id = ?;", (product_id,)).fetchone()
    conn.close()
    return row


def tracked_products(regime=None):
    """Catalog rows with a tracking regime (optionally one specific).

    untracked rows are NEVER returned here — that is the gate. Lists the
    pickers and the coverage view feed from.
    """
    conn = get_db()
    cur = conn.cursor()
    if regime in TRACKING_REGIMES and regime != "untracked":
        cur.execute(
            "SELECT * FROM products WHERE tracking_regime = ? ORDER BY name;",
            (regime,))
    else:
        cur.execute(
            "SELECT * FROM products WHERE tracking_regime IN ('qty', 'serialized') "
            "ORDER BY name;")
    rows = cur.fetchall()
    conn.close()
    return rows


def set_tracking_regime(product_id, regime, min_stock=None, unit_base=None,
                        pack_size=None):
    """Flip a product's tracking regime (opt-in, amendment 5).

    Regime must be in TRACKING_REGIMES. Switching qty <-> serialized is
    allowed but the service does NOT migrate data: qty rows with movements
    and serialized rows with instances both stay (the operator records a
    stocktake-adjustment to reconcile). untracked hides the product from
    stock views without destroying any ledger history.
    """
    if regime not in TRACKING_REGIMES:
        return False, "Nepoznat režim praćenja."
    product = get_product(product_id)
    if product is None:
        return False, "Proizvod ne postoji."
    conn = get_db()
    conn.execute(
        "UPDATE products SET tracking_regime = ?, min_stock = ?, "
        "unit_base = ?, pack_size = ? WHERE id = ?;",
        (regime, min_stock, unit_base, pack_size, product_id),
    )
    conn.commit()
    conn.close()
    return True, None


# ---------------------------------------------------------------------------
# movements (qty regime + serialized evidence)
# ---------------------------------------------------------------------------

def record_movement(product_id=None, equipment_id=None, name_snapshot=None,
                    qty=None, direction="in", reason=None, contact_id=None,
                    note=None, moved_by=None, moved_at=None):
    """Append one movement to the ledger. Returns (ok, id-or-message).

    Rules:
      * exactly one subject: a qty-regime product OR an equipment instance
        OR a temp product (name_snapshot alone);
      * direction is 'in' | 'out'; reason must be in MOVEMENT_REASON_VALUES;
      * stocktake_adjustment REQUIRES a note (blueprint §9: the one
        hand-editable ledger event);
      * untracked products are rejected (regime gate);
      * serialized subjects should arrive via the equipment transition
        helper below, but a raw instance movement is accepted as evidence.
    """
    if direction not in ("in", "out"):
        return False, "Smer mora biti 'in' ili 'out'."
    if reason not in MOVEMENT_REASON_VALUES:
        return False, "Nepoznat razlog kretanja."
    if product_id is None and equipment_id is None and not (name_snapshot or "").strip():
        return False, "Kretanje mora imati proizvod, mašinu ili opis (temp proizvod)."
    if reason == "stocktake_adjustment" and not (note or "").strip():
        return False, "Korekcija popisa zahteva napomenu (obavezno polje)."

    if product_id is not None:
        product = get_product(product_id)
        if product is None:
            return False, "Proizvod ne postoji."
        if product["tracking_regime"] != "qty":
            return False, (
                f"Proizvod nije u 'qty' režimu ({product['tracking_regime']}) "
                "— količinski kretanja se ne beleže.")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO stock_movements (product_id, equipment_id, name_snapshot,
                                     qty, direction, reason, contact_id,
                                     note, moved_at, moved_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            product_id, equipment_id,
            (name_snapshot or "").strip() or None,
            qty if direction == "in" or qty is None else abs(float(qty)),
            direction, reason, contact_id, note,
            moved_at or _utcnow_iso(), moved_by,
        ),
    )
    movement_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, movement_id


def qty_on_hand(product_id):
    """Ledger balance for a qty-regime product: Σin − Σout."""
    conn = get_db()
    row = conn.execute(
        """
        SELECT COALESCE(SUM(CASE direction WHEN 'in' THEN qty ELSE -qty END), 0) AS on_hand
        FROM stock_movements WHERE product_id = ?;
        """,
        (product_id,),
    ).fetchone()
    conn.close()
    return row["on_hand"] or 0.0


def list_movements(product_id=None, equipment_id=None, limit=200):
    """Ledger rows (newest first), names resolved live (read-time joins)."""
    conn = get_db()
    cur = conn.cursor()
    sql = """
        SELECT m.*, p.name AS product_name,
               e.name_snapshot AS equipment_name,
               c.display_name AS contact_name
        FROM stock_movements m
        LEFT JOIN products p ON p.id = m.product_id
        LEFT JOIN equipment e ON e.id = m.equipment_id
        LEFT JOIN contacts c ON c.id = m.contact_id
    """
    clauses, params = [], []
    if product_id is not None:
        clauses.append("m.product_id = ?")
        params.append(product_id)
    if equipment_id is not None:
        clauses.append("m.equipment_id = ?")
        params.append(equipment_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY m.moved_at DESC, m.id DESC LIMIT ?;"
    params.append(limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# equipment (serialized instances; transitions only)
# ---------------------------------------------------------------------------

def _resolve_name_snapshot(conn, product_id, name_snapshot):
    """name_snapshot from product_id when the caller didn't supply one."""
    if (name_snapshot or "").strip():
        return name_snapshot.strip()
    if product_id is not None:
        row = conn.execute(
            "SELECT name FROM products WHERE id = ?;", (product_id,)).fetchone()
        if row:
            return row["name"]
    return None


def register_equipment(product_id=None, name_snapshot=None, serial_number=None,
                       custodian_type="warehouse", custodian_contact_id=None,
                       since_date=None, status="in_stock", notes=None,
                       registered_by=None):
    """Add one machine to the registry. Returns (ok, id-or-message).

    product_id NULL = temp registration (ad-hoc device without a catalog
    row); name_snapshot is then required. custodian/status validate against
    the closed sets. No delete path exists — scrap is a transition.
    """
    if custodian_type not in CUSTODIAN_TYPES:
        return False, "Nepoznat čuvar (custodian_type)."
    if status not in EQUIPMENT_STATUS_VALUES:
        return False, "Nepoznat status opreme."
    if not since_date:
        since_date = _today()
    if custodian_type == "customer" and not custodian_contact_id:
        return False, "Čuvar 'customer' zahteva kontakt iz imenika."
    if custodian_type in ("warehouse", "scrap"):
        custodian_contact_id = None

    conn = get_db()
    resolved = _resolve_name_snapshot(conn, product_id, name_snapshot)
    if not resolved:
        conn.close()
        return False, "Mašina mora imati naziv (iz kataloga ili unet ručno)."
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO equipment (product_id, name_snapshot, serial_number,
                               custodian_type, custodian_contact_id,
                               since_date, status, expected_return_at,
                               notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?);
        """,
        (product_id, resolved, (serial_number or "").strip() or None,
         custodian_type, custodian_contact_id, since_date, status,
         notes, _utcnow_iso()),
    )
    equipment_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, equipment_id


def get_equipment(equipment_id):
    conn = get_db()
    row = conn.execute(
        """
        SELECT e.*, p.name AS product_name,
               c.display_name AS custodian_name
        FROM equipment e
        LEFT JOIN products p ON p.id = e.product_id
        LEFT JOIN contacts c ON c.id = e.custodian_contact_id
        WHERE e.id = ?;
        """,
        (equipment_id,),
    ).fetchone()
    conn.close()
    return row


def list_equipment(status=None, custodian_type=None, contact_id=None,
                   search=""):
    """Registry rows (newest first), display names resolved at read time."""
    conn = get_db()
    cur = conn.cursor()
    sql = """
        SELECT e.*, p.name AS product_name,
               c.display_name AS custodian_name
        FROM equipment e
        LEFT JOIN products p ON p.id = e.product_id
        LEFT JOIN contacts c ON c.id = e.custodian_contact_id
    """
    clauses, params = [], []
    if status in EQUIPMENT_STATUS_VALUES:
        clauses.append("e.status = ?")
        params.append(status)
    if custodian_type in CUSTODIAN_TYPES:
        clauses.append("e.custodian_type = ?")
        params.append(custodian_type)
    if contact_id is not None:
        clauses.append("e.custodian_contact_id = ?")
        params.append(contact_id)
    if search:
        clauses.append("(e.name_snapshot LIKE ? OR e.serial_number LIKE ? "
                       "OR p.name LIKE ?)")
        pattern = f"%{search}%"
        params += [pattern, pattern, pattern]
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY e.id DESC;"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def warehouse_equipment_count(product_id):
    """Serialized 'stock' = instances currently custodian=warehouse,
    status in_stock (derived — no separate qty ledger for serialized)."""
    conn = get_db()
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM equipment
        WHERE product_id = ? AND custodian_type = 'warehouse'
          AND status = 'in_stock';
        """,
        (product_id,),
    ).fetchone()
    conn.close()
    return row["c"]


def transition_equipment(equipment_id, custodian_type, custodian_contact_id=None,
                         status=None, note=None, expected_return_at=None,
                         moved_by=None):
    """Change a machine's custody. Returns (ok, id-of-movement-or-message).

    Transitions ONLY (no delete): the equipment row updates in place (the
    machine's history lives in stock_movements), and an evidence movement is
    appended so 'where was the machine and since when' stays answerable.

    status defaults: warehouse→in_stock, customer→delivered, scrap→scrapped
    (caller may override, e.g. customer+loaned). scrap ignores the contact.
    """
    if custodian_type not in CUSTODIAN_TYPES:
        return False, "Nepoznat čuvar (custodian_type)."
    if custodian_type == "customer" and not custodian_contact_id:
        return False, "Čuvar 'customer' zahteva kontakt iz imenika."
    equipment = get_equipment(equipment_id)
    if equipment is None:
        return False, "Oprema ne postoji."
    if equipment["status"] == "scrapped" and custodian_type != "scrap":
        return False, "Rashodovana oprema se ne može vratiti u promet."

    if status is None:
        status = {
            "warehouse": "in_stock",
            "customer": "delivered",
            "scrap": "scrapped",
        }[custodian_type]
    if status not in EQUIPMENT_STATUS_VALUES:
        return False, "Nepoznat status opreme."
    if custodian_type in ("warehouse", "scrap"):
        custodian_contact_id = None

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE equipment
        SET custodian_type = ?, custodian_contact_id = ?, status = ?,
            since_date = ?, expected_return_at = ?
        WHERE id = ?;
        """,
        (custodian_type, custodian_contact_id, status, _today(),
         expected_return_at, equipment_id),
    )
    # Evidence movement: the registry is the truth; the ledger is the story.
    direction = "out" if custodian_type in ("customer", "scrap") else "in"
    reason = {
        ("customer", "loaned"): "loan",
        ("customer", "test_demo"): "test_demo",
    }.get((custodian_type, status), "sale" if custodian_type == "customer" else "return")
    if custodian_type == "scrap":
        reason = "scrap"
    cur.execute(
        """
        INSERT INTO stock_movements (product_id, equipment_id, name_snapshot,
                                     qty, direction, reason, contact_id,
                                     note, moved_at, moved_by)
        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?);
        """,
        (equipment["product_id"], equipment_id, equipment["name_snapshot"],
         direction, reason, custodian_contact_id, note,
         _utcnow_iso(), moved_by),
    )
    movement_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, movement_id


def equipment_history(equipment_id):
    """Everything that ever happened to one machine, oldest first."""
    return list_movements(equipment_id=equipment_id, limit=1000)


# ---------------------------------------------------------------------------
# reservations (coverage loop, free-text for whom)
# ---------------------------------------------------------------------------

def create_reservation(product_id=None, equipment_id=None, qty=None,
                       for_whom=None, note=None):
    """Reserve stock for someone. Returns (ok, id-or-message).

    Exactly one of product_id (qty regime) / equipment_id (pinned instance)
    is required; for_whom is REQUIRED (the whole point: two deals can't
    silently promise the same machine — blueprint amendment 1).
    """
    if not (for_whom or "").strip():
        return False, "Rezervacija mora imati 'za koga'."
    if (product_id is None) == (equipment_id is None):
        return False, "Rezervacija mora imati proizvod ILI mašinu (tačno jedno)."
    if product_id is not None:
        product = get_product(product_id)
        if product is None:
            return False, "Proizvod ne postoji."
        if product["tracking_regime"] != "qty":
            return False, "Količinska rezervacija je samo za 'qty' proizvode."
        if not qty or float(qty) <= 0:
            return False, "Količina rezervacije mora biti veća od nule."
    if equipment_id is not None:
        equipment = get_equipment(equipment_id)
        if equipment is None:
            return False, "Oprema ne postoji."

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO reservations (product_id, equipment_id, qty, for_whom,
                                  note, created_at, released_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL);
        """,
        (product_id, equipment_id, qty, for_whom.strip(), note, _utcnow_iso()),
    )
    reservation_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, reservation_id


def release_reservation(reservation_id):
    """Release (never delete) a reservation."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE reservations SET released_at = ? WHERE id = ? AND released_at IS NULL;",
        (_utcnow_iso(), reservation_id),
    )
    released = cur.rowcount
    conn.commit()
    conn.close()
    return (True, None) if released else (False, "Rezervacija nije aktivna.")


def list_reservations(active_only=True, product_id=None):
    """Reservations with resolved names; active first-class."""
    conn = get_db()
    cur = conn.cursor()
    sql = """
        SELECT r.*, p.name AS product_name,
               e.name_snapshot AS equipment_name, e.serial_number
        FROM reservations r
        LEFT JOIN products p ON p.id = r.product_id
        LEFT JOIN equipment e ON e.id = r.equipment_id
    """
    clauses, params = [], []
    if active_only:
        clauses.append("r.released_at IS NULL")
    if product_id is not None:
        clauses.append("r.product_id = ?")
        params.append(product_id)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY r.created_at DESC, r.id DESC;"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def reserved_qty(product_id):
    """Σ active reservation quantities for a qty-regime product."""
    conn = get_db()
    row = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) AS q FROM reservations "
        "WHERE product_id = ? AND released_at IS NULL;",
        (product_id,),
    ).fetchone()
    conn.close()
    return row["q"] or 0.0


def product_available(product_id):
    """ATP for one qty product: on_hand − Σ active reservations.
    (Incoming PO lines are a deferred batch — this is the v1 formula.)"""
    return qty_on_hand(product_id) - reserved_qty(product_id)


def coverage_rows():
    """The coverage/ATP view over ALL tracked products.

    One row per tracked product (qty or serialized):
      qty products        → on_hand, reserved, available (= ATP)
      serialized products → warehouse_count (derived from instances)
    untracked products never appear (regime gate).
    """
    rows = []
    for product in tracked_products():
        entry = dict(product)
        if product["tracking_regime"] == "qty":
            entry["on_hand"] = qty_on_hand(product["id"])
            entry["reserved"] = reserved_qty(product["id"])
            entry["available"] = entry["on_hand"] - entry["reserved"]
        else:  # serialized
            entry["on_hand"] = None
            entry["reserved"] = None
            entry["warehouse_count"] = warehouse_equipment_count(product["id"])
        rows.append(entry)
    return rows


# ---------------------------------------------------------------------------
# shortfalls (donor-part debts, amendment 5b)
# ---------------------------------------------------------------------------

def create_shortfall(equipment_id, part_product_id=None, part_name=None,
                     taken_at=None, po_ref=None, note=None):
    """Record 'device A owes a part' (delovi skinuti sa uređaja A).
    Returns (ok, id-or-message). part_product_id NULL = temp part
    (part_name then required)."""
    equipment = get_equipment(equipment_id)
    if equipment is None:
        return False, "Oprema ne postoji."
    resolved_name = part_name
    if not (resolved_name or "").strip() and part_product_id is not None:
        product = get_product(part_product_id)
        resolved_name = product["name"] if product else None
    if not (resolved_name or "").strip():
        return False, "Delo mora imati naziv (iz kataloga ili unet ručno)."
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO equipment_shortfalls (equipment_id, part_product_id,
                                          part_name, taken_at, po_ref,
                                          closed_at, note)
        VALUES (?, ?, ?, ?, ?, NULL, ?);
        """,
        (equipment_id, part_product_id, resolved_name.strip(),
         taken_at or _today(), (po_ref or "").strip() or None, note),
    )
    shortfall_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, shortfall_id


def close_shortfall(shortfall_id, note=None):
    """Settle the debt (closed_at set; the row stays — no deletes)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE equipment_shortfalls SET closed_at = ? WHERE id = ? AND closed_at IS NULL;",
        (_utcnow_iso(), shortfall_id),
    )
    closed = cur.rowcount
    conn.commit()
    conn.close()
    return (True, None) if closed else (False, "Nedostatak nije otvoren.")


def list_shortfalls(equipment_id=None, active_only=False):
    """Debts with the device resolved; open ones first."""
    conn = get_db()
    cur = conn.cursor()
    sql = """
        SELECT s.*, e.name_snapshot AS equipment_name, e.serial_number,
               p.name AS part_product_name
        FROM equipment_shortfalls s
        JOIN equipment e ON e.id = s.equipment_id
        LEFT JOIN products p ON p.id = s.part_product_id
    """
    clauses, params = [], []
    if equipment_id is not None:
        clauses.append("s.equipment_id = ?")
        params.append(equipment_id)
    if active_only:
        clauses.append("s.closed_at IS NULL")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY s.closed_at IS NOT NULL, s.taken_at DESC, s.id DESC;"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def open_shortfall_count(equipment_id):
    """The incomplete-device flag: >0 means the machine owes parts."""
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM equipment_shortfalls "
        "WHERE equipment_id = ? AND closed_at IS NULL;",
        (equipment_id,),
    ).fetchone()
    conn.close()
    return row["c"]
