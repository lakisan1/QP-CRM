"""Rent master template editor routes (admin)."""

from flask import render_template, request, redirect, url_for, session

from ..app import bp, get_db, sort_rent_templates

# ─────────────────────────────────────────────────────────────────────────────
# Rent Master Template Editor (Admin)
# ─────────────────────────────────────────────────────────────────────────────

# Preferred display order + sorter live in shared/web.py (same list the rent
# module uses).

@bp.route("/rent/templates")
def admin_rent_templates():
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin.login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, slug, name FROM rent_templates ORDER BY id;")
    templates = sort_rent_templates(cur.fetchall())
    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_preset';")
    row = cur.fetchone()
    rent_email_preset = row["value"] if row else (
        "Poštovani,\n\n"
        "U prilogu Vam dostavljamo sva dokumenta vezana za zakup opreme.\n\n"
        "Ukoliko ste saglasni, molimo Vas da to potvrdite emailom, kako bismo Vam "
        "poštom poslali potpisane primerke ugovora koje nam na dan ugradnje opreme "
        "vraćate sa Vašim potpisom. Svaki prilog ide u 4 primerka \u2013 2 za Vas i 2 za nas.\n\n"
        "Molimo Vas da popunite i meničko ovlašćenje.\n\n"
        "Uplatu avansa izvršite na osnovu Instrukcija za uplatu avansa, "
        "a nakon toga pratite Plan plaćanja.\n\n"
        "Srdačan pozdrav,\nMarinković-Hofmann d.o.o."
    )
    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_subject';")
    subj_row = cur.fetchone()
    rent_email_subject = subj_row["value"] if subj_row else "Ugovor i prilozi za zakup opreme - {{ contract_number }} - {{ client_name }}"
    conn.close()
    return render_template("admin/admin_rent_templates.html", templates=templates, selected=None, msg=None,
                           rent_email_preset=rent_email_preset,
                           rent_email_subject=rent_email_subject)


@bp.route("/rent/templates/<slug>", methods=["GET", "POST"])
def admin_rent_template_edit(slug):
    if not session.get("admin_authenticated"):
        return redirect(url_for("admin.login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, slug, name FROM rent_templates ORDER BY id;")
    templates = sort_rent_templates(cur.fetchall())

    cur.execute("SELECT * FROM rent_templates WHERE slug=?;", (slug,))
    selected = cur.fetchone()
    if not selected:
        conn.close()
        return "Šablon nije pronađen", 404

    msg = None
    if request.method == "POST":
        new_html = request.form.get("content_html", "")
        cur.execute("UPDATE rent_templates SET content_html=? WHERE slug=?;", (new_html, slug))
        conn.commit()
        msg = "✓ Šablon je uspešno sačuvan."
        # Re-fetch updated
        cur.execute("SELECT * FROM rent_templates WHERE slug=?;", (slug,))
        selected = cur.fetchone()

    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_preset';")
    ep_row = cur.fetchone()
    rent_email_preset = ep_row["value"] if ep_row else (
        "Poštovani,\n\n"
        "U prilogu Vam dostavljamo sva dokumenta vezana za zakup opreme.\n\n"
        "Ukoliko ste saglasni, molimo Vas da to potvrdite emailom, kako bismo Vam "
        "poštom poslali potpisane primerke ugovora koje nam na dan ugradnje opreme "
        "vraćate sa Vašim potpisom. Svaki prilog ide u 4 primerka \u2013 2 za Vas i 2 za nas.\n\n"
        "Molimo Vas da popunite i meničko ovlašćenje.\n\n"
        "Uplatu avansa izvršite na osnovu Instrukcija za uplatu avansa, "
        "a nakon toga pratite Plan plaćanja.\n\n"
        "Srdačan pozdrav,\nMarinković-Hofmann d.o.o."
    )

    cur.execute("SELECT value FROM global_settings WHERE key='rent_email_subject';")
    subj_row2 = cur.fetchone()
    rent_email_subject = subj_row2["value"] if subj_row2 else "Ugovor i prilozi za zakup opreme - {{ contract_number }} - {{ client_name }}"

    conn.close()
    return render_template("admin/admin_rent_templates.html",
                           templates=templates,
                           selected=selected,
                           msg=msg,
                           rent_email_preset=rent_email_preset,
                           rent_email_subject=rent_email_subject)
