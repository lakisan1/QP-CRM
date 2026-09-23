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
  * user_id (employee role -> login account) is an optional link --
    set/cleared through update_contact only, never touched by archive.

The directory is the ONLY party registry (user decision 2026-09-16: the
deals-spine customers tables were removed). Every module -- rent, offers,
future poslovi/radni nalozi -- reads parties from here.
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
    "job_title", "user_id", "notes",
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
                              email, phone, job_title, user_id,
                              notes, created_at, archived)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0);
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
        if field == "user_id":
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
# contact locations (sites of one contact -- the directory's own children)
# ---------------------------------------------------------------------------

def list_contact_locations(contact_id):
    """All site rows of one contact, oldest first."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM contact_locations WHERE contact_id = ? ORDER BY id;",
        (contact_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def create_contact_location(contact_id, name, address="", city="",
                            contact_name="", contact_phone="", notes=""):
    """Add a site to a contact. Returns (ok, id_or_message)."""
    name = (name or "").strip()
    if not name:
        return False, "Naziv lokacije je obavezan."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM contacts WHERE id = ?;", (contact_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Kontakt nije pronađen."
    cur.execute(
        """
        INSERT INTO contact_locations (contact_id, name, address, city,
                                       contact_name, contact_phone, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (contact_id, name, (address or "").strip(), (city or "").strip(),
         (contact_name or "").strip(), (contact_phone or "").strip(),
         (notes or "").strip()),
    )
    location_id = cur.lastrowid
    conn.commit()
    conn.close()
    return True, location_id


def update_contact_location(location_id, name, address="", city="",
                            contact_name="", contact_phone="", notes=""):
    """Edit one site row. Returns (ok, message)."""
    name = (name or "").strip()
    if not name:
        return False, "Naziv lokacije je obavezan."
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM contact_locations WHERE id = ?;", (location_id,))
    if cur.fetchone() is None:
        conn.close()
        return False, "Lokacija nije pronađena."
    cur.execute(
        """
        UPDATE contact_locations SET name = ?, address = ?, city = ?,
                                     contact_name = ?, contact_phone = ?, notes = ?
        WHERE id = ?;
        """,
        (name, (address or "").strip(), (city or "").strip(),
         (contact_name or "").strip(), (contact_phone or "").strip(),
         (notes or "").strip(), location_id),
    )
    conn.commit()
    conn.close()
    return True, "ok"


def linked_documents(contact_id):
    """Everything across modules that references one directory entry.

    Read-time joins over the consumers' id links (offers.contact_id,
    rent_contracts.contact_id); issued documents stay frozen snapshots, so
    this list is WHO the party did business with, resolved live.
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 'offer' AS doc_type, id, offer_number AS doc_number,
               date AS doc_date, client_name AS title_hint, NULL AS url_id
        FROM offers WHERE contact_id = ?
        UNION ALL
        SELECT 'rent_contract' AS doc_type, id, contract_number AS doc_number,
               contract_date AS doc_date, client_name AS title_hint, NULL AS url_id
        FROM rent_contracts WHERE contact_id = ?
        ORDER BY doc_date, doc_type;
        """,
        (contact_id, contact_id),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# legacy-document backfill (musterija-first era): link existing documents
# ---------------------------------------------------------------------------

def _contact_indexes(cur):
    """PIB / MB / normalized-name indexes over ACTIVE directory contacts.

    Name key is case-folded and whitespace-squeezed so 'Delta Automoto
    d.o.o.' and 'delta  automoto D.O.O.' hit the same entry; unicode
    letters (Greek ΣΥΝΕΡΓΕΙΟ) pass through unchanged.
    """
    cur.execute("SELECT id, display_name, pib, mb FROM contacts WHERE archived = 0;")
    by_pib, by_mb, by_name = {}, {}, {}
    for row in cur.fetchall():
        if row["pib"] and row["pib"].strip():
            by_pib.setdefault(row["pib"].strip(), row["id"])
        if row["mb"] and row["mb"].strip():
            by_mb.setdefault(row["mb"].strip(), row["id"])
        key = " ".join((row["display_name"] or "").split()).casefold()
        if key:
            by_name.setdefault(key, row["id"])
    return by_pib, by_mb, by_name


def link_documents_to_contacts(cur):
    """Backfill offers.contact_id / rent_contracts.contact_id (idempotent).

    Only rows with contact_id IS NULL are considered. Match order per row:

      1. PIB match (the tax id is THE identity for companies) — but ONLY
         when the document's name casefold-matches the contact too OR the
         document has no name; a PIB hit on a DIFFERENT name is a data
         conflict and stays unlinked;
      2. MB match, same guard;
      3. exact normalized name match (PIB/MB absent on the document) —
         covers ΣΥΝΕΡΓΕΙΟ-type rows where no tax id was captured.

    Rows whose PIB/MB disagree with the name-matched contact (HIDRAULIK
    FLEX carrying two different PIBs) are deliberately left unlinked --
    wrong-identity links corrupt the directory's document history; they
    surface as reusable pickers with a NULL link for manual review.

    Snapshot fields are NEVER rewritten; this only sets the id link.
    Returns the number of newly linked rows (offers + rent contracts).
    """
    cur.execute("SELECT id, client_name, client_pib, client_mb FROM offers WHERE contact_id IS NULL;")
    offer_rows = cur.fetchall()
    cur.execute("SELECT id, client_name, client_pib, client_mb FROM rent_contracts WHERE contact_id IS NULL;")
    rent_rows = cur.fetchall()
    if not offer_rows and not rent_rows:
        return 0

    by_pib, by_mb, by_name = _contact_indexes(cur)

    def resolve(client_name, pib, mb):
        name_key = " ".join((client_name or "").split()).casefold()
        pib = (pib or "").strip()
        mb = (mb or "").strip()
        if pib:
            hit = by_pib.get(pib)
            if hit is None:
                return None  # PIB present but unknown -> no guesswork
            hit_name = None
            for key, cid in by_name.items():
                if cid == hit:
                    hit_name = key
                    break
            # PIB hit accepted only when the name agrees (or doc has no name)
            if not name_key or hit_name == name_key:
                return hit
            return None  # PIB belongs to a differently-named party
        if mb:
            hit = by_mb.get(mb)
            if hit is None:
                return None
            hit_name = next((key for key, cid in by_name.items() if cid == hit), None)
            if not name_key or hit_name == name_key:
                return hit
            return None
        return by_name.get(name_key)  # no tax id: exact name only

    linked = 0
    for row in offer_rows:
        cid = resolve(row["client_name"], row["client_pib"], row["client_mb"])
        if cid is not None:
            cur.execute("UPDATE offers SET contact_id = ? WHERE id = ?;", (cid, row["id"]))
            linked += 1
    for row in rent_rows:
        cid = resolve(row["client_name"], row["client_pib"], row["client_mb"])
        if cid is not None:
            cur.execute("UPDATE rent_contracts SET contact_id = ? WHERE id = ?;", (cid, row["id"]))
            linked += 1
    return linked
