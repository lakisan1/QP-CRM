from flask import Blueprint, Flask, render_template, request, redirect, url_for, send_file, jsonify, session
import sqlite3
import os
import sys
import io
import csv
import math
from datetime import date, datetime
from calendar import monthrange
from weasyprint import HTML

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.append(PARENT_DIR)

from shared.config import BASE_DIR, APP_DATA_DIR, DATABASE, APP_ASSETS_DIR, STATIC_DIR
from shared.db import get_db
from shared.auth import check_password
from shared.utils import format_amount
from shared.web import (
    get_theme,
    make_auth_hook,
    fetch_rent_defaults,
    sort_rent_templates,
    DEFAULT_RENT_EMAIL,
    DEFAULT_RENT_EMAIL_SUBJECT,
)
from services.rent_service import (
    pmt,
    _add_months,
    calculate_rent,
    generate_schedule,
    _build_doc_context,
    format_document_html,
)
from rent.import_templates import seed_templates

# ---------------------------------------------------------------------------
# Phase 2 stage 1: rent is a Blueprint on the single QP-CRM app.
#
# The Flask(...) instance, secret key and SESSION_COOKIE_NAME moved to
# main.py (one session/secret/cookie; RENT_SECRET_KEY and the rent_session
# cookie are no longer read). The rent_authenticated session flag keeps its
# pre-consolidation name -- it was already module-scoped. Routes keep the
# same URLs via the blueprint's /rent prefix in main.py; endpoints are
# namespaced (rent.list_contracts, ...) and templates live under
# rent/templates/rent/.
# ---------------------------------------------------------------------------

bp = Blueprint("rent", __name__, template_folder="templates")

CSV_DIR = os.path.join(BASE_DIR, "excell Rent calc")


# Per-module login hook from shared/web.py (rent_authenticated keeps its
# pre-consolidation module-scoped name).
bp.before_request(make_auth_hook("rent_authenticated", "rent.login"))




def init_db():
    """Thin wrapper -- the DDL lives in shared/schema.py (single source).
    Seeding (clients/equipment CSV, rent templates) stays here: it is data,
    not schema."""
    from shared.schema import create_rent_tables, migrate_rent_tables

    conn = get_db()
    cur = conn.cursor()
    create_rent_tables(cur)
    conn.commit()

    # Migration: add is_signed column if it doesn't exist (backward compatible)
    migrate_rent_tables(cur)
    conn.commit()

    # Seed from CSV if tables are empty
    _seed_clients(conn)
    _seed_equipment(conn)
    seed_templates(conn)

    conn.close()



def _clean_num(s):
    if not s:
        return None
    s = str(s).strip().replace('\xa0', '').replace(' ', '')
    s = s.replace('.', '').replace(',', '.')
    s = s.replace('€', '').replace('-', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def _seed_clients(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM rent_clients;")
    if cur.fetchone()["c"] > 0:
        return
    csv_path = os.path.join(CSV_DIR, "Marikovic Hofmann Rent MUSTERIJE.csv")
    if not os.path.exists(csv_path):
        return
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("Ime Firme") or "").strip()
            if not name or name.startswith("_"):
                continue
            cur.execute("""
                INSERT INTO rent_clients (name, mb, pib, account, address, representative, email, rent_address, guarantor)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                name,
                (row.get("Maticni Broj Firme") or "").strip(),
                (row.get("PIB Firme") or "").strip(),
                (row.get("Broj racuna Zakupca") or "").strip(),
                (row.get("Adresa Sedista") or "").strip(),
                (row.get("Ime i Prezime Potpisnika Ugovora") or "").strip(),
                (row.get("eMail Zakupca") or "").strip(),
                (row.get("Adresa Zakupa") or "").strip(),
                (row.get("Jamac: Ime, Grad, JMBG: ") or "").strip(),
            ))
    conn.commit()


def _seed_equipment(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as c FROM rent_equipment;")
    if cur.fetchone()["c"] > 0:
        return
    csv_path = os.path.join(CSV_DIR, "Marikovic Hofmann Rent Oprema.csv")
    if not os.path.exists(csv_path):
        return
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("NAZIV MAX 255 karaktera") or "").strip()
            if not name:
                continue
            price = _clean_num(row.get("CENA")) or 0
            months_raw = (row.get("BROJ MESECI") or "48").strip()
            try:
                months = int(months_raw)
            except ValueError:
                months = 48
            stopa_raw = (row.get("Stopa Troska") or "5,00%").strip().replace('%', '').replace(',', '.')
            try:
                guarantee = float(stopa_raw)
            except ValueError:
                guarantee = 5.0
            ucesce_val = _clean_num(row.get("Ucesce"))
            if ucesce_val and price > 0:
                dp_pct = round(ucesce_val / price * 100, 2)
            else:
                dp_pct = 20.0
            cur.execute("""
                INSERT INTO rent_equipment (name, price, default_rent_months, default_guarantee_rate, default_downpayment_percent)
                VALUES (?,?,?,?,?)
            """, (name, price, months, guarantee, dp_pct))
    conn.commit()


# ─── Context processor ─────────────────────────────────────────────────────────
@bp.context_processor
def inject_helpers():
    return dict(format_amount=format_amount, theme=get_theme())


# ─── Routes ────────────────────────────────────────────────────────────────────

# Phase 2 stage 5: route groups live in rent/routes/; importing them
# registers their @bp.route functions on the blueprint defined above.
from . import routes  # noqa: E402,F401
