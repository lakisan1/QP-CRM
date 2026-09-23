"""Offer PDF rendering route (filesystem templates + DB templates via
services.pdf_service sandbox)."""
import io
import os
from pathlib import Path

from flask import render_template, request, send_file, url_for
from weasyprint import HTML, CSS

from qp_crm.shared.utils import format_amount, format_date

from ..app import bp, BASE_DIR, APP_ASSETS_DIR, IMAGE_DIR, get_country_list, get_date_format, get_db



import io
from flask import send_file, request

from pathlib import Path

@bp.route("/offers/<int:offer_id>/pdf")
def offer_pdf(offer_id):
    conn = get_db()
    cur = conn.cursor()

    # Load offer
    cur.execute("SELECT * FROM offers WHERE id = ?", (offer_id,))
    offer = cur.fetchone()
    if not offer:
        conn.close()
        return "Offer not found", 404

    # Load items
    cur.execute("""
        SELECT *
        FROM offer_items
        WHERE offer_id = ?
        ORDER BY line_order, id
    """, (offer_id,))
    items = cur.fetchall()

    # ---- Build file:// URIs for product images ----
    items_for_pdf = []
    for row in items:
        d = dict(row)
        photo_name = d.get("item_photo_path")
        if photo_name:
            full_path = os.path.join(IMAGE_DIR, photo_name)
            if os.path.isfile(full_path):
                d["item_photo_uri"] = Path(full_path).as_uri()
            else:
                d["item_photo_uri"] = None
        else:
            d["item_photo_uri"] = None
        items_for_pdf.append(d)

    # ---- Template Selection ----
    preview_tpl_id = request.args.get("preview_template_id")
    active_tpl_id = 0
    
    if preview_tpl_id:
        active_tpl_id = int(preview_tpl_id)
    else:
        # Get active template from global_settings
        cur.execute("SELECT value FROM global_settings WHERE key = 'active_pdf_template_id';")
        row = cur.fetchone()
        active_tpl_id = int(row["value"]) if row else 0

    custom_tpl = None
    if active_tpl_id > 0:
        cur.execute("SELECT * FROM pdf_templates WHERE id = ?;", (active_tpl_id,))
        custom_tpl = cur.fetchone()

    cur.execute("SELECT value FROM global_settings WHERE key = 'language';")
    row = cur.fetchone()
    current_language = row["value"] if row else "en"

    conn.close()

    # ---- Logo URI ----
    logo_path = os.path.join(APP_ASSETS_DIR, "logo_company.jpg")
    logo_uri = Path(logo_path).as_uri()

    # ---- Footer Image URI ----
    rig_path = os.path.join(APP_ASSETS_DIR, "pdf_footer_image.png")
    rig_uri = Path(rig_path).as_uri()

    ctx = {
        "offer": offer,
        "items": items_for_pdf,
        "pdf_mode": True,
        "logo_uri": logo_uri,
        "rig_uri": rig_uri,
        "format_amount": globals().get('format_amount'), # Make sure these are available
        "format_date": globals().get('format_date'),
        "countries": get_country_list(),
        "current_language": current_language
    }
    # Actually these are already in app.jinja_env.globals if registered
    # but for render_template_string we might need to be explicit or it uses the current app context.

    # Fix for System Default template (render_template_string needs these explicitly if not global)
    ctx["current_date_format"] = get_date_format()
    # Dummy translation function if not present
    ctx["_"] = lambda x: x
    ctx["gettext"] = lambda x: x

    if custom_tpl:
        # Render parts from DB -- sandboxed Jinja (audit C4): DB-stored
        # templates only reach the explicit context plus the pinned globals
        # (url_for, _, gettext, format_amount, format_date) and the app's
        # filters; request/session/config internals are off limits. Output
        # for the seeded System Default template is byte-identical to the
        # previous render_template_string call.
        from flask import current_app

        from qp_crm.services.pdf_service import render_db_template_parts

        header_html, body_html, footer_html = render_db_template_parts(
            custom_tpl["header_html"], custom_tpl["body_html"], custom_tpl["footer_html"],
            ctx,
            app_filters=current_app.jinja_env.filters,
            url_for_func=url_for,
        )
        custom_css = custom_tpl["css"]
        
        # We still use a basic wrapper to position header/footer running elements
        html_string = f"""
        <!doctype html>
        <html>
        <head><meta charset="utf-8"></head>
        <body>
            <div class="pdf-footer">{footer_html}</div>
            <div class="pdf-header">{header_html}</div>
            <div class="page-content">{body_html}</div>
        </body>
        </html>
        """
        pdf_bytes = HTML(string=html_string).write_pdf(
            stylesheets=[CSS(string=custom_css)]
        )
    else:
        # Fallback to filesystem
        html_string = render_template(
            "offer/pdf_offer.html",
            **ctx
        )
        pdf_css_path = os.path.join(BASE_DIR, "static", "css", "pdf.css")
        pdf_bytes = HTML(string=html_string).write_pdf(
            stylesheets=[CSS(filename=pdf_css_path)]
        )

    num = offer["offer_number"] or offer["id"]
    filename = f"{num}.pdf"

    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename
    )
