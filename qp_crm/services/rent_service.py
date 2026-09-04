"""Rent calculation services (Phase 2 stage 4).

pmt, _add_months, calculate_rent, generate_schedule, _build_doc_context
and format_document_html moved verbatim from rent/app.py; rent/app.py
imports them back so route call sites and the existing test imports keep
working.
"""

from calendar import monthrange
from datetime import date, datetime, timedelta

from qp_crm.shared.utils import format_amount


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


def _add_months(d, months):
    """Add months to a date using pure stdlib."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last_day = monthrange(year, month)[1]
    return d.replace(year=year, month=month, day=min(d.day, last_day))


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
# Preferred display order + sorter live in shared/web.py (admin's editor
# page sorts identically).


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
