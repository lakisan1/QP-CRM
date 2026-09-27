"""P5-T6 product alias service tests.

Spec tests for the NEW alias/merge layer. This is the half of P5 that makes
renames and merges safe under the archive-only rule: a merge records the
merged-away name as an alias, re-points every real products(id) reference,
and leaves the source row (and every price row) in place.

The session-wide temp_db is shared with the rest of the suite, so every
fixture name carries the ZZT6 prefix and assertions are membership-based --
never absolute catalogue counts.
"""

import sqlite3

import pytest

from qp_crm.shared.db import get_db
from qp_crm.services import product_alias_service as aliases

PREFIX = "ZZT6"


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


def _insert(table, **columns):
    """One row via a short-lived connection (ALWAYS closed -- a leaked
    connection holds a WAL read lock and the next write dies with
    'database is locked')."""
    conn = get_db()
    try:
        cur = conn.cursor()
        names = ", ".join(columns)
        marks = ", ".join("?" for _ in columns)
        cur.execute(
            f"INSERT INTO {table} ({names}) VALUES ({marks});",
            tuple(columns.values()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _scalar(sql, params=()):
    conn = get_db()
    try:
        row = conn.execute(sql, params).fetchone()
        return None if row is None else row[0]
    finally:
        conn.close()


def _new_product(suffix, **extra):
    columns = {
        "name": f"{PREFIX} {suffix}",
        "item_type": "proizvod",
        "tracking_regime": "qty",
    }
    columns.update(extra)
    return _insert("products", **columns)


# ---------------------------------------------------------------------------
# normalize -- the one canonical comparison key
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, ""),
    ("", ""),
    ("   ", ""),
    ("  BODYGUARD 1.2  ", "bodyguard 1.2"),
    ("Foo\t Bar\nBaz", "foo bar baz"),
    ("BODYGUARD", "bodyguard"),
])
def test_normalize(raw, expected):
    assert aliases.normalize(raw) == expected


def test_normalize_is_deterministic_and_idempotent():
    once = aliases.normalize("  BODYGUARD   1.2 ")
    assert once == "bodyguard 1.2"
    assert aliases.normalize(once) == once


# ---------------------------------------------------------------------------
# add_alias -- validation, live-name rejection, idempotency
# ---------------------------------------------------------------------------

def test_add_alias_rejects_missing_product():
    ok, message = aliases.add_alias(f"{PREFIX} nema proizvoda", 10 ** 9)
    assert ok is False
    assert "ne postoji" in message


def test_add_alias_rejects_blank_alias():
    pid = _new_product("blank-target")
    ok, message = aliases.add_alias("   ", pid)
    assert ok is False
    assert "prazan" in message


def test_add_alias_rejects_alias_equal_to_a_live_product_name():
    live = _new_product("Live Name")
    other = _new_product("live-name-other-target")
    # same name modulo case/whitespace -- normalize makes it a collision
    ok, message = aliases.add_alias(f"  {PREFIX}   live  NAME ", other)
    assert ok is False
    assert f"#{live}" in message


def test_add_alias_stores_canonical_key_and_is_idempotent():
    pid = _new_product("stari-naziv-target")
    ok, alias_id = aliases.add_alias(f"{PREFIX} Stari Naziv", pid)
    assert ok is True
    assert isinstance(alias_id, int)
    assert _scalar(
        "SELECT alias FROM product_aliases WHERE id = ?;", (alias_id,)
    ) == "zzt6 stari naziv"

    ok_again, alias_id_again = aliases.add_alias(f"  {PREFIX}  STARI naziv ", pid)
    assert (ok_again, alias_id_again) == (True, alias_id)
    assert _scalar(
        "SELECT COUNT(*) FROM product_aliases WHERE alias = ?;",
        ("zzt6 stari naziv",),
    ) == 1


def test_add_alias_rejects_alias_owned_by_another_product():
    first = _new_product("owner-a")
    second = _new_product("owner-b")
    assert aliases.add_alias(f"{PREFIX} Deljeni Alias", first)[0] is True
    ok, message = aliases.add_alias(f"{PREFIX} Deljeni Alias", second)
    assert ok is False
    assert f"#{first}" in message


def test_alias_table_enforces_fk_and_unique():
    # FK is enforced (PRAGMA foreign_keys = ON everywhere): the service check
    # exists so this never happens through add_alias, but the DB backs it up.
    conn = get_db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO product_aliases (alias, product_id, created_at) "
                "VALUES (?, ?, ?);",
                ("zzt6 fk ghost", 10 ** 9, "2026-01-01"),
            )
        conn.rollback()
    finally:
        conn.close()

    pid = _new_product("unique-alias-target")
    assert aliases.add_alias(f"{PREFIX} Unique Alias", pid)[0] is True
    conn = get_db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO product_aliases (alias, product_id, created_at) "
                "VALUES (?, ?, ?);",
                ("zzt6 unique alias", pid, "2026-01-01"),
            )
        conn.rollback()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# resolve_name -- both paths
# ---------------------------------------------------------------------------

def test_resolve_name_by_live_product_name_is_case_and_space_insensitive():
    pid = _new_product("Resolve Live")
    assert aliases.resolve_name(f"{PREFIX} resolve live") == pid
    assert aliases.resolve_name(f"  {PREFIX}   RESOLVE   LIVE  ") == pid


def test_resolve_name_by_alias():
    pid = _new_product("resolve-alias-target")
    assert aliases.add_alias(f"{PREFIX} Resolve Alias Old", pid)[0] is True
    assert aliases.resolve_name(f"{PREFIX} resolve alias old") == pid
    assert aliases.resolve_name(f"  {PREFIX}  RESOLVE  alias OLD ") == pid


def test_resolve_name_unknown_and_blank_returns_none():
    assert aliases.resolve_name(f"{PREFIX} ovog nema") is None
    assert aliases.resolve_name(None) is None
    assert aliases.resolve_name("   ") is None


# ---------------------------------------------------------------------------
# merge_products -- alias + repoint + source row survives
# ---------------------------------------------------------------------------

def _seed_references(product_id):
    """One row in EVERY products(id) reference column, pointing at product_id."""
    equipment_id = _insert(
        "equipment",
        product_id=product_id,
        name_snapshot="snapshot ostaje",
        since_date="2026-01-01",
        status="in_stock",
        custodian_type="warehouse",
    )
    offer_id = _insert("offers", offer_number=f"{PREFIX}-OFFER", date="2026-01-01")
    _insert("prices", product_id=product_id, date="2026-01-01", base_price=100.0)
    _insert(
        "offer_items",
        offer_id=offer_id,
        product_id=product_id,
        item_name="stavka snapshot",
        quantity=1,
        unit_price=100.0,
        line_net=100.0,
    )
    _insert(
        "stock_movements",
        product_id=product_id,
        qty=1.0,
        direction="in",
        reason="purchase_in",
        moved_at="2026-01-01",
    )
    _insert(
        "reservations",
        product_id=product_id,
        qty=2.0,
        for_whom="test",
        created_at="2026-01-01",
    )
    _insert(
        "equipment_shortfalls",
        equipment_id=equipment_id,
        part_product_id=product_id,
        part_name="deo",
        taken_at="2026-01-01",
    )


def test_merge_products_repoints_references_and_keeps_the_source_row():
    source = _new_product("merge-source")
    target = _new_product("merge-target")
    # an alias that already resolved to the source must follow the merge,
    # otherwise it would point at a merged-away row (a chain)
    assert aliases.add_alias(f"{PREFIX} Merge Source Alias", source)[0] is True
    _seed_references(source)

    ok, summary = aliases.merge_products(source, target)
    assert ok is True, summary

    # (a) the source's own name became an alias of the target
    assert summary["alias"] == "zzt6 merge-source"
    assert summary["alias_id"] is not None
    assert _scalar(
        "SELECT product_id FROM product_aliases WHERE alias = ?;",
        ("zzt6 merge-source",),
    ) == target

    # (b) the pre-existing alias of the source now points at the target
    assert summary["aliases_repointed"] == 1
    assert _scalar(
        "SELECT product_id FROM product_aliases WHERE alias = ?;",
        ("zzt6 merge source alias",),
    ) == target

    # (c) every seeded reference column was reported and really moved
    assert set(summary["repointed"]) == {
        f"{table}.{column}" for table, column in aliases.PRODUCT_REFERENCE_COLUMNS
    }
    for label, count in summary["repointed"].items():
        assert count == 1, label
    for table, column in aliases.PRODUCT_REFERENCE_COLUMNS:
        assert _scalar(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = ?;", (source,)
        ) == 0, table
        assert _scalar(
            f"SELECT COUNT(*) FROM {table} WHERE {column} = ?;", (target,)
        ) == 1, table

    # (d) ARCHIVE-ONLY: source row still exists, name untouched, no price lost
    assert _scalar("SELECT id FROM products WHERE id = ?;", (source,)) == source
    assert _scalar("SELECT name FROM products WHERE id = ?;", (source,)) == f"{PREFIX} merge-source"
    assert _scalar(
        "SELECT COUNT(*) FROM prices WHERE product_id IN (?, ?);", (source, target)
    ) == 1

    # (e) the old name now resolves to the canonical product
    assert aliases.resolve_name(f"{PREFIX} merge-source") == target
    assert aliases.resolve_name("zzt6 Merge Source Alias") == target

    # (f) nothing was skipped silently
    assert "offer_items.item_name" in summary["skipped"]
    assert "products.site_product_id" in summary["skipped"]
    assert summary["message"]


def test_merge_products_rejects_invalid_inputs():
    pid = _new_product("merge-invalid")
    ok, message = aliases.merge_products(10 ** 9, pid)
    assert ok is False and "ne postoji" in message
    ok, message = aliases.merge_products(pid, 10 ** 9)
    assert ok is False and "ne postoji" in message
    ok, message = aliases.merge_products(pid, pid)
    assert ok is False and "isti" in message


def test_merge_products_refuses_to_create_alias_chains():
    a = _new_product("chain-a")
    b = _new_product("chain-b")
    c = _new_product("chain-c")
    assert aliases.merge_products(a, b)[0] is True

    # 'a' is merged away -- it may not be a merge TARGET ...
    ok, message = aliases.merge_products(c, a)
    assert ok is False and "spojen" in message
    # ... and may not be merged again as a SOURCE into a third product
    ok, message = aliases.merge_products(a, c)
    assert ok is False and "spojen" in message

    # merging the canonical row onwards is fine and keeps the map flat:
    # both old names resolve straight to the new canonical row.
    assert aliases.merge_products(b, c)[0] is True
    assert aliases.resolve_name(f"{PREFIX} chain-a") == c
    assert aliases.resolve_name(f"{PREFIX} chain-b") == c


# ---------------------------------------------------------------------------
# group_duplicate_suspects -- pure read model
# ---------------------------------------------------------------------------

def test_group_duplicate_suspects_groups_prefix_pairs_transitively_and_reads_only():
    short = _new_product("Dup Suspect")
    longer = _new_product("Dup Suspect Extended")
    third = _new_product("Dup Suspect Extended Pro")

    before = _scalar("SELECT COUNT(*) FROM products;")
    groups = aliases.group_duplicate_suspects()
    assert _scalar("SELECT COUNT(*) FROM products;") == before

    hits = [
        group for group in groups
        if {short, longer, third} <= {item["id"] for item in group["products"]}
    ]
    assert hits, "deliberately inserted prefix chain was not grouped"
    group = hits[0]
    assert group["kind"] == "prefix"
    assert group["key"] == "zzt6 dup suspect"
    assert group["size"] >= 3
    # the read model carries enough to render a merge tool later
    assert {"id", "name", "item_type", "tracking_regime"} <= set(group["products"][0])


def test_group_duplicate_suspects_flags_equal_normalized_names():
    # Two catalog rows can differ only by whitespace (the UNIQUE index is on
    # `name COLLATE NOCASE`, which compares the literal strings).
    _new_product("Equal  Pair")
    _new_product("Equal Pair")
    groups = aliases.group_duplicate_suspects()
    group = next(
        (g for g in groups if g["key"] == "zzt6 equal pair"), None)
    assert group is not None, "equal normalized names were not grouped"
    assert group["kind"] == "equal"
    assert group["size"] == 2


def test_group_duplicate_suspects_omits_unique_names_and_is_sorted():
    _new_product("Sasvim Jedinstveno Ime Bez Blizanca")
    groups = aliases.group_duplicate_suspects()
    flat_ids = {item["id"] for group in groups for item in group["products"]}
    lone = _scalar(
        "SELECT id FROM products WHERE name = ?;",
        (f"{PREFIX} Sasvim Jedinstveno Ime Bez Blizanca",),
    )
    assert lone not in flat_ids
    assert [group["key"] for group in groups] == sorted(group["key"] for group in groups)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

def test_product_aliases_table_shape_and_index():
    conn = get_db()
    try:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(product_aliases);").fetchall()
        }
        assert columns == {"id", "alias", "product_id", "created_at"}
        assert conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
            "AND tbl_name='product_aliases' AND name='idx_product_aliases_product';"
        ).fetchone()[0] == 1
    finally:
        conn.close()
