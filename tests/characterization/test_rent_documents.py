"""Rent document templates — fixes from the 2026-09-24 document review (R-D1/R-D2).

Pinned here:

* no rent template carries a hard-coded contract number ("001/2023" was in
  Prilog 2 before the fix) — every reference is the {{ contract_number }}
  placeholder, so a printed protocol always points at the contract it belongs to;
* all templates name the agreement "Ugovor o zakupu opreme" (the annexes used
  to say "Ugovor o dugoročnom zakupu");
* the menica authorisation asks for five (5) blanko solo menica — the contract
  clause 10.1 requires five and the handover record lists five serial numbers;
  the authorisation used to say "jednu";
* the advance payment instruction carries NO hard-coded RSD amount (the exact
  dinars are only known on the payment date, at the NBS middle rate);
* Prilog 2 has unique list letters per clause and the lessee (not the lessor)
  owes the damage compensation;
* the new 'izjava-vrednost-opreme' template states the guaranteed end-of-rent
  value and renders the contract's residual (net / VAT / gross) — this is the
  document that records the value the contract itself deliberately omits.
"""

import re
import sys

import pytest

sys.path.insert(0, "tests")

from conftest import csrf_token_for, login_client  # noqa: E402
from qp_crm.main import app  # noqa: E402
from qp_crm.shared.db import get_db  # noqa: E402
from qp_crm.shared.utils import format_amount  # noqa: E402
from qp_crm.shared.web import RENT_TEMPLATE_SORT_ORDER  # noqa: E402

NEW_SLUG = "izjava-vrednost-opreme"


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


@pytest.fixture(autouse=True)
def _clean():
    conn = get_db()
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("DELETE FROM rent_contract_documents;")
    conn.execute("DELETE FROM rent_contracts;")
    conn.commit()
    yield
    conn.close()


def _templates():
    conn = get_db()
    rows = conn.execute("SELECT slug, name, content_html FROM rent_templates;").fetchall()
    conn.close()
    return {r["slug"]: r["content_html"] for r in rows}


def _client():
    return login_client(app.test_client(), "rent")


def test_no_hard_coded_contract_number_in_any_template():
    for slug, html in _templates().items():
        assert "001/2023" not in html, f"{slug} still hard-codes contract 001/2023"


def test_all_templates_use_the_same_agreement_name():
    for slug, html in _templates().items():
        assert "dugoročnom zakupu" not in html, \
            f"{slug} still says 'Ugovor o dugoročnom zakupu'"


def test_protocol_references_the_contract_number_placeholder():
    html = _templates()["prilog-2-protokol"]
    assert "br. {{ contract_number }}" in html
    assert "utvrđuje" in html and "utvruđuje" not in html


def test_protocol_list_letters_are_unique_and_lessee_pays_damages():
    html = _templates()["prilog-2-protokol"]
    # clause 2 and clause 3 each list letters without duplicates
    clauses = re.findall(r"Član \d+\.(.*?)(?=Član \d+\.|$)", html, re.S)
    checked = 0
    for block in clauses:
        letters = re.findall(r"<p>([a-j])\.\s", block)
        if len(letters) >= 2:
            assert len(letters) == len(set(letters)), f"duplicate letters: {letters}"
            checked += 1
    assert checked >= 2
    # the lessee compensates the lessor (roles used to be swapped)
    assert "Zakupac je dužan da nadoknadi celokupnu vrednost štete koju je pretrpeo Zakupodavac" in html


def test_menica_authorisation_asks_for_five_menica():
    conn = get_db()
    row = conn.execute("SELECT name, content_html FROM rent_templates "
                       "WHERE slug='menicno-ovlascenje';").fetchone()
    conn.close()
    # Serbian: the adjective from 'menica' is 'menično' ('menično pravo');
    # 'Meničko' is a misspelling and used to be the template name.
    assert row["name"] == "Menično ovlašćenje"
    html = row["content_html"]
    assert "pet (5) blanko solo menica" in html
    assert "jednu blanko solo menicu" not in html
    # five menica must not read as five times the debt: the authorisation caps
    # the total collected across all of them at the actual outstanding debt.
    # The sentence is deliberately NOT bolded (user request).
    assert "ne može preći iznos stvarnog duga po Ugovoru" in html
    assert "<strong>Ukupan iznos naplaćen" not in html
    assert "<p>Ukupan iznos naplaćen" in html


def test_advance_instruction_has_no_hard_coded_amount():
    html = _templates()["instrukcija-avans"]
    assert "100.100" not in html and "824.817" not in html
    assert "Iznos: ______________" in html
    # the EUR amount is still shown (that one is exact at signature time)
    assert "{{ ucesce_bruto_fmt }}" in html


def test_contract_clause_23_links_the_advance_closing():
    for slug in ("ugovor-zakup", "ugovor-zakup-jemac"):
        html = _templates()[slug]
        assert "zatvaranja avansa iz člana 13.2" in html, slug


def test_new_value_statement_template_exists_and_is_ordered():
    tpl = _templates()
    assert NEW_SLUG in tpl
    assert NEW_SLUG in RENT_TEMPLATE_SORT_ORDER
    html = tpl[NEW_SLUG]
    assert "IZJAVA O VREDNOSTI OPREME" in html
    for ph in ("{{ ostatak_fmt }}", "{{ ostatak_pdv_fmt }}",
               "{{ ostatak_bruto_fmt }}", "{{ period_years }}", "{{ vat_percent }}",
               "{{ period_months }}", "{{ equipment_model }}"):
        assert ph in html, ph
    # the term is stated in months only (the parenthetical year count was
    # redundant — the years already appear in the table heading)
    assert "meseci redovnog" in html
    assert "meseci ({{ period_years }}" not in html
    # the tax-safety note must stay
    assert "ne može biti isto pravno lice" in html
    # ordered LAST: it is the end-of-rent document, not a signing-time annex
    assert RENT_TEMPLATE_SORT_ORDER[-1] == NEW_SLUG


def test_documents_page_lists_the_value_statement_last():
    """The rendered documents table ends with the value statement at #11."""
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, contract_date, client_name, "
        "price, period_months) VALUES ('DOK-1', '2026-09-24', 'Dok Firma', 5000, 48);")
    conn.commit()
    cid = conn.execute(
        "SELECT id FROM rent_contracts WHERE contract_number='DOK-1';").fetchone()["id"]
    conn.close()

    page = client.get(f"/rent/contracts/{cid}/documents").data.decode()
    body = page[page.find("<tbody>"):page.find("</tbody>")]
    names = [" ".join(re.sub(r"<[^>]+>", " ", td).split())
             for td in re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)]
    # template rows carry their display number in the first cell; the trailing
    # "Evidencija Uplata" row uses 📝 and is not part of the numbered run
    order = [(names[i], names[i + 1]) for i in range(0, len(names) - 3, 4)]
    numbered = [(n, nm) for n, nm in order if n.isdigit()]
    assert numbered[-1] == ("11", "Izjava o vrednosti opreme"), numbered
    # the whole numbering is a clean 1..11 run (it used to show two 3s and no 5)
    assert [n for n, _ in numbered] == [str(i) for i in range(1, 12)], numbered


def test_value_statement_renders_the_contract_residual():
    """For a 4.200 EUR / 48-month contract the residual is 20% = 840 net."""
    client = _client()
    conn = get_db()
    conn.execute(
        "INSERT INTO rent_contracts (contract_number, contract_date, client_name, "
        "price, period_months, salvage_value_percent, vat_percent, "
        "downpayment_percent, interest_rate, insurance_rate, guarantee_rate, "
        "admin_fee, equipment_model) "
        "VALUES ('IZ-1', '2026-09-24', 'Izjava Firma', 4200, 48, 20, 20, "
        "20, 14, 1.13, 5, 50, 'Test Masina');")
    conn.commit()
    cid = conn.execute(
        "SELECT id FROM rent_contracts WHERE contract_number='IZ-1';").fetchone()["id"]
    conn.close()

    resp = client.get(f"/rent/contracts/{cid}/documents/{NEW_SLUG}")
    assert resp.status_code == 200
    html = resp.data.decode()
    assert format_amount(840.0) in html      # neto = 20% od 4.200
    assert format_amount(168.0) in html      # PDV 20%
    assert format_amount(1008.0) in html     # bruto
    assert "Test Masina" in html
    assert "{{" not in html, "unsubstituted placeholder left in the document"
