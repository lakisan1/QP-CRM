"""P1-T5b characterization: rent document placeholder machinery AS IS.

Covers rent/app.py _build_doc_context (the flat dict every document
template is filled from) and format_document_html (official-heading
post-processing). The literal {{ key }} / {{key}} double-replace +
html.escape loop lives inline in the document_pdf route
(rent/app.py:1178-1192) and is pinned end-to-end by the golden PDF test
(tests/golden), including its html-escape behavior.

Captured from the unmodified app via tests/_capture.py. Pinned quirks:

* every missing/None contract field becomes "" (empty string), so
  templates never render "None" -- and missing data is invisible.
* fmt_date inside the context converts YYYY-MM-DD to DD.MM.YYYY and
  passes anything unparsable through UNCHANGED.
* format_document_html converts only lowercase "Član N" paragraphs
  (uppercase "ČLAN 1." is NOT matched) and only the fixed section-header
  whitelist; everything else passes through untouched.
"""

from qp_crm.rent.app import _build_doc_context, calculate_rent, format_document_html

CALC_ARGS = (20000.0, 48, 20.0, 20.0, 14.0, 1.13, 5.0, 20.0, 50.0)

CONTRACT = {
    "contract_number": "UGOVOR-2026-007",
    "contract_date": "2026-01-15",
    "period_months": 48,
    "delivery_time": "10 dana",
    "delivery_date": "2026-01-25",
    "client_name": "Kupac d.o.o.",
    "client_mb": "11111111",
    "client_pib": "101010101",
    "client_account": "160-000000-01",
    "client_address": "Ulica 1, Beograd",
    "client_representative": "Marko Markovic",
    "client_email": None,
    "rent_address": "Radionica 2, Novi Sad",
    "guarantor": None,
    "equipment_model": "Model X-100",
    "price": 20000.0,
}


def _ctx():
    return _build_doc_context(CONTRACT, calculate_rent(*CALC_ARGS))


class TestBuildContext:
    def test_contract_fields_map_through(self):
        ctx = _ctx()
        assert ctx["contract_number"] == "UGOVOR-2026-007"
        assert ctx["contract_date"] == "15.01.2026"        # DD.MM.YYYY
        assert ctx["period_months"] == "48"                # stringified
        assert ctx["delivery_time"] == "10 dana"
        assert ctx["delivery_date"] == "25.01.2026"
        assert ctx["client_name"] == "Kupac d.o.o."
        assert ctx["client_mb"] == "11111111"
        assert ctx["client_pib"] == "101010101"
        assert ctx["client_account"] == "160-000000-01"
        assert ctx["client_address"] == "Ulica 1, Beograd"
        assert ctx["client_representative"] == "Marko Markovic"
        assert ctx["rent_address"] == "Radionica 2, Novi Sad"
        assert ctx["equipment_model"] == "Model X-100"

    def test_none_fields_become_empty_strings(self):
        ctx = _ctx()
        assert ctx["client_email"] == ""
        assert ctx["guarantor"] == ""

    def test_fmt_date_passthrough_for_unparsable(self):
        contract = dict(CONTRACT, contract_date="not-a-date")
        ctx = _build_doc_context(contract, calculate_rent(*CALC_ARGS))
        assert ctx["contract_date"] == "not-a-date"

    def test_money_values_are_european_formatted(self):
        ctx = _ctx()
        assert ctx["price_fmt"] == "20.000,00"
        assert ctx["rata_neto_fmt"] == "414,25"       # rounded to 2 decimals
        assert ctx["rata_bruto_fmt"] == "497,10"
        assert ctx["ucesce_bruto_fmt"] == "4.800,00"
        assert ctx["ucesce_pdv_fmt"] == "800,00"
        assert ctx["zatvaranje_fmt"] == "100,00"
        assert ctx["ostatak_fmt"] == "4.000,00"
        assert ctx["osiguranje_fmt"] == "18,83"
        assert ctx["garancija_fmt"] == "20,83"


class TestFormatDocumentHtml:
    def test_clan_paragraph_becomes_h3_with_dot(self):
        html = "<p><strong>Član 2</strong></p>"
        assert format_document_html(html) == '<h3 class="clan-header">Član 2.</h3>'

    def test_clan_with_trailing_dot_and_whitespace(self):
        html = "<p> <strong> Član 12 . </strong> </p>"
        assert format_document_html(html) == '<h3 class="clan-header">Član 12.</h3>'

    def test_uppercase_clan_is_not_matched(self):
        # regex is case-sensitive: "ČLAN" passes through untouched
        html = "<p><strong>ČLAN 1.</strong></p>"
        assert format_document_html(html) == html

    def test_section_header_whitelist(self):
        html = "<p><strong>Plaćanje zakupnine</strong></p>"
        assert format_document_html(html) == '<h4 class="section-header">Plaćanje zakupnine</h4>'

    def test_unknown_header_untouched(self):
        html = "<p><strong>Nepoznato poglavlje</strong></p>"
        assert format_document_html(html) == html

    def test_empty_and_none(self):
        assert format_document_html("") == ""
        assert format_document_html(None) == ""
