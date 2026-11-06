"""Admin → Istorija izmena (P-6 User logs, 2026-11-06).

Read-only list of the global audit_log — who created/updated/deleted which
record, and when — with filters by user / table / action / source / date
range. Admin-only (the admin blueprint's require_role('admin') hook) and
read-only (no POST routes, so nothing to CSRF here).
"""

import math
from datetime import datetime, time, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from flask import render_template, request

from ..app import bp
from qp_crm.shared.db import get_db
from qp_crm.shared.auth import list_users

LOCAL_TZ = ZoneInfo("Europe/Belgrade")
PAGE_SIZE = 50

# Human-friendly Serbian labels for the main business tables (fallback: the
# raw table name, which is also what appears for future modules).
TABLE_LABELS = {
    "products": "Proizvodi",
    "prices": "Cene",
    "product_aliases": "Aliasi proizvoda",
    "offers": "Ponude",
    "offer_items": "Stavke ponude",
    "rent_contracts": "Ugovori (rent)",
    "rent_clients": "Klijenti (rent)",
    "rent_contract_documents": "Dokumenti (rent)",
    "rent_templates": "Rent šabloni",
    "contacts": "Imenik",
    "contact_roles": "Uloge kontakata",
    "contact_locations": "Lokacije",
    "equipment": "Oprema",
    "stock_movements": "Promet magacina",
    "reservations": "Rezervacije",
    "equipment_shortfalls": "Manjkovi opreme",
    "purchase_orders": "Narudžbenice",
    "po_lines": "Stavke narudžbenice",
    "brands": "Brendovi",
    "category_pricing_defaults": "Podrazumevane cene kategorija",
    "text_presets": "Tekstualni preset-i",
    "pdf_templates": "PDF šabloni",
    "price_rounding_rules": "Pravila zaokruživanja",
}

ACTION_LABELS = {"created": "kreirao", "updated": "izmenio", "deleted": "obrisao"}
SOURCE_LABELS = {"web": "web", "api": "API", "system": "sistem"}


def _fmt_local(ts):
    """UTC ISO -> 'DD.MM.YYYY HH:MM:SS' in Europe/Belgrade."""
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(LOCAL_TZ).strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return ts


def _local_day_bounds(date_str):
    """(start_ts, end_ts) UTC ISO covering one local calendar day."""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    start = datetime.combine(d, time.min, tzinfo=LOCAL_TZ)
    end = datetime.combine(d, time(23, 59, 59), tzinfo=LOCAL_TZ)
    return (
        start.astimezone(timezone.utc).isoformat(timespec="seconds"),
        end.astimezone(timezone.utc).isoformat(timespec="seconds"),
    )


@bp.route("/audit")
def audit_log_page():
    conn = get_db()
    cur = conn.cursor()

    user_id = request.args.get("user_id", type=int) or None
    table = (request.args.get("table") or "").strip()
    action = (request.args.get("action") or "").strip()
    source = (request.args.get("source") or "").strip()
    date_from = (request.args.get("from") or "").strip()
    date_to = (request.args.get("to") or "").strip()
    page = max(1, request.args.get("page", 1, type=int) or 1)

    where = []
    params = []
    if user_id:
        where.append("user_id = ?")
        params.append(user_id)
    if table:
        where.append("table_name = ?")
        params.append(table)
    if action:
        where.append("action = ?")
        params.append(action)
    if source:
        where.append("source = ?")
        params.append(source)
    if date_from:
        start, _ = _local_day_bounds(date_from)
        where.append("ts >= ?")
        params.append(start)
    if date_to:
        _, end = _local_day_bounds(date_to)
        where.append("ts <= ?")
        params.append(end)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    total = cur.execute(
        f"SELECT COUNT(*) AS c FROM audit_log{where_sql};", params
    ).fetchone()["c"]
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, pages)
    offset = (page - 1) * PAGE_SIZE

    rows = cur.execute(
        f"SELECT * FROM audit_log{where_sql} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?;",
        params + [PAGE_SIZE, offset],
    ).fetchall()

    users = [dict(u) for u in list_users()]
    tables = [
        r[0] for r in cur.execute(
            "SELECT DISTINCT table_name FROM audit_log ORDER BY table_name;"
        ).fetchall()
    ]
    conn.close()

    entries = []
    for r in rows:
        entries.append({
            "id": r["id"],
            "table_name": r["table_name"],
            "table_label": TABLE_LABELS.get(r["table_name"], r["table_name"]),
            "row_id": r["row_id"],
            "action": r["action"],
            "action_label": ACTION_LABELS.get(r["action"], r["action"]),
            "username": r["username"] or "sistem",
            "source": r["source"],
            "source_label": SOURCE_LABELS.get(r["source"], r["source"]),
            "record_label": r["record_label"],
            "ts_local": _fmt_local(r["ts"]),
        })

    # Filter-preserving query string for the pagination links (page added in
    # the template). Built here so Jinja never has to spell the 'from'/'to'
    # kwarg names (reserved words in the template language).
    qs_parts = []
    for key, val in (
        ("user_id", user_id), ("table", table), ("action", action),
        ("source", source), ("from", date_from), ("to", date_to),
    ):
        if val:
            qs_parts.append((key, val))
    pagination_qs = urlencode(qs_parts)

    return render_template(
        "admin/audit.html",
        entries=entries,
        users=users,
        tables=tables,
        table_labels=TABLE_LABELS,
        action_labels=ACTION_LABELS,
        source_labels=SOURCE_LABELS,
        total=total,
        page=page,
        pages=pages,
        pagination_qs=pagination_qs,
        filters={
            "user_id": user_id, "table": table, "action": action,
            "source": source, "from": date_from, "to": date_to,
        },
    )
