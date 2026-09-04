"""NOT a test (underscore name -- pytest never collects it).

PDF determinism probe used while building the golden tests (P1-T6):
renders the fixed offer + fixed rent document TWICE through the
production routes inside one container, diffs the raw bytes, applies the
candidate normalizer, and reports whether the normalized bytes are
stable. Run:

    docker compose run --rm app python tests/_probe_pdf.py
"""

import os
import re
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TEST_ROOT = "/tmp/qp-crm-probe"  # fixed like tests/conftest.py (deterministic URLs)
import shutil
if os.path.exists(TEST_ROOT):
    shutil.rmtree(TEST_ROOT)
TEST_APP_DATA = os.path.join(TEST_ROOT, "app_data")
TEST_ASSETS = os.path.join(TEST_ROOT, "app_assets")
os.makedirs(TEST_APP_DATA, exist_ok=True)
os.makedirs(os.path.join(TEST_APP_DATA, "product_images"), exist_ok=True)
os.makedirs(TEST_ASSETS, exist_ok=True)

import shared.config as _config

_config.APP_DATA_DIR = TEST_APP_DATA
_config.DATABASE = os.path.join(TEST_APP_DATA, "pricing.db")
_config.IMAGE_DIR = os.path.join(TEST_APP_DATA, "product_images")
_config.APP_ASSETS_DIR = TEST_ASSETS

# deterministic fixture assets straight from tests/golden/assets
import shutil

for name in os.listdir(os.path.join(PROJECT_ROOT, "tests", "golden", "assets")):
    shutil.copy2(os.path.join(PROJECT_ROOT, "tests", "golden", "assets", name),
                 os.path.join(TEST_ASSETS, name))

from pricing.app import init_db as pricing_init_db, migrate_schema as pricing_migrate_schema
from offer.app import init_db as offer_init_db
from admin.app import init_db as admin_init_db
from rent.app import init_db as rent_init_db

pricing_init_db()
pricing_migrate_schema()
offer_init_db()
admin_init_db()
rent_init_db()

from shared.db import get_db
from offer.app import recalc_totals

conn = get_db()
cur = conn.cursor()
cur.execute(
    """INSERT INTO offers (offer_number, date, client_name, client_address, client_email,
        client_phone, country, currency, exchange_rate,
        discount_percent, special_discount_percent, third_discount_percent, vat_percent,
        payment_terms, delivery_terms, validity_days, notes)
     VALUES ('GOLD-2026-001', '2026-03-15', 'Golden Customer d.o.o.',
             'Zlatna ulica 15, 11000 Beograd', 'gold@example.rs', '+381 11 000 0000',
             'Srbija', 'RSD', 1.0, 0.10, 0.05, 0.0, 0.20,
             'Avans 50%', '5 dana', 30, 'Golden note')"""
)
oid = cur.lastrowid
for order, (name, desc, qty, price) in enumerate(
    [
        ("CNC centar 500", "Osnovna masina\nDodatna oprema ukljucena", 1.0, 21000.0),
        ("Doslizni stalak", "Hidraulicni doslizni stalak", 2.0, 4750.0),
    ], start=1):
    line_net = qty * price * (1 - 0.05)
    cur.execute(
        """INSERT INTO offer_items (offer_id, item_name, item_description, quantity,
            unit_price, discount_percent, line_net, line_order)
         VALUES (?, ?, ?, ?, ?, 0.05, ?, ?)""",
        (oid, name, desc, qty, price, line_net, order),
    )
conn.commit()
conn.close()
recalc_totals(oid)

conn = get_db()
cur = conn.cursor()
cur.execute(
    """INSERT INTO rent_contracts (contract_number, contract_date, client_name, client_mb,
        client_pib, client_account, client_address, client_representative, client_email,
        rent_address, guarantor, delivery_time, delivery_date, equipment_model, price,
        vat_percent, period_months, downpayment_percent, salvage_value_percent,
        interest_rate, insurance_rate, guarantee_rate, admin_fee)
     VALUES ('UGOVOR-2026-TEST', '2026-01-15', 'Golden Customer d.o.o.', '11111111',
             '101010101', '160-000000-01', 'Zlatna ulica 15, 11000 Beograd',
             'Marko Markovic', 'gold@example.rs', 'Radionica 2, Novi Sad', '',
             '10 dana', '2026-01-25', 'CNC centar 500', 20000.0,
             20.0, 48, 20.0, 20.0, 14.0, 1.13, 5.0, 50.0)"""
)
cid = cur.lastrowid
conn.commit()
conn.close()

import main  # Phase 2: one app; offer/rent are blueprints under prefixes

oc = main.app.test_client()
with oc.session_transaction() as s:
    s["offer_authenticated"] = True

rc = main.app.test_client()
with rc.session_transaction() as s:
    s["rent_authenticated"] = True


def diff_offsets(a, b, limit=5):
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y][:limit] if len(a) == len(b) else f"LEN {len(a)} vs {len(b)}"


NORMS = [
    (re.compile(rb"/CreationDate (D:d{14}(?:[+-]d{2}'d{2}')?)"), b"/CreationDate (D:FIXED)"),
    (re.compile(rb"/ModDate (D:d{14}(?:[+-]d{2}'d{2}')?)"), b"/ModDate (D:FIXED)"),
    (re.compile(rb"d{4}-d{2}-d{2}Td{2}:d{2}:d{2}(?:.d+)?Z?"), b"ISO-FIXED"),
    (re.compile(rb"(/ID\s*\[)\s*<[0-9a-fA-F]+>\s*<[0-9a-fA-F]+>\s*(\])"), rb"\1<0><0>\2"),
]


def normalize(data):
    for rx, repl in NORMS:
        data = rx.sub(repl, data)
    return data


for label, client, url in (("OFFER", oc, f"/offer/offers/{oid}/pdf"),
                           ("RENT", rc, f"/rent/contracts/{cid}/documents/ugovor-zakup/pdf")):
    r1 = client.get(url)
    r2 = client.get(url)
    b1, b2 = r1.data, r2.data
    print(f"--- {label} {url} ---")
    print(f"status={r1.status_code} len1={len(b1)} len2={len(b2)} raw_diff={diff_offsets(b1, b2)}")
    n1, n2 = normalize(b1), normalize(b2)
    print(f"normalized equal: {n1 == n2}  normalized_diff={diff_offsets(n1, n2)}")
    for marker in (b"/CreationDate", b"/ModDate", b"/ID [", b"xmpmeta", b"xmp:CreateDate"):
        idx = b1.find(marker)
        print(f"  {marker!r} at {idx}: ...{b1[max(0, idx - 10):idx + 70]!r}")
