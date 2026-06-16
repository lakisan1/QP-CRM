from flask import Flask, render_template, request, redirect, url_for, send_file, jsonify, session
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
from rent.import_templates import seed_templates

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static"
)
app.secret_key = "crm_rent_secret_key_change_me"
app.config['SESSION_COOKIE_NAME'] = 'rent_session'

CSV_DIR = os.path.join(BASE_DIR, "excell Rent calc")


@app.before_request
def check_auth():
    if request.endpoint in ('login', 'static'):
        return None
    if not session.get('rent_authenticated'):
        return redirect(url_for('login'))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if check_password("rent", request.form.get("password")):
            session['rent_authenticated'] = True
            return redirect(url_for('index'))
        else:
            error = "Pogrešna lozinka"
    return render_template("rent_login.html", error=error)


@app.route("/logout")
def logout():
    session.pop('rent_authenticated', None)
    return redirect('/')


# ─── PMT helper ────────────────────────────────────────────────────────────────
def pmt(rate, nper, pv, fv=0, pmt_type=0):
    """Replicate Excel PMT. Returns the periodic payment (positive = outflow)."""
    if rate == 0:
        return -(pv + fv) / nper
    factor = (1 + rate) ** nper
    num = pv * factor + fv
    den = (factor - 1) / rate
    if pmt_type == 1:
        den *= (1 + rate)
    return -num / den


def calculate_rent(price, period_months, downpayment_pct, salvage_pct,
                   interest_rate, insurance_rate, guarantee_rate, vat_pct, admin_fee):
    """Return dict with all calculated rent fields."""
    ucesce = price * downpayment_pct / 100.0
    ucesce_pdv = ucesce * vat_pct / 100.0
    ucesce_bruto = ucesce + ucesce_pdv

    ostatak = price * salvage_pct / 100.0

    monthly_rate = interest_rate / 100.0 / 12.0
    rata_fin = pmt(monthly_rate, period_months, -(price - ucesce), ostatak, 0)

    osiguranje = insurance_rate / 100.0 * price / 12.0
    garancija = price * guarantee_rate / 100.0 / period_months

    rata_neto = rata_fin + osiguranje + garancija
    rata_pdv = rata_neto * vat_pct / 100.0
    rata_bruto = rata_neto + rata_pdv

    zatvaranje = ucesce_bruto / period_months
    rata_nakon = rata_bruto - zatvaranje

    admin_pdv = admin_fee * vat_pct / 100.0
    admin_bruto = admin_fee + admin_pdv

    return {
        "ucesce": ucesce,
        "ucesce_pdv": ucesce_pdv,
        "ucesce_bruto": ucesce_bruto,
        "ostatak": ostatak,
        "rata_fin": rata_fin,
        "osiguranje": osiguranje,
        "garancija": garancija,
        "rata_neto": rata_neto,
        "rata_pdv": rata_pdv,
        "rata_bruto": rata_bruto,
        "zatvaranje": zatvaranje,
        "rata_nakon": rata_nakon,
        "admin_fee": admin_fee,
        "admin_pdv": admin_pdv,
        "admin_bruto": admin_bruto,
    }


def _add_months(d, months):
    """Add months to a date using pure stdlib."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last_day = monthrange(year, month)[1]
    return d.replace(year=year, month=month, day=min(d.day, last_day))


def generate_schedule(calc, contract_date_str, period_months):
    """Generate payment schedule rows."""
    rows = []
    try:
        d = datetime.strptime(contract_date_str, "%Y-%m-%d").date()
    except Exception:
        d = date.today()

    rows.append({
        "nr": "0.1", "neto": None, "avans": None,
        "druge": calc["admin_fee"], "pdv": calc["admin_pdv"],
        "suma": calc["admin_bruto"], "zatvaranje": None, "suma_nakon": None,
        "datum": d.strftime("%d.%m.%Y"), "opis": "Uplata naknada za procenu boniteta",
    })
    rows.append({
        "nr": "0.2", "neto": None, "avans": calc["ucesce"], "druge": None,
        "pdv": calc["ucesce_pdv"], "suma": calc["ucesce_bruto"],
        "zatvaranje": None, "suma_nakon": None,
        "datum": d.strftime("%d.%m.%Y"), "opis": "Uplata avansa",
    })

    for i in range(1, period_months + 1):
        row_d = _add_months(d, i)
        last_day = monthrange(row_d.year, row_d.month)[1]
        row_date = row_d.replace(day=last_day)
        rows.append({
            "nr": str(i), "neto": calc["rata_neto"], "avans": None, "druge": None,
            "pdv": calc["rata_pdv"], "suma": calc["rata_bruto"],
            "zatvaranje": calc["zatvaranje"], "suma_nakon": calc["rata_nakon"],
            "datum": row_date.strftime("%d.%m.%Y"), "opis": "Zakupnina",
        })
    return rows


# ─── DB init ───────────────────────────────────────────────────────────────────
def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mb TEXT,
            pib TEXT,
            account TEXT,
            address TEXT,
            representative TEXT,
            email TEXT,
            rent_address TEXT,
            guarantor TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            default_rent_months INTEGER DEFAULT 48,
            default_guarantee_rate REAL DEFAULT 5.0,
            default_downpayment_percent REAL DEFAULT 20.0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_number TEXT,
            contract_date TEXT,
            client_name TEXT,
            client_mb TEXT,
            client_pib TEXT,
            client_account TEXT,
            client_address TEXT,
            client_representative TEXT,
            client_email TEXT,
            rent_address TEXT,
            guarantor TEXT,
            delivery_time TEXT,
            delivery_date TEXT,
            equipment_model TEXT,
            price REAL DEFAULT 0,
            vat_percent REAL DEFAULT 20.0,
            period_months INTEGER DEFAULT 48,
            downpayment_percent REAL DEFAULT 20.0,
            salvage_value_percent REAL DEFAULT 20.0,
            interest_rate REAL DEFAULT 14.0,
            insurance_rate REAL DEFAULT 1.13,
            guarantee_rate REAL DEFAULT 5.0,
            admin_fee REAL DEFAULT 50.0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            content_html TEXT NOT NULL DEFAULT ''
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_contract_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER NOT NULL,
            template_slug TEXT NOT NULL,
            custom_content_html TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            UNIQUE(contract_id, template_slug)
        );
    """)

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
@app.context_processor
def inject_helpers():
    return dict(format_amount=format_amount, theme=_get_theme())


def _get_theme():
    return request.cookies.get("theme", "dark")


# ─── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return redirect(url_for("list_contracts"))


@app.route("/contracts")
def list_contracts():
    search = request.args.get("search", "").strip()
    date_from = request.args.get("date_from", "").strip()
    date_to = request.args.get("date_to", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    conn = get_db()
    cur = conn.cursor()

    clauses, params = [], []
    if search:
        clauses.append("(contract_number LIKE ? OR client_name LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if date_from:
        clauses.append("contract_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("contract_date <= ?")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    cur.execute(f"SELECT COUNT(*) as c FROM rent_contracts {where}", params)
    total = cur.fetchone()["c"]
    total_pages = math.ceil(total / per_page) if total else 1

    cur.execute(f"SELECT * FROM rent_contracts {where} ORDER BY contract_date DESC, id DESC LIMIT {per_page} OFFSET {offset}", params)
    contracts = cur.fetchall()
    conn.close()

    return render_template("rent_contracts.html",
                           contracts=contracts,
                           search=search, date_from=date_from, date_to=date_to,
                           current_page=page, total_pages=total_pages, total=total,
                           calculate_rent=calculate_rent)


@app.route("/contracts/new", methods=["GET", "POST"])
def new_contract():
    return _contract_form(None)


@app.route("/contracts/edit/<int:contract_id>", methods=["GET", "POST"])
def edit_contract(contract_id):
    return _contract_form(contract_id)


def _get_rent_defaults():
    """Fetch rent default parameters from global_settings."""
    conn = get_db()
    cur = conn.cursor()
    keys = {
        'rent_default_interest_rate': 14.0,
        'rent_default_insurance_rate': 1.13,
        'rent_default_guarantee_rate': 5.0,
        'rent_default_admin_fee': 50.0,
        'rent_default_vat_percent': 20.0,
        'rent_default_salvage_value_percent': 20.0,
        'rent_default_downpayment_percent': 20.0,
        'rent_default_period_months': 48,
    }
    result = {}
    for key, default in keys.items():
        cur.execute("SELECT value FROM global_settings WHERE key = ?;", (key,))
        row = cur.fetchone()
        result[key] = row["value"] if row else str(default)
    conn.close()
    return result


def generate_next_contract_number(db_conn, contract_date_str):
    """Generate contract number using: counter (zero-padded 2 chars) + month (2 chars) + year (2 chars)."""
    try:
        dt = datetime.strptime(contract_date_str, "%Y-%m-%d")
    except Exception:
        dt = date.today()
    
    year_short = dt.strftime("%y")  # '26'
    month_str = dt.strftime("%m")   # '06'
    
    cur = db_conn.cursor()
    pattern = f"{dt.year:04d}-{dt.month:02d}-%"
    cur.execute("SELECT COUNT(*) as cnt FROM rent_contracts WHERE contract_date LIKE ?;", (pattern,))
    count = cur.fetchone()["cnt"]
    
    next_counter = count + 1
    return f"{next_counter:02d}{month_str}{year_short}"


def _contract_form(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_clients ORDER BY name;")
    clients = cur.fetchall()
    cur.execute("SELECT * FROM rent_equipment ORDER BY name;")
    equipment = cur.fetchall()

    contract = None
    if contract_id:
        cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
        contract = cur.fetchone()

    if request.method == "POST":
        c_number = request.form.get("contract_number", "").strip()
        c_date = request.form.get("contract_date") or date.today().isoformat()
        
        # Auto-generate if new and contract number is empty
        if not contract_id and not c_number:
            c_number = generate_next_contract_number(conn, c_date)

        data = {
            "contract_number": c_number,
            "contract_date": c_date,
            "client_name": request.form.get("client_name", "").strip(),
            "client_mb": request.form.get("client_mb", "").strip(),
            "client_pib": request.form.get("client_pib", "").strip(),
            "client_account": request.form.get("client_account", "").strip(),
            "client_address": request.form.get("client_address", "").strip(),
            "client_representative": request.form.get("client_representative", "").strip(),
            "client_email": request.form.get("client_email", "").strip(),
            "rent_address": request.form.get("rent_address", "").strip(),
            "guarantor": request.form.get("guarantor", "").strip(),
            "delivery_time": request.form.get("delivery_time", "").strip(),
            "delivery_date": request.form.get("delivery_date", "").strip(),
            "equipment_model": request.form.get("equipment_model", "").strip(),
            "price": float(request.form.get("price") or 0),
            "vat_percent": float(request.form.get("vat_percent") or 20),
            "period_months": int(request.form.get("period_months") or 48),
            "downpayment_percent": float(request.form.get("downpayment_percent") or 20),
            "salvage_value_percent": float(request.form.get("salvage_value_percent") or 20),
            "interest_rate": float(request.form.get("interest_rate") or 14),
            "insurance_rate": float(request.form.get("insurance_rate") or 1.13),
            "guarantee_rate": float(request.form.get("guarantee_rate") or 5),
            "admin_fee": float(request.form.get("admin_fee") or 50),
        }
        cols = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        if contract_id:
            sets = ", ".join(f"{k}=?" for k in data.keys())
            cur.execute(f"UPDATE rent_contracts SET {sets} WHERE id=?;", list(data.values()) + [contract_id])
            conn.commit()
            conn.close()
            return redirect(url_for("edit_contract", contract_id=contract_id))
        else:
            cur.execute(f"INSERT INTO rent_contracts ({cols}) VALUES ({placeholders});", list(data.values()))
            new_id = cur.lastrowid
            conn.commit()
            conn.close()
            return redirect(url_for("edit_contract", contract_id=new_id))

    conn.close()
    rent_defaults = _get_rent_defaults()
    return render_template("rent_contract_form.html",
                           contract=contract,
                           clients=clients,
                           equipment=equipment,
                           today=date.today().isoformat(),
                           rent_defaults=rent_defaults)


@app.route("/contracts/delete/<int:contract_id>", methods=["POST"])
def delete_contract(contract_id):
    conn = get_db()
    conn.execute("DELETE FROM rent_contracts WHERE id=?;", (contract_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("list_contracts"))


@app.route("/contracts/duplicate/<int:contract_id>", methods=["POST"])
def duplicate_contract(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
    row = cur.fetchone()
    if row:
        d = dict(row)
        d.pop("id")
        d["contract_number"] = d.get("contract_number", "") + "-KOPIJA"
        cols = ", ".join(d.keys())
        placeholders = ", ".join(["?"] * len(d))
        cur.execute(f"INSERT INTO rent_contracts ({cols}) VALUES ({placeholders});", list(d.values()))
        new_id = cur.lastrowid
        conn.commit()
        conn.close()
        return redirect(url_for("edit_contract", contract_id=new_id))
    conn.close()
    return redirect(url_for("list_contracts"))


# ─── API endpoints ─────────────────────────────────────────────────────────────
@app.route("/api/client/<int:client_id>")
def api_client(client_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_clients WHERE id=?;", (client_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({}), 404
    return jsonify(dict(row))


@app.route("/api/equipment/<int:eq_id>")
def api_equipment(eq_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_equipment WHERE id=?;", (eq_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return jsonify({}), 404
    return jsonify(dict(row))


@app.route("/api/calculate")
def api_calculate():
    try:
        price = float(request.args.get("price", 0))
        period = int(request.args.get("period_months", 48))
        dp = float(request.args.get("downpayment_percent", 20))
        sv = float(request.args.get("salvage_value_percent", 20))
        ir = float(request.args.get("interest_rate", 14))
        ins = float(request.args.get("insurance_rate", 1.13))
        gr = float(request.args.get("guarantee_rate", 5))
        vat = float(request.args.get("vat_percent", 20))
        admin = float(request.args.get("admin_fee", 50))
        result = calculate_rent(price, period, dp, sv, ir, ins, gr, vat, admin)
        return jsonify({k: round(v, 4) for k, v in result.items()})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─── PDF Routes ────────────────────────────────────────────────────────────────
@app.route("/contracts/pdf/offer/<int:contract_id>")
def pdf_offer(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
    contract = cur.fetchone()
    conn.close()
    if not contract:
        return "Not found", 404

    c = dict(contract)
    calc = calculate_rent(
        c["price"], c["period_months"], c["downpayment_percent"],
        c["salvage_value_percent"], c["interest_rate"], c["insurance_rate"],
        c["guarantee_rate"], c["vat_percent"], c["admin_fee"]
    )

    logo_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
    logo_url = f"file://{logo_path}" if os.path.exists(logo_path) else ""

    html_str = render_template("rent_pdf_offer.html",
                               contract=c, calc=calc,
                               logo_url=logo_url, pdf_mode=True)
    pdf_bytes = HTML(string=html_str, base_url=BASE_DIR).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    filename = f"Ponuda_{c.get('contract_number','') or contract_id}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=False, download_name=filename)


@app.route("/contracts/pdf/schedule/<int:contract_id>")
def pdf_schedule(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
    contract = cur.fetchone()
    conn.close()
    if not contract:
        return "Not found", 404

    c = dict(contract)
    calc = calculate_rent(
        c["price"], c["period_months"], c["downpayment_percent"],
        c["salvage_value_percent"], c["interest_rate"], c["insurance_rate"],
        c["guarantee_rate"], c["vat_percent"], c["admin_fee"]
    )
    schedule = generate_schedule(calc, c["contract_date"], c["period_months"])

    logo_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
    logo_url = f"file://{logo_path}" if os.path.exists(logo_path) else ""

    html_str = render_template("rent_pdf_schedule.html",
                               contract=c, calc=calc, schedule=schedule,
                               logo_url=logo_url, pdf_mode=True)
    pdf_bytes = HTML(string=html_str, base_url=BASE_DIR).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    filename = f"Plan_Placanja_{c.get('contract_number','') or contract_id}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=False, download_name=filename)


# ─── Clients CRUD ──────────────────────────────────────────────────────────────
@app.route("/clients", methods=["GET", "POST"])
def list_clients():
    conn = get_db()
    cur = conn.cursor()
    msg = None
    edit_client = None
    edit_id = request.args.get("edit_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "save":
            data = {
                "name": request.form.get("name", "").strip(),
                "mb": request.form.get("mb", "").strip(),
                "pib": request.form.get("pib", "").strip(),
                "account": request.form.get("account", "").strip(),
                "address": request.form.get("address", "").strip(),
                "representative": request.form.get("representative", "").strip(),
                "email": request.form.get("email", "").strip(),
                "rent_address": request.form.get("rent_address", "").strip(),
                "guarantor": request.form.get("guarantor", "").strip(),
            }
            cid = request.form.get("client_id", type=int)
            if cid:
                sets = ", ".join(f"{k}=?" for k in data)
                cur.execute(f"UPDATE rent_clients SET {sets} WHERE id=?;", list(data.values()) + [cid])
            else:
                cols = ", ".join(data.keys())
                ph = ", ".join(["?"] * len(data))
                cur.execute(f"INSERT INTO rent_clients ({cols}) VALUES ({ph});", list(data.values()))
            conn.commit()
            msg = "Sačuvano."
        elif action == "delete":
            cid = request.form.get("client_id", type=int)
            cur.execute("DELETE FROM rent_clients WHERE id=?;", (cid,))
            conn.commit()
            msg = "Obrisano."
        conn.close()
        return redirect(url_for("list_clients"))

    if edit_id:
        cur.execute("SELECT * FROM rent_clients WHERE id=?;", (edit_id,))
        edit_client = cur.fetchone()

    cur.execute("SELECT * FROM rent_clients ORDER BY name;")
    clients = cur.fetchall()
    conn.close()
    return render_template("rent_clients.html", clients=clients, edit_client=edit_client, msg=msg)


# ─── Equipment CRUD ────────────────────────────────────────────────────────────
@app.route("/equipment", methods=["GET", "POST"])
def list_equipment():
    conn = get_db()
    cur = conn.cursor()
    msg = None
    edit_eq = None
    edit_id = request.args.get("edit_id", type=int)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "save":
            data = {
                "name": request.form.get("name", "").strip(),
                "price": float(request.form.get("price") or 0),
                "default_rent_months": int(request.form.get("default_rent_months") or 48),
                "default_guarantee_rate": float(request.form.get("default_guarantee_rate") or 5),
                "default_downpayment_percent": float(request.form.get("default_downpayment_percent") or 20),
            }
            eid = request.form.get("eq_id", type=int)
            if eid:
                sets = ", ".join(f"{k}=?" for k in data)
                cur.execute(f"UPDATE rent_equipment SET {sets} WHERE id=?;", list(data.values()) + [eid])
            else:
                cols = ", ".join(data.keys())
                ph = ", ".join(["?"] * len(data))
                cur.execute(f"INSERT INTO rent_equipment ({cols}) VALUES ({ph});", list(data.values()))
            conn.commit()
            msg = "Sačuvano."
        elif action == "delete":
            eid = request.form.get("eq_id", type=int)
            cur.execute("DELETE FROM rent_equipment WHERE id=?;", (eid,))
            conn.commit()
            msg = "Obrisano."
        conn.close()
        return redirect(url_for("list_equipment"))

    if edit_id:
        cur.execute("SELECT * FROM rent_equipment WHERE id=?;", (edit_id,))
        edit_eq = cur.fetchone()

    cur.execute("SELECT * FROM rent_equipment ORDER BY name;")
    equipment = cur.fetchall()
    conn.close()
    return render_template("rent_equipment.html", equipment=equipment, edit_eq=edit_eq, msg=msg)


# ─── Helper: format document HTML with official headings ───────────────────────
def format_document_html(html: str) -> str:
    if not html:
        return ""
    import re
    # 1. Replace <p><strong>Član 1</strong></p> with <h3 class="clan-header">Član \1.</h3>
    html = re.sub(
        r'<p>\s*<strong>\s*Član\s+(\d+)\s*\.?\s*</strong>\s*</p>',
        r'<h3 class="clan-header">Član \1.</h3>',
        html
    )
    # 2. Replace specific section headers that are wrapped in <p><strong>...</strong></p>
    headers = [
        'Predmet ugovora',
        'Predmet zakupa, trajanje zakupa i zakupnina',
        'Primopredaja Predmeta zakupa',
        'Odgovornost Ugovarača u vezi Predmeta zakupa',
        'Plaćanje zakupnine',
        'Kašnjenje u plaćanju',
        'Održavanje i upotreba Predmeta zakupa',
        'Osiguranje predmeta',
        'Obaveze obaveštavanja i dozvola pristupa',
        'Sredstva obezbeđenja',
        'Završne odredbe'
    ]
    for h in headers:
        html = re.sub(
            rf'<p>\s*<strong>\s*({h})[\s\t\.]*\s*</strong>\s*</p>',
            r'<h4 class="section-header">\1</h4>',
            html
        )
    return html


# ─── Helper: build template context for a contract ─────────────────────────────
def _build_doc_context(contract: dict, calc: dict) -> dict:
    """Return a flat dict mapping all Jinja placeholders to human-readable values."""
    fa = format_amount

    # Format a date from YYYY-MM-DD to DD.MM.YYYY
    def fmt_date(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").strftime("%d.%m.%Y")
        except Exception:
            return s or ""

    return {
        # Contract
        "contract_number":      contract.get("contract_number") or "",
        "contract_date":        fmt_date(contract.get("contract_date") or ""),
        "period_months":        str(contract.get("period_months", "")),
        "delivery_time":        contract.get("delivery_time") or "",
        "delivery_date":        fmt_date(contract.get("delivery_date") or ""),

        # Client
        "client_name":          contract.get("client_name") or "",
        "client_mb":            contract.get("client_mb") or "",
        "client_pib":           contract.get("client_pib") or "",
        "client_account":       contract.get("client_account") or "",
        "client_address":       contract.get("client_address") or "",
        "client_representative": contract.get("client_representative") or "",
        "client_email":         contract.get("client_email") or "",
        "rent_address":         contract.get("rent_address") or "",
        "guarantor":            contract.get("guarantor") or "",

        # Equipment / pricing
        "equipment_model":      contract.get("equipment_model") or "",
        "price_fmt":            fa(contract.get("price", 0)),

        # Calculated values
        "rata_neto_fmt":        fa(calc["rata_neto"]),
        "rata_bruto_fmt":       fa(calc["rata_bruto"]),
        "ucesce_bruto_fmt":     fa(calc["ucesce_bruto"]),
        "ucesce_pdv_fmt":       fa(calc["ucesce_pdv"]),
        "zatvaranje_fmt":       fa(calc["zatvaranje"]),
        "ostatak_fmt":          fa(calc["ostatak"]),
        "osiguranje_fmt":       fa(calc["osiguranje"]),
        "garancija_fmt":        fa(calc["garancija"]),
    }


# ─── Document list for a contract ──────────────────────────────────────────────
@app.route("/contracts/<int:contract_id>/documents")
def contract_documents(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
    contract = cur.fetchone()
    if not contract:
        conn.close()
        return "Ugovor nije pronađen", 404

    cur.execute("SELECT * FROM rent_templates ORDER BY id;")
    templates = cur.fetchall()

    cur.execute("SELECT template_slug, updated_at FROM rent_contract_documents WHERE contract_id=?;", (contract_id,))
    saved_slugs = {row["template_slug"]: row["updated_at"] for row in cur.fetchall()}
    conn.close()

    return render_template("rent_contract_documents.html",
                           contract=contract,
                           templates=templates,
                           saved_slugs=saved_slugs)


# ─── Document editor (GET = load/create draft, POST = save edits) ───────────────
@app.route("/contracts/<int:contract_id>/documents/<slug>", methods=["GET", "POST"])
def document_editor(contract_id, slug):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
    contract = cur.fetchone()
    if not contract:
        conn.close()
        return "Ugovor nije pronađen", 404

    cur.execute("SELECT * FROM rent_templates WHERE slug=?;", (slug,))
    template = cur.fetchone()
    if not template:
        conn.close()
        return "Šablon nije pronađen", 404

    if request.method == "POST":
        content = request.form.get("content", "")
        cur.execute("""
            INSERT INTO rent_contract_documents (contract_id, template_slug, custom_content_html, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(contract_id, template_slug) DO UPDATE SET
                custom_content_html = excluded.custom_content_html,
                updated_at = excluded.updated_at;
        """, (contract_id, slug, content, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return redirect(url_for("document_editor", contract_id=contract_id, slug=slug))

    # GET — check if a draft already exists
    cur.execute("SELECT custom_content_html FROM rent_contract_documents WHERE contract_id=? AND template_slug=?;",
                (contract_id, slug))
    row = cur.fetchone()

    if row:
        html_content = format_document_html(row["custom_content_html"])
    else:
        # Pre-fill master template with contract data using simple string replace
        c = dict(contract)
        calc = calculate_rent(
            c["price"], c["period_months"], c["downpayment_percent"],
            c["salvage_value_percent"], c["interest_rate"], c["insurance_rate"],
            c["guarantee_rate"], c["vat_percent"], c["admin_fee"]
        )
        ctx = _build_doc_context(c, calc)
        raw_html = template["content_html"]
        for key, value in ctx.items():
            raw_html = raw_html.replace("{{ " + key + " }}", str(value))
            raw_html = raw_html.replace("{{" + key + "}}", str(value))
        html_content = format_document_html(raw_html)

    conn.close()
    return render_template("rent_document_editor.html",
                           contract=contract,
                           template=template,
                           html_content=html_content)


# ─── Print document to PDF ─────────────────────────────────────────────────────
@app.route("/contracts/<int:contract_id>/documents/<slug>/pdf")
def document_pdf(contract_id, slug):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
    contract = cur.fetchone()
    cur.execute("SELECT * FROM rent_templates WHERE slug=?;", (slug,))
    template = cur.fetchone()
    if not contract or not template:
        conn.close()
        return "Nije pronađeno", 404

    cur.execute("SELECT custom_content_html FROM rent_contract_documents WHERE contract_id=? AND template_slug=?;",
                (contract_id, slug))
    row = cur.fetchone()
    conn.close()

    if row:
        html_content = format_document_html(row["custom_content_html"])
    else:
        c = dict(contract)
        calc = calculate_rent(
            c["price"], c["period_months"], c["downpayment_percent"],
            c["salvage_value_percent"], c["interest_rate"], c["insurance_rate"],
            c["guarantee_rate"], c["vat_percent"], c["admin_fee"]
        )
        ctx = _build_doc_context(c, calc)
        raw_html = template["content_html"]
        for key, value in ctx.items():
            raw_html = raw_html.replace("{{ " + key + " }}", str(value))
        html_content = format_document_html(raw_html)

    logo_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
    logo_url = f"file://{logo_path}" if os.path.exists(logo_path) else ""

    html_str = render_template("rent_pdf_document.html",
                               contract=dict(contract),
                               template_name=template["name"],
                               html_content=html_content,
                               logo_url=logo_url,
                               pdf_mode=True)
    pdf_bytes = HTML(string=html_str, base_url=BASE_DIR).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    cnum = dict(contract).get("contract_number") or str(contract_id)
    filename = f"{slug}_{cnum}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=False, download_name=filename)

