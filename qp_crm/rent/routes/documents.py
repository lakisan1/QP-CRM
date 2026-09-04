"""Rent per-contract document routes: list/editor, save, PDF print."""
import datetime
import io
import os

from flask import redirect, render_template, request, send_file, url_for
from weasyprint import HTML

from ..app import (bp, APP_ASSETS_DIR, BASE_DIR, DEFAULT_RENT_EMAIL,
                   DEFAULT_RENT_EMAIL_SUBJECT, _build_doc_context,
                   calculate_rent, format_document_html, get_db,
                   sort_rent_templates)


@bp.route("/contracts/<int:contract_id>/documents")
def contract_documents(contract_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM rent_contracts WHERE id=?;", (contract_id,))
    contract = cur.fetchone()
    if not contract:
        conn.close()
        return "Ugovor nije pronađen", 404

    cur.execute("SELECT * FROM rent_templates ORDER BY id;")
    templates = sort_rent_templates(cur.fetchall())

    cur.execute("SELECT template_slug, updated_at FROM rent_contract_documents WHERE contract_id=?;", (contract_id,))
    saved_slugs = {row["template_slug"]: row["updated_at"] for row in cur.fetchall()}

    # Fetch email preset and substitute placeholders
    _DEFAULT_EMAIL = DEFAULT_RENT_EMAIL
    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_preset';")
    row = cur.fetchone()
    email_preset = (row["value"] if row else _DEFAULT_EMAIL)
    email_preset = email_preset.replace("{{ client_name }}", contract["client_name"] or "")
    email_preset = email_preset.replace("{{ contract_number }}", contract["contract_number"] or str(contract_id))

    # Fetch email subject preset
    _DEFAULT_SUBJECT = DEFAULT_RENT_EMAIL_SUBJECT
    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_subject';")
    subj_row = cur.fetchone()
    email_subject = (subj_row["value"] if subj_row else _DEFAULT_SUBJECT)
    email_subject = email_subject.replace("{{ client_name }}", contract["client_name"] or "")
    email_subject = email_subject.replace("{{ contract_number }}", contract["contract_number"] or str(contract_id))
    email_subject = email_subject.replace("{{client_name}}", contract["client_name"] or "")
    email_subject = email_subject.replace("{{contract_number}}", contract["contract_number"] or str(contract_id))

    client_email = contract["client_email"] or ""

    conn.close()

    return render_template("rent/rent_contract_documents.html",
                           contract=contract,
                           templates=templates,
                           saved_slugs=saved_slugs,
                           email_preset=email_preset,
                           email_subject=email_subject,
                           client_email=client_email)



# ─── Document editor (GET = load/create draft, POST = save edits) ───────────────
@bp.route("/contracts/<int:contract_id>/documents/<slug>", methods=["GET", "POST"])
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
        return redirect(url_for("rent.document_editor", contract_id=contract_id, slug=slug))

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
        # G26: Escape values before replacing placeholders to avoid corrupting HTML
        import html
        for key, value in ctx.items():
            safe_value = html.escape(str(value))
            raw_html = raw_html.replace("{{ " + key + " }}", safe_value)
            raw_html = raw_html.replace("{{" + key + "}}", safe_value)
        html_content = format_document_html(raw_html)

    conn.close()
    return render_template("rent/rent_document_editor.html",
                           contract=contract,
                           template=template,
                           html_content=html_content)


# ─── Print document to PDF ─────────────────────────────────────────────────────
@bp.route("/contracts/<int:contract_id>/documents/<slug>/pdf")
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
        # G26: Escape values before replacing placeholders to avoid corrupting HTML
        import html
        for key, value in ctx.items():
            safe_value = html.escape(str(value))
            raw_html = raw_html.replace("{{ " + key + " }}", safe_value)
            raw_html = raw_html.replace("{{" + key + "}}", safe_value)
        html_content = format_document_html(raw_html)

    # G25: Use base64 data URI for the logo so it works on remote servers too
    logo_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
    logo_url = ""
    if os.path.exists(logo_path):
        try:
            import base64
            with open(logo_path, "rb") as lf:
                logo_b64 = base64.b64encode(lf.read()).decode("ascii")
            logo_url = f"data:image/jpeg;base64,{logo_b64}"
        except Exception as e:
            print(f"Warning: Could not encode logo: {e}")

    html_str = render_template("rent/rent_pdf_document.html",
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
