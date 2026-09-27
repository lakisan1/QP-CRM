"""Product alias service (P5-T6): rename & merge safety for the catalogue.

WHY THIS EXISTS
---------------
The catalogue carries real duplicate/prefix names (the live DB has exactly
31 prefix pairs under canonical comparison, e.g. 'BODYGUARD 1.2' and
'BODYGUARD 1.2 Spoljasnja verzija'). A rename is already harmless -- every
row references products by id and issued documents keep their own frozen
line snapshots -- but a MERGE collapses two catalogue rows into one
concept, and the project rule is archive-only: nothing is ever deleted.

So a merge is expressed as an ALIAS MAP plus repointing, never as a delete:

  * ``product_aliases`` maps a canonicalized old/alternate NAME to the
    surviving product id (schema in shared/schema.py, single DDL source);
  * the merged-away SOURCE row stays exactly where it is, id and name
    included, so anything left un-repointed (or an old bookmark/report)
    still resolves to a real row and can be re-pointed later;
  * every column that genuinely holds a products(id) reference is re-pointed
    to the target, so the canonical row carries the whole history.

Read-time resolution is ``resolve_name``: live product name first, alias
second -- with ONE deliberate merge exception (see resolve_name).

All functions are short-lived-connection: a fresh get_db() per call, always
closed in a finally. A leaked connection holds a SQLite WAL read lock and
the next write dies with 'database is locked'.

Service-layer only: no UI, no routes, no blueprint (P5-T6 boundary).
"""

import re
import unicodedata
from datetime import datetime, timezone

from qp_crm.shared.db import get_db

# Every column in the schema that holds a products(id) reference. merge_products
# re-points only the ones that actually exist in the connected DB: legacy
# databases predate the P5 warehouse tables entirely.
PRODUCT_REFERENCE_COLUMNS = (
    ("prices", "product_id"),
    ("offer_items", "product_id"),
    ("equipment", "product_id"),
    ("stock_movements", "product_id"),
    ("reservations", "product_id"),
    ("equipment_shortfalls", "part_product_id"),
)

# Product-ish names that LOOK like references but are deliberately NOT
# re-pointed by a merge. Reported in the merge summary so nothing is skipped
# silently.
NOT_REPOINTED_REASONS = {
    "products.site_product_id":
        "referencira site_products(id), ne products(id) -- eksterni WP link ne prati spajanje.",
    "products.product_code":
        "slobodan kataloški kod, nije referenca na products(id).",
    "equipment.name_snapshot":
        "zamrznuti snapshot naziva (istorija ostaje onakva kakva je izdata).",
    "stock_movements.name_snapshot":
        "zamrznuti snapshot naziva (temp proizvodi / istorija).",
    "offer_items.item_name":
        "zamrznuti snapshot stavke -- izdate ponude se nikad ne prepisuju.",
    "rent_contracts.equipment_model":
        "slobodan tekst; rent više nema products(id) kolonu (rent_equipment ukinut, R-T8).",
}

_WHITESPACE = re.compile(r"\s+")


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# canonical name key
# ---------------------------------------------------------------------------

def normalize(name):
    """The canonical comparison key for product names.

    NFKC -> strip -> collapse internal whitespace -> casefold. Deterministic
    and total: None and blanks normalize to "" (callers treat that as "no
    name"). NFKC folds compatibility forms (e.g. full-width chars) that
    plain casefold would miss; casefold (not lower) is the Unicode-correct
    case mapping, so 'BODYGUARD' and 'bodyguard' are one key.

    This is THE key every alias row stores, so lookups are plain equality.
    """
    if name is None:
        return ""
    return _WHITESPACE.sub(
        " ", unicodedata.normalize("NFKC", str(name)).strip()
    ).casefold()


# ---------------------------------------------------------------------------
# internal helpers (one connection: caller owns it)
# ---------------------------------------------------------------------------

def _find_live_product(cur, key):
    """The products row whose name normalizes to `key`, or None.

    Fast path: the indexed `name COLLATE NOCASE` lookup (idx_products_name_
    unique already exists) with the raw key. Fallback: a normalized scan,
    because SQLite's lower()/NOCASE is ASCII-only and cannot collapse
    whitespace the way normalize() does. The catalogue is ~254 rows, so the
    fallback is cheap and only runs when the indexed probe found nothing.
    """
    if not key:
        return None
    row = cur.execute(
        "SELECT id, name FROM products WHERE name = ? COLLATE NOCASE LIMIT 1;",
        (key,),
    ).fetchone()
    if row is not None and normalize(row["name"]) == key:
        return row
    for candidate in cur.execute("SELECT id, name FROM products;").fetchall():
        if normalize(candidate["name"]) == key:
            return candidate
    return None


def _alias_row(cur, key):
    return cur.execute(
        "SELECT id, product_id FROM product_aliases WHERE alias = ? LIMIT 1;",
        (key,),
    ).fetchone()


def _column_exists(cur, table, column):
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?;",
        (table,),
    ).fetchone()
    if row is None:
        return False
    return any(
        info["name"] == column
        for info in cur.execute(f"PRAGMA table_info({table});").fetchall()
    )


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def add_alias(alias, product_id):
    """Register `alias` as an alternate name of `product_id`.

    Returns (ok, alias_id_or_message). Refusals:
      * blank alias;
      * the product does not exist (checked here so the enforced FK never
        has to blow up);
      * the alias is already the canonical name of a LIVE product -- that
        would make resolve_name ambiguous, so it is rejected;
      * the alias already maps to a DIFFERENT product.

    Idempotent: re-adding the same alias for the same product returns the
    existing row's id and writes nothing.
    """
    key = normalize(alias)
    if not key:
        return False, "Alias ne sme biti prazan."
    conn = get_db()
    try:
        cur = conn.cursor()
        product = cur.execute(
            "SELECT id FROM products WHERE id = ?;", (product_id,)).fetchone()
        if product is None:
            return False, f"Proizvod #{product_id} ne postoji."

        existing = _alias_row(cur, key)
        if existing is not None:
            if existing["product_id"] == product_id:
                return True, existing["id"]
            return False, (
                f"Alias '{str(alias).strip()}' je već dodeljen proizvodu "
                f"#{existing['product_id']}."
            )

        live = _find_live_product(cur, key)
        if live is not None:
            return False, (
                f"'{str(alias).strip()}' je i sam naziv proizvoda #{live['id']} "
                "-- alias bi bio dvosmislen."
            )

        cur.execute(
            "INSERT INTO product_aliases (alias, product_id, created_at) "
            "VALUES (?, ?, ?);",
            (key, product_id, _utcnow_iso()),
        )
        conn.commit()
        return True, cur.lastrowid
    finally:
        conn.close()


def resolve_name(name):
    """Resolve a product NAME to a product id, or None.

    Order: exact live product name first, then the alias table -- with one
    deliberate exception. A name that is BOTH a live product name and an
    alias of a DIFFERENT product can only be the merged-away source of
    merge_products (add_alias refuses to create that collision). There the
    ALIAS MUST WIN, otherwise the merge would not resolve at all: the source
    row is left in place on purpose, but its old name has to lead to the
    canonical target.
    """
    key = normalize(name)
    if not key:
        return None
    conn = get_db()
    try:
        cur = conn.cursor()
        live = _find_live_product(cur, key)
        alias = _alias_row(cur, key)
        if alias is not None and (live is None or alias["product_id"] != live["id"]):
            return alias["product_id"]
        return live["id"] if live is not None else None
    finally:
        conn.close()


def merge_products(source_id, target_id):
    """Merge `source_id` INTO `target_id`. Nothing is ever deleted.

    One connection, one commit. Steps:
      1. validate: both rows exist, source != target, and neither side is
         itself a merged-away row (an alias for its own name pointing
         elsewhere) -- that would create an alias CHAIN;
      2. record the source's current name as an alias of the target;
      3. re-point every EXISTING products(id) reference column from source
         to target (PRODUCT_REFERENCE_COLUMNS): price history, offer lines,
         equipment instances, movement ledger, reservations, shortfall
         parts. No rows are deleted, so the canonical product gains the
         whole history and the source's prices stay where they are (just
         re-labelled);
      4. re-point aliases that already resolved to the source onto the
         target (no alias may end up pointing at a merged-away row);
      5. leave the source row in place, untouched otherwise.

    Returns (ok, summary). On success summary is a dict:
        {"source_id", "target_id", "alias", "alias_id",
         "repointed": {table.column: rows}, "aliases_repointed": n,
         "skipped": {name: reason}, "message": human-readable string}
    and 'skipped' names every reference-like column that was deliberately
    NOT re-pointed (plus candidate columns missing from this DB), so nothing
    is skipped silently. On failure the second element is a plain string
    reason (no summary exists to report).
    """
    conn = get_db()
    try:
        cur = conn.cursor()
        source = cur.execute(
            "SELECT id, name FROM products WHERE id = ?;", (source_id,)).fetchone()
        if source is None:
            return False, f"Izvor #{source_id} ne postoji."
        target = cur.execute(
            "SELECT id, name FROM products WHERE id = ?;", (target_id,)).fetchone()
        if target is None:
            return False, f"Cilj #{target_id} ne postoji."
        if source_id == target_id:
            return False, "Izvor i cilj su isti proizvod."

        key = normalize(source["name"])
        if not key:
            return False, f"Izvor #{source_id} nema naziv."

        # No alias chains: a side whose own name already resolves somewhere
        # else is itself a merged-away row.
        source_alias = _alias_row(cur, key)
        if source_alias is not None and source_alias["product_id"] != target_id:
            return False, (
                f"Izvor #{source_id} je već spojen u #{source_alias['product_id']} "
                "-- spajanje bi napravilo lanac alijasa."
            )
        target_alias = _alias_row(cur, normalize(target["name"]))
        if target_alias is not None and target_alias["product_id"] != target_id:
            return False, (
                f"Cilj #{target_id} je i sam spojen u #{target_alias['product_id']} "
                "-- koristite taj proizvod kao cilj."
            )

        # (2) the source's name becomes an alias of the target. Deliberately
        # bypasses add_alias's live-name guard: the source row stays in
        # place, so its name IS still a live name, and resolve_name resolves
        # that collision in the alias's favour -- that is what makes the
        # merge visible without touching the source row.
        if source_alias is None:
            cur.execute(
                "INSERT INTO product_aliases (alias, product_id, created_at) "
                "VALUES (?, ?, ?);",
                (key, target_id, _utcnow_iso()),
            )
            alias_id = cur.lastrowid
        else:
            alias_id = source_alias["id"]

        # (3) re-point every products(id) reference that exists.
        repointed = {}
        skipped = {}
        for table, column in PRODUCT_REFERENCE_COLUMNS:
            label = f"{table}.{column}"
            if not _column_exists(cur, table, column):
                skipped[label] = "kolona/tabela ne postoji u ovoj bazi (legacy)."
                continue
            cur.execute(
                f"UPDATE {table} SET {column} = ? WHERE {column} = ?;",
                (target_id, source_id),
            )
            repointed[label] = cur.rowcount

        # (4) any alias that used to resolve to the source now resolves to
        # the canonical target (the just-inserted name alias already does).
        cur.execute(
            "UPDATE product_aliases SET product_id = ? WHERE product_id = ?;",
            (target_id, source_id),
        )
        aliases_repointed = cur.rowcount

        # Reference-like columns a merge deliberately leaves alone, reported
        # so the caller is never misled by silence.
        skipped.update(NOT_REPOINTED_REASONS)

        conn.commit()
        message = (
            f"Spojen #{source_id} ('{source['name']}') u #{target_id} "
            f"('{target['name']}'); preusmereno: "
            + ", ".join(f"{k}={v}" for k, v in repointed.items())
            + f"; alijasa preusmereno={aliases_repointed}; "
            f"namerno nedirnuto: {', '.join(sorted(skipped))}."
        )
        return True, {
            "source_id": source_id,
            "target_id": target_id,
            "alias": key,
            "alias_id": alias_id,
            "repointed": repointed,
            "aliases_repointed": aliases_repointed,
            "skipped": skipped,
            "message": message,
        }
    finally:
        conn.close()


def group_duplicate_suspects():
    """READ-ONLY grouping of catalogue rows whose names collide or nest.

    Two rows are grouped when their normalized names are EQUAL or when one
    is a PREFIX of the other (naive normalized startswith -- that is exactly
    the rule that yields the 31 known prefix pairs on the live 254-product
    catalogue, e.g. 'BODYGUARD 1.2' / 'BODYGUARD 1.2 Spoljasnja verzija').
    Grouping is transitive, so a chain like MONTY 3550 / MONTY 3550 GP /
    MONTY 3550 GP Plus lands in ONE group instead of three pairs.

    Returns a list of groups (>= 2 members), each:
        {"key": shortest normalized name, "kind": "equal" | "prefix",
         "size": n, "products": [{"id", "name", "item_type",
                                  "tracking_regime"}, ...]}
    Members are ordered by normalized name. Pure read: no writes, and the
    connection is closed before grouping runs.
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name, item_type, tracking_regime FROM products "
            "ORDER BY name;"
        ).fetchall()
    finally:
        conn.close()

    entries = [
        {
            "id": row["id"],
            "name": row["name"],
            "item_type": row["item_type"],
            "tracking_regime": row["tracking_regime"],
            "key": normalize(row["name"]),
        }
        for row in rows
    ]
    count = len(entries)
    parent = list(range(count))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left, right):
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for i in range(count):
        for j in range(i + 1, count):
            left, right = entries[i]["key"], entries[j]["key"]
            if not left or not right:
                continue
            if left == right or left.startswith(right) or right.startswith(left):
                union(i, j)

    buckets = {}
    for index, entry in enumerate(entries):
        buckets.setdefault(find(index), []).append(entry)

    groups = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda item: item["key"])
        keys = {item["key"] for item in members}
        groups.append({
            "key": min(keys),
            "kind": "equal" if len(keys) == 1 else "prefix",
            "size": len(members),
            "products": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "item_type": item["item_type"],
                    "tracking_regime": item["tracking_regime"],
                }
                for item in members
            ],
        })
    groups.sort(key=lambda group: group["key"])
    return groups
