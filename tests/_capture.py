"""NOT a test (underscore name -- pytest never collects it).

Development helper used during Phase 1 (P1-T2..T5) to capture the exact
characterization literals from a container run of the UNMODIFIED app:

    docker compose run --rm app python tests/_capture.py

The printed values are hand-checked against the code paths and then
hardcoded into the characterization tests. Kept in the repo so a future
re-capture is one command.

Standalone script: duplicates the conftest isolation patch (patch
shared.config BEFORE importing any app module), then replays the production
init sequence into the throwaway DB.
"""

import os
import sys
import tempfile
from datetime import date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

TEST_ROOT = "/tmp/qp-crm-capture"  # fixed like tests/conftest.py (deterministic URLs)
import shutil
if os.path.exists(TEST_ROOT):
    shutil.rmtree(TEST_ROOT)
TEST_APP_DATA_DIR = os.path.join(TEST_ROOT, "app_data")
TEST_DATABASE = os.path.join(TEST_APP_DATA_DIR, "pricing.db")
for _d in (TEST_APP_DATA_DIR, os.path.join(TEST_APP_DATA_DIR, "product_images"),
           os.path.join(TEST_ROOT, "app_assets")):
    os.makedirs(_d, exist_ok=True)

import qp_crm.shared.config as _config

_config.APP_DATA_DIR = TEST_APP_DATA_DIR
_config.DATABASE = TEST_DATABASE
_config.IMAGE_DIR = os.path.join(TEST_APP_DATA_DIR, "product_images")
_config.APP_ASSETS_DIR = os.path.join(TEST_ROOT, "app_assets")

from qp_crm.pricing.app import init_db as pricing_init_db, migrate_schema as pricing_migrate_schema
from qp_crm.offer.app import init_db as offer_init_db
from qp_crm.admin.app import init_db as admin_init_db
from qp_crm.rent.app import init_db as rent_init_db

pricing_init_db()
pricing_migrate_schema()
offer_init_db()
admin_init_db()
rent_init_db()

from qp_crm.pricing.app import apply_rounding
from qp_crm.shared.db import get_db


def section(title):
    print(f"\n===== {title} =====")


# ------------------------------------------------------------------ rounding
section("A. apply_rounding against SEEDED default rules (target price/discount)")
for target in ("price", "discount"):
    for val in (0, -5, 0.01, 12.5, 499.99, 500, 999.99, 1000, 1000.01,
                9999.99, 10000, 10000.01, 29999.99, 30000, 30000.01,
                12345.67, 999999999, 1e9):
        print(f"apply_rounding({val!r}, {target!r}) = {apply_rounding(val, target)!r}")

section("A2. custom-rule targets")
conn = get_db()
cur = conn.cursor()
cur.executemany(
    "INSERT INTO price_rounding_rules (target, limit_val, step_val, method) VALUES (?, ?, ?, ?);",
    [
        ("up_test", 999999999, 7, "UP"),
        ("down_test", 999999999, 7, "DOWN"),
        ("nearest_test", 999999999, 1, "NEAREST"),
        ("weird_test", 999999999, 7, "WEIRD"),
    ],
)
conn.commit()
conn.close()
for target, val in (("up_test", 100), ("down_test", 100), ("weird_test", 100),
                    ("nearest_test", 2.5), ("nearest_test", 3.5),
                    ("nearest_test", 0.5), ("nearest_test", 1.5),
                    ("nearest_test", 2.675), ("no_such_target", 100.55)):
    print(f"apply_rounding({val!r}, {target!r}) = {apply_rounding(val, target)!r}")

# ------------------------------------------------------------- recalc_totals
section("B. recalc_totals: 3-level cascade (fractions 0.10/0.05/0.025, vat 0.20)")
conn = get_db()
cur = conn.cursor()
cur.execute(
    """INSERT INTO offers (offer_number, date, client_name, currency, exchange_rate,
        discount_percent, special_discount_percent, third_discount_percent, vat_percent)
     VALUES ('CAP-2026-001', '2026-03-15', 'Capture d.o.o.', 'RSD', 1.0, 0.10, 0.05, 0.025, 0.20);"""
)
offer_id = cur.lastrowid
for line_net in (10000.0, 19000.0, 500.0):
    cur.execute(
        """INSERT INTO offer_items (offer_id, item_name, quantity, unit_price,
            discount_percent, line_net, line_order)
         VALUES (?, ?, 1, ?, 0.0, ?, ?);""",
        (offer_id, f"Item {line_net}", line_net, line_net, len(str(line_net))),
    )
conn.commit()
conn.close()

from qp_crm.offer.app import recalc_totals

recalc_totals(offer_id)
conn = get_db()
cur = conn.cursor()
cur.execute("SELECT * FROM offers WHERE id = ?;", (offer_id,))
row = dict(cur.fetchone())
for key in ("total_net", "total_discount", "total_net_after_discount",
            "total_special_discount", "total_net_after_special_discount",
            "total_third_discount", "total_net_after_third_discount",
            "total_vat", "total_gross"):
    print(f"{key} = {row[key]!r}")
conn.close()

section("B2. recalc_totals: NULL discount/vat coercion")
conn = get_db()
cur = conn.cursor()
cur.execute(
    """INSERT INTO offers (offer_number, date, client_name, currency, exchange_rate,
        discount_percent, special_discount_percent, third_discount_percent, vat_percent)
     VALUES ('CAP-2026-002', '2026-03-15', 'Null d.o.o.', 'RSD', 1.0, NULL, NULL, NULL, NULL);"""
)
null_offer_id = cur.lastrowid
cur.execute(
    """INSERT INTO offer_items (offer_id, item_name, quantity, unit_price,
        discount_percent, line_net, line_order)
     VALUES (?, 'Item', 1, 100.0, 0.0, 100.0, 1);""", (null_offer_id,)
)
conn.commit()
conn.close()
recalc_totals(null_offer_id)
conn = get_db()
cur = conn.cursor()
cur.execute("SELECT discount_percent, special_discount_percent, third_discount_percent, vat_percent, total_net, total_gross FROM offers WHERE id = ?;", (null_offer_id,))
row = dict(cur.fetchone())
for key, val in row.items():
    print(f"{key} = {val!r}")
conn.close()

section("B3. recalc_totals: float artifact sums (33.33 + 0.1)")
conn = get_db()
cur = conn.cursor()
cur.execute(
    """INSERT INTO offers (offer_number, date, client_name, currency, exchange_rate,
        discount_percent, special_discount_percent, third_discount_percent, vat_percent)
     VALUES ('CAP-2026-003', '2026-03-15', 'Float d.o.o.', 'RSD', 1.0, 0.0, 0.0, 0.0, 0.20);"""
)
float_offer_id = cur.lastrowid
for name, net in (("A", 33.33), ("B", 0.1)):
    cur.execute(
        """INSERT INTO offer_items (offer_id, item_name, quantity, unit_price,
            discount_percent, line_net, line_order)
         VALUES (?, ?, 1, ?, 0.0, ?, ?);""",
        (float_offer_id, name, net, net, 1 if name == "A" else 2),
    )
conn.commit()
conn.close()
recalc_totals(float_offer_id)
conn = get_db()
cur = conn.cursor()
cur.execute("SELECT total_net, total_vat, total_gross FROM offers WHERE id = ?;", (float_offer_id,))
row = dict(cur.fetchone())
for key, val in row.items():
    print(f"{key} = {val!r}")
conn.close()

# ---------------------------------------------------------------- rent math
section("C. rent pmt / calculate_rent")
from qp_crm.rent.app import pmt, calculate_rent, _add_months, generate_schedule

print(f"pmt(0.0, 48, -16000, 4000)       = {pmt(0.0, 48, -16000, 4000)!r}")
print(f"pmt(0.14/12, 48, -16000, 4000)   = {pmt(0.14 / 12, 48, -16000, 4000)!r}")
print(f"pmt(0.14/12, 48, -16000, 4000,1) = {pmt(0.14 / 12, 48, -16000, 4000, 1)!r}")
try:
    pmt(0.0, 0, -16000)
except Exception as e:
    print(f"pmt(0.0, 0, -16000) -> {type(e).__name__}: {e}")
try:
    pmt(0.1, 48, 0)  # pv=0 -> num=0*factor+0=0... fine; use nper=0 rate>0 instead
except Exception:
    pass
try:
    pmt(0.1, 0, -16000)
except Exception as e:
    print(f"pmt(0.1, 0, -16000) -> {type(e).__name__}: {e}")

calc = calculate_rent(20000.0, 48, 20.0, 20.0, 14.0, 1.13, 5.0, 20.0, 50.0)
for key, val in calc.items():
    print(f"calc[{key!r}] = {val!r}")

section("C2. _add_months clamping")
for d, months in ((date(2026, 1, 31), 1), (date(2026, 1, 15), 3),
                  (date(2024, 1, 31), 1), (date(2026, 12, 31), 2)):
    print(f"_add_months({d!r}, {months}) = {_add_months(d, months)!r}")

section("C3. generate_schedule (contract 2026-01-15, 3 months)")
rows = generate_schedule(calc, "2026-01-15", 3)
for row in rows:
    print({k: (repr(v) if isinstance(v, float) else v) for k, v in row.items()})

section("C4. generate_schedule bad-date fallback (compare to today)")
rows_bad = generate_schedule(calc, "not-a-date", 1)
print(f"first row datum = {rows_bad[0]['datum']!r}  (date.today() = {date.today().strftime('%d.%m.%Y')!r})")

# --------------------------------------------------------------- formatting
section("D. shared format_amount / format_date")
from qp_crm.shared.utils import format_amount, format_date

for val in (None, 0, 12312, 1234.5, -1234.5, "abc", "12.5", 1234567.891, 0.005, 1e6):
    print(f"format_amount({val!r}) = {format_amount(val)!r}")
for date_str, fmt in (("2026-01-15", "DD/MM/YYYY"), ("2026-01-15", "MM/DD/YYYY"),
                      ("2026-01-15", "DD.MM.YYYY"), ("2026-01-15", "YYYY-MM-DD"),
                      ("2026-01-15", None), ("15-01-2026", "DD/MM/YYYY"),
                      ("garbage", "DD/MM/YYYY"), (None, "DD/MM/YYYY"), ("", "DD/MM/YYYY")):
    print(f"format_date({date_str!r}, {fmt!r}) = {format_date(date_str, fmt)!r}")

# --------------------------------------------------------- doc placeholders
section("E. rent _build_doc_context + format_document_html")
from qp_crm.rent.app import _build_doc_context, format_document_html

contract = {
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
ctx = _build_doc_context(contract, calc)
for key, val in ctx.items():
    print(f"ctx[{key!r}] = {val!r}")

sample = (
    "<p><strong>\u010cLAN 1.</strong></p>\n"
    "<p>text</p>\n"
    "<p><strong>\u010clan 2</strong></p>\n"
    "<p><strong>Pla\u0107anje zakupnine</strong></p>\n"
    "<p><strong>Nepoznato poglavlje</strong></p>\n"
)
print("format_document_html(sample) =")
print(format_document_html(sample))

print("\nDONE")
