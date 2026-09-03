"""P1-T6 golden-PDF tests: render fixed documents, compare against baselines.

Both documents are rendered through the PRODUCTION routes (offer_pdf,
document_pdf) with a Flask test client against the throwaway fixture DB,
using fixed fixture rows and the fixed fixture assets from
tests/golden/assets/ (small stand-in logo + footer image -- golden bytes
must not depend on whatever logo sits in the host app_assets/).

Fonts are pinned in the Docker image (fonts-dejavu-core) and WeasyPrint
69.0 writes no timestamps/document IDs into these PDFs, so renders are
byte-identical across runs (verified by tests/_probe_pdf.py). The
normalizer below still blanks the classic volatile regions (PDF dates,
XMP timestamps, trailer /ID) on BOTH sides of the comparison so a future
WeasyPrint upgrade that starts writing metadata does not force a
pointless re-baseline -- everything else must stay byte-identical.

Re-baselining is deliberate: run

    docker compose run -v "$PWD/tests:/app/tests" --rm -e QP_UPDATE_GOLDEN=1 \
        app pytest tests/golden

then git-diff tests/golden/baselines/ and explain the intended change in
the commit message (see tests/README.md).
"""

import os
import re

import pytest

from offer.app import recalc_totals

BASELINES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baselines")
UPDATE_GOLDEN = os.environ.get("QP_UPDATE_GOLDEN") == "1"

# (regex, replacement) for the only regions that are allowed to differ
NORMALIZERS = [
    (re.compile(rb"/CreationDate \(D:\d{14}(?:[+-]\d{2}'\d{2})?\)"), b"/CreationDate (D:NORMALIZED)"),
    (re.compile(rb"/ModDate \(D:\d{14}(?:[+-]\d{2}'\d{2})?\)"), b"/ModDate (D:NORMALIZED)"),
    (re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?"), b"ISO-TIMESTAMP-NORMALIZED"),
    (re.compile(rb"(/ID\s*\[)\s*<[0-9a-fA-F]+>\s*<[0-9a-fA-F]+>\s*(\])"), rb"\1<0><0>\2"),
]


def _normalize(data: bytes) -> bytes:
    for regex, replacement in NORMALIZERS:
        data = regex.sub(replacement, data)
    return data


def _first_diff(a: bytes, b: bytes):
    for offset, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return offset
    return min(len(a), len(b))


def _assert_golden(name: str, pdf_bytes: bytes):
    """Compare rendered bytes against the checked-in baseline.

    QP_UPDATE_GOLDEN=1 rewrites the baseline instead of comparing (and
    skips) -- only usable with tests/ bind-mounted into the container.
    """
    assert pdf_bytes.startswith(b"%PDF"), f"{name}: response is not a PDF"
    baseline_path = os.path.join(BASELINES_DIR, name)
    normalized = _normalize(pdf_bytes)
    if UPDATE_GOLDEN or not os.path.exists(baseline_path):
        if UPDATE_GOLDEN:
            with open(baseline_path, "wb") as handle:
                handle.write(normalized)
            pytest.skip(f"baseline rewritten: {name}")
        pytest.fail(
            f"baseline {name} missing -- create it deliberately with "
            'QP_UPDATE_GOLDEN=1 (command in tests/README.md)'
        )
    with open(baseline_path, "rb") as handle:
        baseline = handle.read()
    assert normalized == baseline, (
        f"{name}: rendered PDF differs from baseline "
        f"({len(pdf_bytes)} vs {len(baseline)} bytes, first diff at byte "
        f"{_first_diff(normalized, baseline)}). If this change is intended, "
        "re-baseline with QP_UPDATE_GOLDEN=1 and say why in the commit."
    )


@pytest.fixture(scope="module")
def offer_id(temp_db, conn_factory):
    """Fixed offer: 3-level discounts 10%/5%/0%, VAT 20%, two items."""
    with conn_factory() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO offers (id, offer_number, date, client_name, client_address,
                client_email, client_phone, country, currency, exchange_rate,
                discount_percent, special_discount_percent, third_discount_percent,
                vat_percent, payment_terms, delivery_terms, validity_days, notes)
             VALUES (900001, 'GOLD-2026-001', '2026-03-15', 'Golden Customer d.o.o.',
                     'Zlatna ulica 15, 11000 Beograd', 'gold@example.rs',
                     '+381 11 000 0000', 'Srbija', 'RSD', 1.0,
                     0.10, 0.05, 0.0, 0.20,
                     'Avans 50%', '5 dana', 30, 'Golden note')"""
        )
        oid = cur.lastrowid
        # Explicit ids: the PDF carries id-derived anchors/destinations, so
        # autoincrement ids shifted by other tests would change the bytes.
        item_ids = {1: 900001, 2: 900002}
        for order, (name, desc, qty, price) in enumerate(
            [
                ("CNC centar 500", "Osnovna masina\nDodatna oprema ukljucena", 1.0, 21000.0),
                ("Doslizni stalak", "Hidraulicni doslizni stalak", 2.0, 4750.0),
            ],
            start=1,
        ):
            line_net = qty * price * (1 - 0.05)
            cur.execute(
                """INSERT INTO offer_items (id, offer_id, item_name, item_description,
                    quantity, unit_price, discount_percent, line_net, line_order)
                 VALUES (?, ?, ?, ?, ?, ?, 0.05, ?, ?)""",
                (item_ids[order], oid, name, desc, qty, price, line_net, order),
            )
    recalc_totals(oid)
    return oid


@pytest.fixture(scope="module")
def contract_id(temp_db, conn_factory):
    """Fixed rent contract matching the characterization CALC_ARGS."""
    with conn_factory() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO rent_contracts (id, contract_number, contract_date, client_name,
                client_mb, client_pib, client_account, client_address,
                client_representative, client_email, rent_address, guarantor,
                delivery_time, delivery_date, equipment_model, price, vat_percent,
                period_months, downpayment_percent, salvage_value_percent,
                interest_rate, insurance_rate, guarantee_rate, admin_fee)
             VALUES (900001, 'UGOVOR-2026-TEST', '2026-01-15', 'Golden Customer d.o.o.',
                     '11111111', '101010101', '160-000000-01',
                     'Zlatna ulica 15, 11000 Beograd', 'Marko Markovic',
                     'gold@example.rs', 'Radionica 2, Novi Sad', '',
                     '10 dana', '2026-01-25', 'CNC centar 500', 20000.0,
                     20.0, 48, 20.0, 20.0, 14.0, 1.13, 5.0, 50.0)"""
        )
        cid = cur.lastrowid
    return cid


def test_offer_pdf_matches_golden_baseline(temp_db, conn_factory, offer_client, assets_dir, offer_id):
    """Filesystem-template path (fresh fixture DB has no active_pdf_template_id)."""
    response = offer_client.get(f"/offers/{offer_id}/pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    _assert_golden("offer_golden.pdf", response.data)


def test_rent_document_pdf_matches_golden_baseline(temp_db, rent_client, assets_dir, contract_id):
    """ugovor-zakup is seeded from rent/rent_templates_defaults.json and filled
    through the {{ key }}/{{key}} + html.escape substitution loop."""
    response = rent_client.get(f"/contracts/{contract_id}/documents/ugovor-zakup/pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    _assert_golden("rent_ugovor_zakup_golden.pdf", response.data)
