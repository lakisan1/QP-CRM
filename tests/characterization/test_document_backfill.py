"""Legacy-document backfill (musterija-first era, user request 2026-09-22).

Existing offers and rent contracts were issued before the shared directory
became the single musterija registry, so most rows have contact_id NULL
and the imenik's document history is empty. link_documents_to_contacts()
links them (idempotent, boot-time via migrate_contacts):

* PIB/MB match wins -- but only when the document's name agrees with the
  matched contact (a PIB belonging to a differently-named party is a data
  conflict and stays unlinked);
* exact normalized name match covers rows with no tax id (ΣΥΝΕΡΓΕΙΟ-type);
* PIB/MB-vs-name conflicts (HIDRAULIK FLEX with two different PIBs) are
  deliberately left unlinked for manual review;
* snapshot fields are never rewritten -- only the id link is set;
* reruns do nothing new (only contact_id IS NULL rows are considered).
"""

import pytest

from qp_crm.services import contact_service
from qp_crm.shared.db import get_db
from qp_crm.shared.schema import migrate_contacts


@pytest.fixture(scope="module", autouse=True)
def _db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _clean():
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("DELETE FROM offers;")
    conn.execute("DELETE FROM rent_contracts;")
    conn.execute("DELETE FROM contact_locations;")
    conn.execute("DELETE FROM contact_roles;")
    conn.execute("DELETE FROM contacts;")
    conn.commit()
    yield
    conn.close()


def _offer(name, pib=None, mb=None, number="BF-1"):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO offers (offer_number, date, client_name, client_pib, client_mb,
                               country, currency, exchange_rate)
           VALUES (?, '2026-09-22', ?, ?, ?, 'Srbija', 'EUR', 0);""",
        (number, name, pib, mb),
    )
    oid = cur.lastrowid
    conn.commit()
    conn.close()
    return oid


def _rent(name, pib=None, mb=None, number="BF-UG-1"):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO rent_contracts (contract_number, contract_date, client_name,
                                       client_pib, client_mb)
           VALUES (?, '2026-09-22', ?, ?, ?);""",
        (number, name, pib, mb),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    return cid


def _offer_link(oid):
    conn = get_db()
    row = conn.execute("SELECT contact_id FROM offers WHERE id = ?;", (oid,)).fetchone()
    conn.close()
    return row["contact_id"]


def _rent_link(cid):
    conn = get_db()
    row = conn.execute("SELECT contact_id FROM rent_contracts WHERE id = ?;", (cid,)).fetchone()
    conn.close()
    return row["contact_id"]


def _run_backfill():
    conn = get_db()
    cur = conn.cursor()
    linked = contact_service.link_documents_to_contacts(cur)
    conn.commit()
    conn.close()
    return linked


def test_links_by_pib_when_name_agrees():
    ok, cid = contact_service.create_contact(
        "Delta Automoto d.o.o.", kind="company", roles=["client"],
        fields={"pib": "104764599", "mb": "20236507"})
    oid = _offer("Delta Automoto d.o.o.", pib="104764599", mb="20236507")
    assert _run_backfill() >= 1
    assert _offer_link(oid) == cid


def test_links_by_exact_name_when_no_tax_id():
    ok, cid = contact_service.create_contact(
        "ΣΥΝΕΡΓΕΙΟ ΑΥΤΟΚΙΝΗΤΩΝ", kind="company", roles=["client"],
        fields={"pib": None})
    oid = _offer("ΣΥΝΕΡΓΕΙΟ ΑΥΤΟΚΙΝΗΤΩΝ")  # no PIB captured
    _run_backfill()
    assert _offer_link(oid) == cid


def test_name_match_is_whitespace_and_case_insensitive():
    ok, cid = contact_service.create_contact(
        "Delta Automoto d.o.o.", kind="company", roles=["client"], fields={})
    oid = _offer("  delta   automoto D.O.O.  ")
    _run_backfill()
    assert _offer_link(oid) == cid


def test_skips_pib_unknown_and_pib_name_conflict():
    """The ambiguous entity: same name, different PIB -> no link."""
    ok, cid = contact_service.create_contact(
        "HIDRAULIK FLEX ZANATSKO TRGOVINSKA RADNJA IVAN JAKOVLJEVIC PR",
        kind="company", roles=["client"], fields={"pib": "489498856"})
    known = _offer("HIDRAULIK FLEX ZANATSKO TRGOVINSKA RADNJA IVAN JAKOVLJEVIC PR",
                   pib="489498856")           # agrees -> link
    conflict = _offer("HIDRAULIK FLEX ZANATSKO TRGOVINSKA RADNJA IVAN JAKOVLJEVIC PR",
                      pib="108028497")        # disagrees -> skip
    unknown = _offer("Nepoznata Firma d.o.o.", pib="999999999")  # unknown PIB -> skip
    _run_backfill()
    assert _offer_link(known) == cid
    assert _offer_link(conflict) is None
    assert _offer_link(unknown) is None


def test_links_rent_contracts_too():
    ok, cid = contact_service.create_contact(
        "GRADINGCOMMERCE DOO BEOGRAD", kind="company", roles=["client"],
        fields={"pib": "104033337"})
    rid = _rent("GRADINGCOMMERCE DOO BEOGRAD", pib="104033337")
    _run_backfill()
    assert _rent_link(rid) == cid


def test_never_touches_snapshot_fields():
    ok, cid = contact_service.create_contact(
        "Snimak Firma d.o.o.", kind="company", roles=["client"],
        fields={"pib": "100001111", "billing_address": "Imenik adresa 1"})
    oid = _offer("Snimak Firma d.o.o.", pib="100001111")
    conn = get_db()
    conn.execute("UPDATE offers SET client_address = 'Dokument adresa 2' WHERE id = ?;", (oid,))
    conn.commit()
    conn.close()
    _run_backfill()
    conn = get_db()
    row = conn.execute("SELECT contact_id, client_address, client_pib FROM offers WHERE id = ?;", (oid,)).fetchone()
    conn.close()
    assert row["contact_id"] == cid
    assert row["client_address"] == "Dokument adresa 2"  # snapshot untouched
    assert row["client_pib"] == "100001111"


def test_idempotent_rerun():
    ok, cid = contact_service.create_contact(
        "Idem Potent d.o.o.", kind="company", roles=["client"],
        fields={"pib": "100002222"})
    oid = _offer("Idem Potent d.o.o.", pib="100002222")
    first = _run_backfill()
    second = _run_backfill()
    assert first >= 1 and second == 0
    assert _offer_link(oid) == cid


def test_boot_migration_runs_backfill():
    """The boot sequence (migrate_contacts) picks unlinked rows up."""
    ok, cid = contact_service.create_contact(
        "Boot Hook d.o.o.", kind="company", roles=["client"],
        fields={"pib": "100003333"})
    oid = _offer("Boot Hook d.o.o.", pib="100003333")
    conn = get_db()
    cur = conn.cursor()
    migrate_contacts(cur)
    conn.commit()
    conn.close()
    assert _offer_link(oid) == cid
