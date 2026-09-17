"""Contact services (P5-pre): the shared directory (Zajednički imenik).

Business logic for the contacts app; route modules keep HTTP concerns
(services-layer pattern, P2 stage 4). Conventions enforced here:

  * NO deletes: a contact archives (archived flag) -- the directory is
    master data referenced by rent/poslovi/ponude/radni nalozi, so a row
    never disappears (blueprint §4 rule 5).
  * Names resolve at read time: callers store contact ids, views join for
    the display name. Renaming a contact = editing one master row.
  * Roles are rows in contact_roles (fixed CONTACT_ROLES list); a contact
    may hold several roles at once. Role filtering is the AND-able
    `role IN (...)` read below, not a boolean column.
  * KIND is exactly one of CONTACT_KINDS: 'company' (legal entity: PIB/MB/
    account) or 'person' (first/last name, JMBG, job_title). The service
    rejects an empty display_name and normalizes kind/role values so the
    fixed lists stay closed.
  * user_id (employee role -> login account) and customer_id (client role
    -> deals-spine customers row) are optional links -- set/cleared through
    update_contact only, never touched by archive.

The directory is INDEPENDENT of the P4 customers spine: customers keeps
being the billing/deal party model; contacts is the wider registry every
module shares. When the same party both buys and appears in the directory,
the contact row carries customer_id so both worlds resolve each other by id.
"""
from qp_crm.shared.db import get_db

from qp_crm.shared.schema import CONTACT_KINDS, CONTACT_ROLES

_VALID_KINDS = frozenset(CONTACT_KINDS)
_VALID_ROLES = frozenset(CONTACT_ROLES)

# Fields every caller may pass; update_contact whitelists on this set so a
# form can never write a column this module does not own.
_CONTACT_FIELDS = (
    "kind", "display_name", "first_name", "last_name", "jmbg", "pib", "mb",
    "account", "billing_address", "city", "country", "email", "phone",
    "job_title", "user_id", "customer_id", "notes",
)


def _utcnow_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_contacts(include_archived=False, search="", roles=None, kind=None):
    """Directory rows for lists/pickers, newest-relevant last.

    roles:   None = all; a sequence filters to contacts holding ANY of the
             given roles (a supplier+client contact matches both).
    kind:    None = all; 'company' | 'person'.
    Search matches display_name, first/last, pib, mb, jmbg, email, phone,
    city -- the fields a receptionist actually types.
    """
    conn = get_db()
    cur = conn.cursor()
    sql = "SELECT DISTINCT c.* FROM contacts c"
    clauses, params = [], []
    if roles:
        wanted = [r for r in (roles or []) if r in _VALID_ROLES]
        if wanted:
            placeholders = ",".join("?" for _ in wanted)
            sql += (f" JOIN contact_roles cr ON cr.contact_id = c.id "
                    f"AND cr.role IN ({placeholders})")
            params += wanted
    if not include_archived:
        clauses.append("c.archived = 0")
    if kind in _VALID_KINDS:
        clauses.append("c.kind = ?")
        params.append(kind)
    if search:
        clauses.append(
            "(c.display_name LIKE ? OR c.first_name LIKE ? OR c.last_name LIKE ? "
            "OR c.pib LIKE ? OR c.mb LIKE ? OR c.jmbg LIKE ? OR c.email LIKE ? "
            "OR c.phone LIKE ? OR c.city LIKE ?)")
        like = f"%{search}%"
        params += [like] * 9
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY c.display_name COLLATE NOCASE;"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def get_contact(contact_id):
    """One contact row plus its roles (roles list in row['roles'])."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM contacts WHERE id = ?;", (contact_id,))
    row = cur.fetchone()
    if row is not None:
        cur.execute(
            "SELECT role FROM contact_roles WHERE contact_id = ? ORDER BY role;",
            (contact_id,),
        )
        row = dict(row)
        row["roles"] = [r["role"] for r in cur.fetchall()]
    conn.close()
    return row


def create_contact(display_name, kind="company", roles=(), fields=None):
    """Create a directory entry. Returns (ok, id_or_message).

    display_name is mandatory for both kinds (a person without a name is
    not an entry). roles outside the fixed list are ignored silently --
    same closed-list discipline as set_user_modules.
    """
    display_name = (display_name or "").strip()
    if not display_name:
        return False, "Naziv kontakta je obavezan."
    if kind not in _VALID_KINDS:
        kind = "company"
    fields = fields or {}
    clean_roles = sorted({r for r in (roles or []) if r in _VALID_ROLES})

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO contacts (kind, display_name, first_name, last_name, jmbg,
                              pib, mb, account, billing_address, city, country,
                              email, phone, job_title, user_id, customer_id,
                              notes, created_at, archived)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0);
        """,
        (
            kind,
            display_name,
            (fields.get("first_name") or "").strip(),
            (fields.get("last_name") or "").strip(),
            (fields.get("jmbg") or "").strip(),
            (fields.get("pib") or "").strip(),
            (fields.get("mb") or "").strip(),
            (fields.get("account") or "").strip(),
            (fields.get("billing_address") or "").strip(),
            (fields.get("city") or "").strip(),
            (fields.get("country") or "").strip(),
            (fields.get("email") or "").strip(),
            (fields.get("phone") or "").strip(),
            (fields.get("job_title") or "").strip(),
            fields.get("user_id") or None,
            fields.get("customer_id") or None,
            (fields.get("notes") or "").strip(),
            _utcnow_iso(),
        ),
    )
    contact_id = cur.lastrowid
    for role in clean_roles:
        cur.execute(
            "INSERT OR IGNORE INTO contact_roles (contact_id, role) VALUES (?, ?);",
            (contact_id, role),
        )
    conn.commit()
    conn.close()
    return True, contact_id


def update_contact(contact_id, display_name, kind=None, roles=None, fields=None):
    """Edit master data (and replace the role set when roles is not None).

    Rename is safe by design: everything links by id. Returns
    (ok, id_or_message).
    """
    display_name = (display_name or "").strip()
    if not display_name:
        return False, "Naziv kontakta je obavezan."
    fields = fields or {}
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, kind FROM contacts WHERE id = ?;", (contact_id,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return False, "Kontakt nije pronađen."
    new_kind = kind if kind in _VALID_KINDS else row["kind"]

    writable = tuple(_CONTACT_FIELDS)
    assignments, params = ["display_name = ?", "kind = ?"], [display_name, new_kind]
    for field in writable:
        if field in ("kind", "display_name"):
            continue
        value = fields.get(field)
        if field in ("user_id", "customer_id"):
            value = value or None
        else:
            value = (value or "").strip()
        assignments.append(f"{field} = ?")
        params.append(value)
    params.append(contact_id)
    cur.execute(
        f"UPDATE contacts SET {', '.join(assignments)} WHERE id = ?;", params)

    if roles is not None:
        clean_roles = sorted({r for r in roles if r in _VALID_ROLES})
        cur.execute("DELETE FROM contact_roles WHERE contact_id = ?;", (contact_id,))
        for role in clean_roles:
            cur.execute(
                "INSERT OR IGNORE INTO contact_roles (contact_id, role) VALUES (?, ?);",
                (contact_id, role),
            )
    conn.commit()
    conn.close()
    return True, contact_id


def set_contact_archived(contact_id, archived):
    """Archive (never delete) a contact. Returns (ok, message)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM contacts WHERE id = ?;", (contact_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Kontakt nije pronađen."
    cur.execute("UPDATE contacts SET archived = ? WHERE id = ?;",
                (1 if archived else 0, contact_id))
    conn.commit()
    conn.close()
    return True, "ok"


def roles_of(contact_id):
    """Role names held by one contact (empty list when unknown)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT role FROM contact_roles WHERE contact_id = ? ORDER BY role;",
        (contact_id,),
    )
    roles = [r["role"] for r in cur.fetchall()]
    conn.close()
    return roles


def contacts_by_role(role, include_archived=False):
    """All contacts holding exactly one role (picker feed).

    Unknown role names return an empty list, keeping the fixed list closed.
    """
    if role not in _VALID_ROLES:
        return []
    return list_contacts(include_archived=include_archived, roles=[role])


# ---------------------------------------------------------------------------
# cross-module lookup feeds (read-only views over the directory)
# ---------------------------------------------------------------------------

def directory_choices(roles=None, include_archived=False):
    """(id, label) feed for shared pickers in rent/ponude/poslovi.

    Label shape: display name + role hint + distinguishing document number
    (PIB for companies, JMBG for persons) so same-named entries stay
    tellable apart in a dropdown.
    """
    rows = list_contacts(include_archived=include_archived, roles=roles)
    choices = []
    for row in rows:
        badge = row["pib"] or row["jmbg"] or ""
        label = row["display_name"] + (f" ({badge})" if badge else "")
        choices.append((row["id"], label))
    return choices


def find_by_user_id(user_id):
    """Directory entry linked to an app login account, or None."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM contacts WHERE user_id = ?;", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# contact ↔ customer/location links
# ---------------------------------------------------------------------------

def list_links(contact_id):
    """All directory links of one contact, resolved with party names.

    Names join live at read time (customers.display-name equivalents), so
    renaming a customer/location never orphans a link label.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT l.*, c.name AS customer_name, loc.name AS location_name
        FROM contact_links l
        LEFT JOIN customers c ON c.id = l.customer_id
        LEFT JOIN customer_locations loc ON loc.id = l.location_id
        WHERE l.contact_id = ?
        ORDER BY l.is_primary DESC, l.id;
        """,
        (contact_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def create_link(contact_id, customer_id=None, location_id=None, relation="",
                is_primary=False, notes=""):
    """Attach a contact to a customer (optionally one of its sites).

    Returns (ok, id_or_message). A location must belong to the given
    customer -- the link records where AT WHOM the contact matters, and a
    site of another customer would be a data error, not a style choice.
    """
    customer_id = customer_id or None
    location_id = location_id or None
    if customer_id is None and location_id is None:
        return False, "Veza zahteva kupca ili lokaciju."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM contacts WHERE id = ?;", (contact_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Kontakt nije pronađen."
    if customer_id is not None:
        cur.execute("SELECT id FROM customers WHERE id = ?;", (customer_id,))
        if cur.fetchone() is None:
            conn.close()
            return False, "Kupac nije pronađen."
    if location_id is not None:
        cur.execute("SELECT customer_id FROM customer_locations WHERE id = ?;",
                    (location_id,))
        row = cur.fetchone()
        if row is None:
            conn.close()
            return False, "Lokacija nije pronađena."
        if customer_id is None:
            customer_id = row["customer_id"]
        elif customer_id != row["customer_id"]:
            conn.close()
            return False, "Lokacija ne pripada datom kupcu."
    cur.execute(
        """
        INSERT INTO contact_links (contact_id, customer_id, location_id,
                                   relation, is_primary, notes)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (contact_id, customer_id, location_id, (relation or "").strip(),
         1 if is_primary else 0, (notes or "").strip()),
    )
    link_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, link_id


def delete_link(contact_id, link_id):
    """Remove one link row (the LINK, never the contact)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM contact_links WHERE id = ? AND contact_id = ?;",
                (link_id, contact_id))
    if cur.fetchone() is None:
        conn.close()
        return False, "Veza nije pronađena."
    cur.execute("DELETE FROM contact_links WHERE id = ?;", (link_id,))
    conn.commit()
    conn.close()
    return True, "ok"
