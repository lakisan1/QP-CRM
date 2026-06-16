"""
import_templates.py
Seeds the rent_templates database table.

Priority order:
  1. If rent_templates is already populated → skip (idempotent).
  2. If rent_templates_defaults.json exists next to this file → seed from JSON.
  3. If .docx source files exist (legacy path) → convert and seed (kept for compatibility).
"""
import os
import sys
import json

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
JSON_DEFAULTS = os.path.join(HERE, "rent_templates_defaults.json")

# Legacy: original Word .docx files (may not exist on remote servers)
DOCX_DIR = os.path.join(os.path.dirname(HERE), "excell Rent calc", "word documents")

# ---------------------------------------------------------------------------
# Template metadata (used by docx fallback path only)
# ---------------------------------------------------------------------------
TEMPLATES = [
    ("Ugovor o zakupu opreme.docx",                    "ugovor-zakup",          "Ugovor o zakupu opreme"),
    ("Ugovor o zakupu opreme jemac.docx",              "ugovor-zakup-jemac",    "Ugovor o zakupu opreme (sa jemcem)"),
    ("Prilog 1 Zapisnik o primopredaji.docx",          "prilog-1-zapisnik",     "Prilog 1 – Zapisnik o primopredaji"),
    ("Prilog 2 Protokol o prihvatljivom stanju.docx",  "prilog-2-protokol",     "Prilog 2 – Protokol o prihvatljivom stanju"),
    ("Menicno ovlascenje Opcija 1.docx",               "menicno-ovlascenje",    "Meničko ovlašćenje"),
    ("Instrukcija za uplatu Avansa.docx",              "instrukcija-avans",     "Instrukcija za uplatu avansa"),
    ("Informacije za osiguranje.docx",                 "info-osiguranje",       "Informacije za osiguranje"),
    ("Zapisnik o Preuzimanju predmeta zakupa.docx",    "zapisnik-preuzimanje",  "Zapisnik o preuzimanju predmeta zakupa"),
]

# ---------------------------------------------------------------------------
# MERGEFIELD → Jinja2 variable map (used by docx fallback only)
# ---------------------------------------------------------------------------
FIELD_MAP = {
    "broj_ugovora":                        "contract_number",
    "datum_zaključenja_ugovora":           "contract_date",
    "datum_zakljucenja_ugovora":           "contract_date",
    "ime_firme":                           "client_name",
    "adresa_sedista":                      "client_address",
    "maticni_broj_firme":                  "client_mb",
    "maticni_broj":                        "client_mb",
    "pib_firme":                           "client_pib",
    "pib":                                 "client_pib",
    "broj_racuna_zakupca":                 "client_account",
    "broj_racuna":                         "client_account",
    "ime_i_prezime_potpisnika_ugovora":    "client_representative",
    "email_zakupca":                       "client_email",
    "e-mail_zakupca":                      "client_email",
    "adresa_zakupa":                       "rent_address",
    "jamac_ime_grad_jmbg_":               "guarantor",
    "jamac":                               "guarantor",
    "predmet_zakupa":                      "equipment_model",
    "oprema_model":                        "equipment_model",
    "cena_opreme":                         "price_fmt",
    "broj_meseci":                         "period_months",
    "rent":                                "rata_neto_fmt",
    "rentpdv":                             "rata_bruto_fmt",
    "ucesce":                              "ucesce_bruto_fmt",
    "ucescepdv":                           "ucesce_pdv_fmt",
    "zatvaranje_avansa":                   "zatvaranje_fmt",
    "ostatak_vrednosti":                   "ostatak_fmt",
    "osiguranje":                          "osiguranje_fmt",
    "garancija":                           "garancija_fmt",
}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def seed_templates(conn):
    """
    Called during init_db.  Idempotent – skips if table already has rows.
    Tries JSON defaults first, then legacy .docx conversion.
    """
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM rent_templates;")
    if cur.fetchone()[0] > 0:
        return  # Already seeded – nothing to do

    # ── Path 1: JSON defaults (preferred, always available on remote) ──
    if os.path.exists(JSON_DEFAULTS):
        print("[import_templates] Seeding from rent_templates_defaults.json ...")
        with open(JSON_DEFAULTS, encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            cur.execute(
                "INSERT INTO rent_templates (slug, name, content_html) VALUES (?, ?, ?);",
                (entry["slug"], entry["name"], entry["content_html"]),
            )
            print(f"[import_templates] Seeded: {entry['name']}")
        conn.commit()
        return

    # ── Path 2: Legacy .docx conversion (only if source files present) ──
    _seed_from_docx(cur, conn)


# ---------------------------------------------------------------------------
# Legacy .docx conversion (kept for compatibility)
# ---------------------------------------------------------------------------

def _seed_from_docx(cur, conn):
    """Convert Word .docx files to HTML and seed the database."""
    try:
        import zipfile
        import xml.etree.ElementTree as ET
        import mammoth
    except ImportError:
        print("[import_templates] mammoth not installed – skipping docx seed.")
        return

    NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def _resolve_field(raw_name):
        key = raw_name.strip('"«» ').lower()
        return FIELD_MAP.get(key, key)

    def _clean_xml_fields(xml_bytes):
        for prefix, uri in [
            ('w',   NS_W),
            ('r',   'http://schemas.openxmlformats.org/officeDocument/2006/relationships'),
            ('w14', 'http://schemas.microsoft.com/office/word/2010/wordml'),
            ('mc',  'http://schemas.openxmlformats.org/markup-compatibility/2006'),
        ]:
            ET.register_namespace(prefix, uri)

        root = ET.fromstring(xml_bytes)
        for para in root.iter(f'{{{NS_W}}}p'):
            children = list(para)
            new_children = []
            i = 0
            while i < len(children):
                child = children[i]
                is_begin = False
                if child.tag == f'{{{NS_W}}}r':
                    fc = child.find(f'{{{NS_W}}}fldChar')
                    if fc is not None and fc.get(f'{{{NS_W}}}fldCharType') == 'begin':
                        is_begin = True
                if is_begin:
                    field_var = None
                    end_idx = -1
                    for j in range(i + 1, len(children)):
                        sib = children[j]
                        if sib.tag != f'{{{NS_W}}}r':
                            continue
                        instr = sib.find(f'{{{NS_W}}}instrText')
                        if instr is not None and instr.text:
                            txt = instr.text.strip()
                            if txt.upper().startswith('MERGEFIELD'):
                                parts = txt.split(None, 2)
                                if len(parts) > 1:
                                    field_var = '{{ ' + _resolve_field(parts[1]) + ' }}'
                            elif txt.upper().startswith('DATE'):
                                field_var = '{{ contract_date }}'
                        fc = sib.find(f'{{{NS_W}}}fldChar')
                        if fc is not None and fc.get(f'{{{NS_W}}}fldCharType') == 'end':
                            end_idx = j
                            break
                    if field_var and end_idx != -1:
                        r_new = ET.Element(f'{{{NS_W}}}r')
                        rpr = child.find(f'{{{NS_W}}}rPr')
                        if rpr is not None:
                            r_new.append(rpr)
                        t = ET.SubElement(r_new, f'{{{NS_W}}}t')
                        t.text = field_var
                        new_children.append(r_new)
                        i = end_idx + 1
                        continue
                new_children.append(child)
                i += 1
            for c in list(para):
                para.remove(c)
            for c in new_children:
                para.append(c)
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)

    def _docx_to_html(docx_path):
        import io as _io
        with zipfile.ZipFile(docx_path, 'r') as z_in:
            doc_xml = z_in.read('word/document.xml')
            patched_xml = _clean_xml_fields(doc_xml)
            buf = _io.BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z_out:
                for item in z_in.infolist():
                    if item.filename == 'word/document.xml':
                        z_out.writestr(item, patched_xml)
                    else:
                        z_out.writestr(item, z_in.read(item.filename))
            buf.seek(0)
        result = mammoth.convert_to_html(buf)
        return result.value

    print("[import_templates] JSON defaults not found – trying .docx conversion ...")
    for filename, slug, display_name in TEMPLATES:
        docx_path = os.path.join(DOCX_DIR, filename)
        if not os.path.exists(docx_path):
            print(f"[import_templates] WARNING: {filename} not found, skipping.")
            continue
        try:
            html = _docx_to_html(docx_path)
            cur.execute(
                "INSERT INTO rent_templates (slug, name, content_html) VALUES (?, ?, ?);",
                (slug, display_name, html),
            )
            print(f"[import_templates] Imported: {display_name}")
        except Exception as e:
            print(f"[import_templates] ERROR importing {filename}: {e}")
    conn.commit()
