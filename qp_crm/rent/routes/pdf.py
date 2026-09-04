"""Rent contract PDF routes: offer, payment schedule, fillable schedule."""
import io
import os

from flask import render_template, send_file
from weasyprint import HTML

from ..app import (bp, APP_ASSETS_DIR, BASE_DIR, calculate_rent,
                   generate_schedule, get_db)


# ─── PDF Routes ────────────────────────────────────────────────────────────────
@bp.route("/contracts/pdf/offer/<int:contract_id>")
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

    html_str = render_template("rent/rent_pdf_offer.html",
                               contract=c, calc=calc,
                               logo_url=logo_url, pdf_mode=True)
    pdf_bytes = HTML(string=html_str, base_url=BASE_DIR).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    filename = f"Prilog_3_Ponuda_{c.get('contract_number','') or contract_id}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=False, download_name=filename)


@bp.route("/contracts/pdf/schedule/<int:contract_id>")
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

    html_str = render_template("rent/rent_pdf_schedule.html",
                               contract=c, calc=calc, schedule=schedule,
                               logo_url=logo_url, pdf_mode=True)
    pdf_bytes = HTML(string=html_str, base_url=BASE_DIR).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    c_num = str(c.get('contract_number', '') or contract_id).replace('/', '-')
    filename = f"Prilog_4_Plan_Placanja_{c_num}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=False, download_name=filename)


@bp.route("/contracts/pdf/schedule_fillable/<int:contract_id>")
def pdf_schedule_fillable(contract_id):
    """Generate a fillable PDF payment tracker (Evidencija Uplata).

    The PDF is created in two passes:
      1. WeasyPrint renders the HTML with empty cells for the two extra columns.
      2. pypdf overlays AcroForm text fields on those empty cells so the user
         can type directly in any PDF reader (Adobe, Foxit, etc.).
    """
    import pypdf
    from pypdf.generic import (
        ArrayObject, DictionaryObject, NameObject,
        NumberObject, TextStringObject,
    )

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

    # Pass 1: WeasyPrint renders to PDF with empty columns
    html_str = render_template("rent/rent_pdf_schedule_fillable.html",
                               contract=c, calc=calc, schedule=schedule,
                               logo_url=logo_url, pdf_mode=True)
    pdf_bytes = HTML(string=html_str, base_url=BASE_DIR).write_pdf()

    # Pass 2: Add AcroForm text fields over the empty cells using pypdf
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    writer = pypdf.PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    num_rows = len(schedule)

    # A4 landscape dimensions in points
    page_width = 842
    page_height = 595

    # Table column positions (approximate, based on HTML template percentages)
    left_margin = 28
    table_width = page_width - left_margin - 28

    # "Uplaćen iznos" column: starts at ~81% of table, width ~10%
    col_amount_x = left_margin + table_width * 0.81
    col_amount_w = table_width * 0.10
    # "Datum uplate" column: starts at ~91%, width ~9%
    col_date_x = left_margin + table_width * 0.91
    col_date_w = table_width * 0.085
    # Collect all field references
    form_fields = ArrayObject()

    # The named destinations give us exact coordinates for each row
    dests = reader.named_destinations

    # Fixed field height to match row size
    field_height = 14.0

    for i in range(num_rows):
        row_id = f"row_{i}"
        if row_id not in dests:
            continue
            
        dest = dests[row_id]
        page_ref = dest['/Page']
        try:
            current_page = reader.pages.index(page_ref)
        except ValueError:
            continue
            
        # The /Top coordinate is in PDF points from the bottom of the page
        # It represents the top edge of the <tr> element.
        # We place the field just inside the cell.
        top_y = float(dest['/Top'])
        y_bottom = top_y - field_height - 1.5 # 1.5pt padding from top
        y_top = top_y - 1.5

        for col_name, col_x, col_w in [
            ("iznos", col_amount_x, col_amount_w),
            ("datum", col_date_x, col_date_w),
        ]:
            field_name = f"{col_name}_{i}"
            rect = ArrayObject([
                NumberObject(int(col_x)),
                NumberObject(int(y_bottom)),
                NumberObject(int(col_x + col_w)),
                NumberObject(int(y_top)),
            ])

            field = DictionaryObject()
            field.update({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/Rect"): rect,
                NameObject("/T"): TextStringObject(field_name),
                NameObject("/V"): TextStringObject(""),
                NameObject("/DA"): TextStringObject("/Helv 7 Tf 0 0 0 rg"),
                NameObject("/Ff"): NumberObject(0),
                NameObject("/Q"): NumberObject(1),
            })

            page = writer.pages[current_page]
            
            # Use pypdf's way to get an indirect reference to the dictionary
            field_ref = writer._add_object(field)
            form_fields.append(field_ref)

            if "/Annots" in page:
                annots = page["/Annots"]
                if hasattr(annots, "get_object"):
                    annots = annots.get_object()
                annots.append(field_ref)
            else:
                page[NameObject("/Annots")] = ArrayObject([field_ref])

    # Set up AcroForm at document level
    writer._root_object.update({
        NameObject("/AcroForm"): DictionaryObject({
            NameObject("/Fields"): form_fields,
            NameObject("/DR"): DictionaryObject({
                NameObject("/Font"): DictionaryObject({
                    NameObject("/Helv"): DictionaryObject({
                        NameObject("/Type"): NameObject("/Font"),
                        NameObject("/Subtype"): NameObject("/Type1"),
                        NameObject("/BaseFont"): NameObject("/Helvetica"),
                    })
                })
            }),
            NameObject("/DA"): TextStringObject("/Helv 7 Tf 0 0 0 rg"),
            NameObject("/NeedAppearances"): pypdf.generic.BooleanObject(True),
        })
    })

    out_buf = io.BytesIO()
    writer.write(out_buf)
    out_buf.seek(0)
    c_num = str(c.get('contract_number', '') or contract_id).replace('/', '-')
    filename = f"Evidencija_Uplata_{c_num}.pdf"
    return send_file(out_buf, mimetype="application/pdf",
                     as_attachment=True, download_name=filename)
