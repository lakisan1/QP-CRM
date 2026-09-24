"""Import musterije_kontakti_2024_2026.csv into the QP-CRM shared directory.

Source: export of the 2024-2026 customer contact list (2181 rows, ; separated,
columns: naziv;pib;mb;adresa;grad;telefon;email;šifra banke).

Core user requirement: ONE customer = ONE contact. The same customer seen in
several rows (repeat customers across the years, empty duplicate rows) must
NOT become several contacts. Multiple DISTINCT addresses of one customer
become contact_locations (sites) -- not extra contacts.

Identity keys (match priority):
  1. PIB  -- 9-digit Serbian tax id, THE identity for legal entities.
  2. MB   -- 8-digit Serbian registry number (BIH entities carry JIB here).
  3. normalized display name -- casefold + diacritics-folded + whitespace
     squeezed; covers person rows and rows with no tax id.

Field mapping (after cleaning):
  naziv          -> display_name (with 'Kupac: X Adresa: Y' parsing, bare-email
                    and junk-name repair), junk overflow goes to notes
  pib/mb         -> pib/mb (JIB lines relocated to mb; PIB/MB 9/8-digit swaps
                    corrected)
  adresa/grad    -> billing_address/city, with the export's well-known column
                    slips repaired (street in grad, city in adresa, phone/
                    email/jmbg/ID markers in either column)
  telefon        -> phone (plus phone rescued from other columns)
  email          -> email (plus email rescued from other columns)
  šifra banke    -> notes 'Šifra klijenta: X' (it is the client code registry,
                    NOT a bank account number)
  country        -> Srbija (default) / BiH (JIB or BIH city) / Crna Gora

kind: company when legal-form tokens (doo, ad, sztr, pr, radnja, ...) or any
tax id are present; otherwise person (first/last name split, JMBG when the
'jmbg' marker appears in a column).

Location extraction per contact: distinct (address, city) pairs from the
matched rows; the billing row itself is NOT duplicated as a location when it
is the only pair. Locations get name = city (or 'Lokacija N').

Every decision is logged; a skip report lists rows that could not be safely
imported (corrupt rows). Run with --dry-run first; --apply writes the DB.
"""
import argparse
import csv
import re
import sys
import unicodedata
from collections import defaultdict

sys.path.insert(0, "/home/dsh/QP-CRM")

CSV_PATH = "/home/dsh/QP-CRM/app_data/imports/musterije.csv"

CITY_TOKENS = {
    # derived from the export itself (grad values appearing >= 5 times) plus
    # obvious region names seen in the data
    "beograd", "novi beograd", "novi sad", "zemun", "novo sarajevo",
    "nis", "niš", "kragujevac", "cacak", "čačak", "subotica", "pančevo",
    "pancevo", "sombor", "kraljevo", "krusevac", "kruševac", "leskovac",
    "uzice", "užice", "vranje", "smederevo", "valjevo", "loznica", "pirot",
    "zrenjanin", "kikinda", "sremska mitrovica", "stara pazova", "sabac",
    "šabac", "pozarevac", "požarevac", "jagodina", "gornji milanovac",
    "novi pazar", "priboj", "prijepolje", "prokuplje", "mladenovac",
    "lazarevac", "obrenovac", "paracin", "paraćin", "zajecar", "zaječar",
    "kula", "ruma", "indjija", "inđija", "temerin", "vrbas", "bor", "veternik",
    "futog", "borca", "borča", "surcin", "surčin", "kaludjerica",
    "kaluđerica", "zemun polje", "voganj", "okletac", "prislonica", "ljubic",
    "ljubić", "gruza", "poljna", "stajkovce", "stubica",
    "donja mutnica", "trstenik", "ljig", "guca", "guča", "tutin", "ostruznica",
    "ostružnica", "leštane", "lestane", "velika plana", "svilajnac",
    "despotovac", "srbobran", "velika mostanica",
    "bogatic", "bogatić", "presevo", "preševo", "merosina", "merošina",
    "koceljeva", "mionica", "surdulica", "dimitrovgrad", "belo polje",
    "postenje", "postenje bb", "banja luka", "sarajevo", "prijedor",
    "brcko", "brčko", "bijeljina", "dobo", "trebinje", "tuzla", "zenica",
    "mostar", "bih", "podgorica", "crna gora", "bar", "kotor", "budva",
    "niksic", "nikšić", "pristina", "priština", "kosovska mitrovica",
    "lesak", "lešak", "zubin potok", "gracanica",
    "gračanica", "lapovo", "varošica", "racovica", "rakovica", "vojvodina",
    "cetinje", "herceg novi", "vrelo", "krupanj", "golubac", "vodanj",
    "snegotin", "pilica", "zaguzanje", "zaguljanje", "stubline",
    "becmen", "becej", "bečej", "apatin", "backa topola",
    "bačka topola", "ada", "mol", "senta",
    "preljina", "kosjerić", "kosjeric", "nova pazova", "baric", "barič",
    "kanjiza", "kanjiža", "zvecan", "zvečan", "pukovac", "odzaci", "odžaci",
    "backa palanka", "bačka palanka", "stari banovci", "nova varoš",
    "nova varos", "bela palanka", "donja vrežina",
    "macvanski prnjavor", "mačvanski prnjavor", "novi zednik", "novi bečej",
    "novi becej", "petrovac na mlavi", "petrovac",
    "arandjelovac", "aranđelovac", "bajina basta", "bajina bašta",
    "salaš noćajski", "salas nocajski", "pas poljana", "pasi poljana",
    "vinoraca", "vinorača", "simanovce", "belo polje", "donje rataje",
    "iskovo", "guncati", "trstenik", "celarevo", "čelarevo", "zlata",
}

LEGAL_TOKENS = re.compile(
    r"(?i)\b(doo|d\.o\.o\.?|do\.?o\.?|ad\b|a\.d\.?|sztr|szc\b|giz\b|jkp\b|jp\b|"
    r"zadruga|društvo|drustvo|radnja|preduzeće|predreeze|predusece|sh\.?p\.?k|"
    r"shpk|d\.d\.|dd\b|jib\b|bre\b|centar\b|servis\b|auto\b|autocentar|t\.?i\.?m\b)",
)


def clean(s):
    return " ".join((s or "").split()).strip()


def fold(s):
    """casefold + strip diacritics, whitespace squeezed -- match key."""
    s = " ".join((s or "").split()).casefold()
    s = "".join(c for c in unicodedata.normalize("NFD", s)
                if unicodedata.category(c) != "Mn")
    return s


def is_email(s):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", s))


PHONE_RE = re.compile(r"(?<![\d/])(\+?\d[\d\s/\-]{5,}\d)(?![\d/])")


def extract_phone(s):
    """Pull a plausible phone out of a column; returns (phone, rest)."""
    s = s.strip()
    if not s:
        return None, s
    m = re.match(r"(?i)^tel:\s*", s)
    if m:
        s = s[m.end():].strip()
    hit = PHONE_RE.search(s)
    if not hit:
        return None, s
    phone = clean(hit.group(1))
    rest = clean(s[:hit.start()] + " " + s[hit.end():])
    return phone, rest


def looks_person_name(s):
    """2-4 capitalized words, no digits/commas -> likely a person's name."""
    if not s or re.search(r"\d", s) or "," in s or re.search(r"(?i)\bbb\b|b\.b", s):
        return False
    words = s.split()
    if not (1 < len(words) <= 4):
        return False
    if not all(re.fullmatch(r"[A-Za-zČĆŠĐŽčćšđž\-'.()]+", w) for w in words):
        return False
    return not LEGAL_TOKENS.search(s)


def looks_city(s):
    if not s or re.search(r"\d", s):
        return False
    key = fold(s)
    if key in CITY_TOKENS:
        return True
    # 'Novi Sad' style 2-word cities already in set; single word w/ 'bb' no
    return False


def looks_street(s):
    return bool(re.search(r"\d", s)) or bool(re.search(r"(?i)\bb\b|\bbb\b", s)) and not is_email(s)


def fix_pib_mb(pib, mb):
    """Export swapped the columns on 8 rows (8-digit in pib, 9-digit in mb);
    normalize so pib carries the 9-digit and mb the 8-digit id."""
    if pib and not mb and re.fullmatch(r"\d{8}", pib):
        pib, mb = None, pib
    if mb and not pib and re.fullmatch(r"\d{9}", mb):
        pib, mb = mb, None
    if pib and re.fullmatch(r"\d{8}", pib) and mb and re.fullmatch(r"\d{9}", mb):
        pib, mb = mb, pib
    return pib or None, mb or None


def split_grad(grad):
    """grad may hold 'street, city' (street part has digits)."""
    if "," in grad:
        head, tail = grad.split(",", 1)
        if re.search(r"\d", head):
            return clean(head), clean(tail)
    return None, grad


def normalize_city(city):
    """Strip trailing 'Srbija' / 'Srbija, XX' decorations and leading postal."""
    city = clean(city)
    city = re.sub(r"(?i)\s*,?\s*srbija\s*$", "", city)
    city = re.sub(r"(?i)\s*,?\s*serbia\s*$", "", city)
    city = re.sub(r"(?i)\s*,?\s*bih\s*$", "", city)
    m = re.match(r"^(\d{5})\s+(.+)$", city)
    if m:
        city = m.group(2)
    return clean(city)


def parse_row(r, log):
    """Clean one raw export row -> normalized dict + list of notes."""
    notes = []
    naziv = clean(r.get("naziv"))
    pib, mb = clean(r.get("pib")), clean(r.get("mb"))
    adr, grad = clean(r.get("adresa")), clean(r.get("grad"))
    tel, email = clean(r.get("telefon")), clean(r.get("email"))
    code = clean(r.get("šifra banke"))

    # -- name repair ------------------------------------------------------
    naziv_adr = None
    if naziv.startswith("Kupac:"):
        m = re.match(r"Kupac:\s*(.+?)\s+Adresa:\s*(.+)$", naziv, re.S)
        if m:
            naziv, naziv_adr = m.group(1).strip(), m.group(2).strip()
            log["name.kupac_parsed"] += 1
    if is_email(naziv):
        local = naziv.split("@")[0]
        name_guess = local.replace(".", " ").replace("_", " ").replace("-", " ")
        name_guess = " ".join(w.capitalize() for w in name_guess.split())
        notes.append(f"eMail (identitet): {naziv}")
        email = email or naziv
        naziv = name_guess or naziv
        log["name.from_email"] += 1
    elif naziv.lower().startswith("jib"):
        notes.append(f"JIB u nazivu: {naziv}")
        digits = re.sub(r"\D", "", naziv)
        if digits and not mb:
            mb = digits
        # 'JIB' rows: the email local-part is the only name source
        if is_email(email):
            local = email.split("@")[0]
            naziv = " ".join(w.capitalize() for w in
                             re.split(r"[._\-]", local) if w)
        else:
            naziv = ""
        log["name.from_jib"] += 1
    elif naziv in ("0", "-", ".", ","):
        notes.append(f"Naziv kolona: {naziv!r}")
        naziv = ""
        log["name.junk"] += 1
    # junk name but a company name sits in adresa -> promote it
    if not naziv and adr and LEGAL_TOKENS.search(adr) and not re.search(r"\d", adr) \
            and not is_email(adr):
        naziv = adr
        adr = ""
        log["name.from_adresa"] += 1
    if naziv_adr:
        notes.append(f"Adresa iz naziva: {naziv_adr}")

    # -- phone/email/jmbg/jib rescued from adresa/grad --------------------
    for colname, val in (("adresa", adr), ("grad", grad)):
        if not val:
            continue
        if is_email(val):
            if email and email != val:
                email = f"{email}; {val}"
            else:
                email = email or val
            setattr_col = "adresa" if val == adr else "grad"
            log[f"email rescued from {setattr_col}"] += 1
            if val == adr:
                adr = ""
            else:
                grad = ""
            continue
        low = val.lower()
        if low.startswith("jmbg"):
            jmbg_digits = re.sub(r"\D", "", val)
            if jmbg_digits:
                notes.append(f"JMBG: {jmbg_digits}")
            log["jmbg extracted"] += 1
            if val == adr:
                adr = ""
            else:
                grad = ""
            continue
        if low.startswith("jib") or (val == naziv and low.startswith("jib")):
            digits = re.sub(r"\D", "", val)
            if digits and not mb:
                mb = digits
                notes.append(f"JIB (BIH): {digits}")
            log["jib extracted"] += 1
            if val == adr:
                adr = ""
            else:
                grad = ""
            continue
        if low.startswith("br.lk") or low.startswith("maticni broj"):
            digits = re.sub(r"\D", "", val)
            notes.append(f"{val}")
            log["id-marker noted"] += 1
            if val == adr:
                adr = ""
            else:
                grad = ""
            continue
        m = re.match(r"(?i)^tel:?\s*(.+)$", val)
        if m:
            got = clean(m.group(1))
            if is_email(got):
                email = email or got
            elif got:
                tel = f"{tel} / {got}" if tel and got not in tel else tel or got
            log[f"tel rescued from {colname}"] += 1
            if val == adr:
                adr = ""
            else:
                grad = ""
            continue
        # grad 'phone + person/city' family ('065/924-2224 Goran Dabic',
        # 'Kanjiza' in adresa): phone lands in tel, the rest stays in grad
        # for the person/city handling below -- even when adr is a city.
        if colname == "grad" and re.search(r"(?i)\d{2,3}[\s/]\d{3}", val):
            got, rest = extract_phone(val)
            if got:
                if not tel or got not in tel:
                    tel = f"{tel} / {got}" if tel else got
                grad = rest
                log["phone from grad"] += 1

    # merge rescued phones: drop a truncated duplicate (one is a prefix of
    # the other, e.g. '060/8696' vs '060/8696-825') -- keep the LONGER one;
    # same digits with different formatting is also one number
    parts = [clean(p) for p in tel.split(" / ") if p.strip()] if tel else []
    if len(parts) == 2:
        a, b = (re.sub(r"\D", "", p) for p in parts)
        if a == b or a.startswith(b) or b.startswith(a):
            tel = parts[0] if len(parts[0]) >= len(parts[1]) else parts[1]
            log["truncated phone dropped"] += 1
        else:
            tel = " / ".join(parts)
    elif tel:
        tel = " / ".join(parts)

    # -- adresa / grad disambiguation -------------------------------------
    # grad may still hold 'phone + rest' leftovers from the rescue loop
    if grad and re.search(r"(?i)^\d{2,3}[\s/]\d{3}", grad) and not looks_city(grad):
        got, rest = extract_phone(grad)
        if got:
            if not tel or got not in tel:
                tel = f"{tel} / {got}" if tel else got
            grad = rest
            log["phone from grad"] += 1
    # 'street, city' smuggled into grad
    street_part, city_part = split_grad(grad)
    if street_part:
        adr = street_part if not adr or looks_city(adr) else adr
        grad = city_part
        log["grad street,city split"] += 1
    # bare street smuggled into grad (digits, no comma) while adr is empty
    # or a city -> grad is the street
    elif grad and re.search(r"\d", grad) and (not adr or looks_city(adr)) \
            and not looks_city(grad):
        if not adr or looks_city(adr):
            if adr:
                grad, adr = adr, grad  # keep the city for the city slot
                log["swap city-in-adr"] += 1
            else:
                adr = grad
                grad = ""
            log["grad street moved to adr"] += 1
    if naziv_adr and not adr:
        # 'Kupac: X Adresa: Y' rows: naziv_adr is a full informal address
        m = re.match(r"^(.+?),\s*(\d{5})\s*$", naziv_adr)
        if m:
            adr = m.group(1)
        elif "," in naziv_adr:
            head, tail = naziv_adr.split(",", 1)
            adr = head.strip()
            if not grad and tail.strip():
                grad = tail.strip()
        else:
            adr = naziv_adr
        log["adr from naziv"] += 1

    # adr is a city, grad holds the street -> swap
    if adr and looks_city(adr) and grad and looks_street(grad) and not looks_city(grad):
        adr, grad = grad, adr
        log["swap city-in-adr"] += 1
    # adr is a city, grad empty -> grad becomes the city
    if adr and not grad and looks_city(adr):
        adr, grad = "", adr
        log["adr city to grad"] += 1

    # adr is a company name duplicated from naziv or a leaser/lender name ->
    # grad holds the real street -> adr=grad, drop adr into notes
    if adr and grad and re.search(r"\d", grad) and not re.search(r"\d", adr) \
            and not looks_city(grad) and (LEGAL_TOKENS.search(adr) or looks_person_name(adr)):
        notes.append(f"Podatak iz kolone adresa: {adr}")
        adr = grad
        grad = ""
        log["adr company name replaced"] += 1

    # adr is a pure company-name fragment while grad is the city
    if adr and grad and looks_city(grad) and LEGAL_TOKENS.search(adr) \
            and not re.search(r"\d", adr) and not looks_street(adr):
        notes.append(f"Podatak iz kolone adresa: {adr}")
        adr = ""
        log["adr company fragment dropped"] += 1

    # both columns hold name-like fragments of the display name (long names
    # wrapped across columns) -- neither is an address
    if adr and grad and not re.search(r"\d", adr + grad) and not looks_city(adr) \
            and not looks_city(grad) and not is_email(adr) and not is_email(grad) \
            and (LEGAL_TOKENS.search(adr) and LEGAL_TOKENS.search(grad)
                 or (fold(adr) in fold(naziv + " " + grad)
                     and fold(grad) in fold(naziv + " " + adr))):
        notes.append(f"Podatak iz kolone adresa: {adr}")
        notes.append(f"Podatak iz kolone grad: {grad}")
        adr = grad = ""
        log["name fragments noted"] += 1

    # grad holds a street with 'bb'/'b.b' marker while adr is empty -> street
    if grad and not adr and re.search(r"(?i)\b(b\.?b\.?|bb)\b", grad):
        adr = grad
        grad = ""
        log["grad bb street to adr"] += 1

    # grad holds a person's name while adr is the city -> contact person
    if grad and looks_person_name(grad) and not looks_city(grad) \
            and (looks_city(adr) or not adr):
        contact_person = grad
        notes.append(f"Kontakt osoba: {contact_person}")
        grad = adr if looks_city(adr) else ""
        adr = ""
        log["contact person from grad"] += 1

    # junk '/ /'-style address cells
    if adr and re.fullmatch(r"[\s/]+", adr):
        adr = ""
        log["adr junk stripped"] += 1

    # registry-id lines in adresa: BM/LK/OIB/JMBG/EMBS/company-number -> notes
    if adr and re.match(r"(?i)^(BM|LK|OIB|JMBG|EMBS|company number|bussiness nr|business nr)\b", adr):
        notes.append(f"ID: {adr}")
        adr = ""
        log["adr id line"] += 1

    # labeled cells: 'phone: ...' / 'address: ...'
    m = re.match(r"(?i)^phone:\s*(.+)$", adr or "")
    if m:
        tel = f"{tel} / {clean(m.group(1))}" if tel else clean(m.group(1))
        adr = ""
        log["labeled phone"] += 1
    m = re.match(r"(?i)^address:\s*(.+)$", grad or "")
    if m:
        grad = clean(m.group(1))
        log["labeled address"] += 1

    # postal glued to city in grad ('Zemun 11283', '11 232 Ripanj',
    # '1Valjevo', '212003 VETERNIK') -> keep only the alpha part. A real
    # street keeps its house number; strip only when a 3-6 digit postal
    # block is present AND the alpha remainder is short/city-like.
    if grad and re.search(r"\d{3,6}", grad):
        alpha = re.sub(r"\b\d+\b", "", grad).strip().lstrip(",").strip()
        m = re.match(r"^[,\s]*(\d+)([A-Za-zČĆŠĐŽčćšđž].*)$", grad)
        if m and not re.search(r"\d", m.group(2)):
            alpha = clean(m.group(2))
        words = alpha.split() if alpha else []
        if alpha and not re.search(r"\d", alpha) and len(words) <= 3:
            grad = clean(alpha)
            log["grad postal stripped"] += 1

    # city slot holds a street while adr holds nothing/city -> adr=street
    if grad and not looks_city(grad) and re.search(r"\d", grad) and not adr \
            and not is_email(grad):
        adr = grad
        grad = ""
        log["final street to adr"] += 1

    # city slot holds a street while adr holds a city/postal-city -> swap
    if adr and grad and not looks_city(grad) and re.search(r"\d", grad) \
            and (looks_city(adr) or re.fullmatch(r"\d{5}\s+\S.*", adr)):
        adr, grad = grad, adr
        log["final swap adr-grad"] += 1

    # city slot holds a 'str.-prefixed' street while adr holds a city -> swap
    if grad and re.match(r"(?i)^str\.?\s*", grad) and adr and not re.search(r"\d", adr):
        adr, grad = grad, adr
        log["final swap str-prefix"] += 1

    # digits glued to a word ('1Valjevo')
    m = re.match(r"^\d+([A-Za-zČĆŠĐŽčćšđž].*)$", grad or "")
    if m and not re.search(r"\d", m.group(1)) and not looks_street(m.group(1)):
        grad = clean(m.group(1))
        log["grad glued postal stripped"] += 1

    # grad is name-like junk while adr is a clean city -> keep city, note junk
    if adr and grad and looks_city(adr) and not looks_city(grad) \
            and not re.search(r"\d", grad) and not looks_person_name(grad):
        notes.append(f"Podatak iz kolone grad: {grad}")
        grad = adr
        adr = ""
        log["grad junk noted"] += 1

    city = normalize_city(grad) if grad else ""
    address = adr

    # postal prefix stripped from city already; single place
    if re.fullmatch(r"\d{5}\s+\S.*", address) and not city:
        city = address.split(" ", 1)[1]
        address = ""
    pib, mb = fix_pib_mb(pib, mb)

    if code:
        notes.append(f"Šifra klijenta: {code}")

    return {
        "row": int(r.get("_row", -1)),
        "name": naziv,
        "pib": pib or "",
        "mb": mb or "",
        "address": address,
        "city": city,
        "phone": tel,
        "email": email,
        "notes": notes,
        "jmbg": "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--csv", default=CSV_PATH)
    args = ap.parse_args()

    with open(args.csv, encoding="utf-8-sig") as f:
        raw = list(csv.DictReader(f, delimiter=";"))
    for i, r in enumerate(raw):
        r["_row"] = i

    log = defaultdict(int)
    parsed = [parse_row(r, log) for r in raw]

    print("=== cleaning log ===")
    for k in sorted(log):
        print(f"  {k:40} {log[k]}")

    # group into contacts
    # Key = PIB when present, else MB, else name. Two-phase: after PIB/MB
    # grouping, MB-groups whose names are similar (containment after fold)
    # collapse into one contact; MB-groups with unrelated names (a shared
    # registry number entered on two different companies -- source error)
    # stay separate so a wrong identity never swallows a real customer.
    groups = defaultdict(list)
    for p in parsed:
        key = None
        if p["pib"]:
            key = ("pib", p["pib"])
        elif p["mb"]:
            key = ("mb", p["mb"])
        else:
            key = ("name", fold(p["name"]))
        groups[key].append(p)

    def similar(n1, n2):
        f1, f2 = fold(n1), fold(n2)
        return bool(f1) and bool(f2) and (f1 in f2 or f2 in f1)

    # MB-collapse pass: rows may sit in different groups (different PIBs --
    # often a typo) yet share one registry number; when their names are
    # similar they are the same party. Unrelated names sharing an MB (source
    # error) stay separate so a wrong identity never swallows a customer.
    key_of = {}
    for key, items in groups.items():
        for i in items:
            key_of[i["row"]] = key
    mb_index = defaultdict(set)
    for key, items in groups.items():
        for i in items:
            if i["mb"]:
                mb_index[i["mb"]].add(key)
    for mb, keys in list(mb_index.items()):
        if len(keys) < 2:
            continue
        keys = sorted(keys, key=lambda k: min(i["row"] for i in groups[k]))
        base = keys[0]
        for other in keys[1:]:
            if other not in groups or base not in groups:
                continue
            names_b = [i["name"] for i in groups[base] if i["name"]]
            names_o = [i["name"] for i in groups[other] if i["name"]]
            if names_b and names_o and (
                    any(similar(a, b) for a in names_b for b in names_o)):
                groups[base].extend(groups.pop(other))
                for i in groups[base]:
                    key_of[i["row"]] = base

    print(f"\nrows: {len(parsed)}, groups: {len(groups)}")

    # resolve mb-keyed groups that are actually different names
    conflicts = []
    for key, items in sorted(groups.items(), key=lambda kv: kv[1][0]["row"]):
        names = {fold(i["name"]) for i in items}
        if len(names) > 1:
            conflicts.append((key, items))
    print(f"groups with multiple distinct names: {len(conflicts)}")
    for key, items in conflicts:
        print(f"  {key}: {[(i['row'], i['name'][:40]) for i in items]}")

    if args.dry_run:
        print("\n=== DRY RUN sample of first 25 contacts ===")
        for key, items in sorted(groups.items(), key=lambda kv: kv[1][0]["row"])[:25]:
            p0 = items[0]
            print(f"[rows {sorted(i['row'] for i in items)}] {p0['name'][:50]!r}")
            print(f"    pib={p0['pib']!r} mb={p0['mb']!r} city={p0['city']!r}")
            print(f"    adr={p0['address']!r} tel={p0['phone']!r} email={p0['email']!r}")
            if p0["notes"]:
                print(f"    notes={p0['notes']}")
        return

    if not args.apply:
        print("nothing to do (no --apply)")
        return

    from qp_crm.shared.db import get_db
    conn = get_db()
    cur = conn.cursor()

    # identity indexes over ACTIVE directory contacts (existing rows first --
    # import LINKS to them instead of duplicating)
    cur.execute("SELECT id, display_name, pib, mb FROM contacts WHERE archived = 0;")
    by_pib, by_mb, by_name = {}, {}, {}
    for row in cur.fetchall():
        if row["pib"] and row["pib"].strip():
            by_pib.setdefault(row["pib"].strip(), row["id"])
        if row["mb"] and row["mb"].strip():
            by_mb.setdefault(row["mb"].strip(), row["id"])
        by_name.setdefault(fold(row["display_name"]), row["id"])

    def link_for(key, names):
        """Existing contact id matching the import-group key, or None.

        mb-keyed groups fall back to the name index (a pre-existing contact
        may hold the same name with no registry number); likewise pib-keyed.
        """
        kind, val = key
        if kind == "pib":
            hit = by_pib.get(val)
            if hit is not None:
                return hit
            for n in names:
                hit = by_name.get(fold(n))
                if hit is not None:
                    return hit
            return None
        if kind == "mb":
            hit = by_mb.get(val)
            if hit is not None:
                return hit
            for n in names:
                hit = by_name.get(fold(n))
                if hit is not None:
                    return hit
            return None
        return by_name.get(val)

    created, linked, skipped = 0, 0, 0
    for key, items in sorted(groups.items(), key=lambda kv: kv[1][0]["row"]):
        # master row: legal-form name wins (a person's email-derived name
        # must not shadow the company), then field richness
        def master_rank(p):
            return (1 if LEGAL_TOKENS.search(p["name"]) else 0,
                    richness(p))
        items = sorted(items, key=master_rank, reverse=True)
        p0 = items[0]
        if not p0["name"]:
            skipped += 1
            continue
        kind = "company" if LEGAL_TOKENS.search(p0["name"]) or p0["pib"] or p0["mb"] else "person"
        # merged name-variant rows: shorter non-legal names become a note
        notes = list(p0["notes"])
        for i in items[1:]:
            if i["name"] and fold(i["name"]) != fold(p0["name"]):
                notes.append(f"Ostali nazivi u izvoru: {i['name']}")
        jmbg = ""
        for i in items:
            for n in i["notes"]:
                if n.startswith("JMBG: "):
                    jmbg = n.split(": ", 1)[1]
        # merge phones/emails across rows (prefix-dedupe)
        phones, emails = [], []
        for i in items:
            for ph in (i["phone"] or "").split(" / "):
                if ph and not any(ph.replace("/", "").replace("-", "").startswith(
                        e.replace("/", "").replace("-", ""))
                        or e.replace("/", "").replace("-", "").startswith(
                            ph.replace("/", "").replace("-", ""))
                        for e in phones):
                    phones.append(ph)
            for em in (i["email"] or "").split(";"):
                em = em.strip()
                if em and em not in emails:
                    emails.append(em)

        fields = {
            "pib": p0["pib"], "mb": p0["mb"],
            "billing_address": p0["address"], "city": p0["city"],
            "country": "BiH" if (p0["mb"] and len(p0["mb"]) > 8) else "Srbija",
            "email": "; ".join(emails), "phone": " / ".join(phones),
            "notes": "\n".join(notes) or None,
        }
        if jmbg:
            fields["jmbg"] = jmbg
        if kind == "person" and " " in p0["name"].strip():
            first, _, last = p0["name"].strip().partition(" ")
            fields["first_name"], fields["last_name"] = first, last

        existing = link_for(key, [i["name"] for i in items])
        if existing is not None:
            # link: enrich the existing contact's empty fields only
            ok, result = _enrich(cur, existing, p0, fields)
            if ok:
                linked += 1
            else:
                skipped += 1
                print("  SKIP enrich", existing, result)
        else:
            cur.execute(
                """
                INSERT INTO contacts (kind, display_name, first_name, last_name,
                                      jmbg, pib, mb, account, billing_address,
                                      city, country, email, phone, job_title,
                                      user_id, notes, created_at, archived)
                VALUES (?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, '', NULL, ?, ?, 0);
                """,
                (
                    kind, p0["name"],
                    fields.get("first_name", ""),
                    fields.get("last_name", ""),
                    fields.get("jmbg", ""),
                    fields["pib"], fields["mb"],
                    fields["billing_address"], fields["city"], fields["country"],
                    fields["email"], fields["phone"], fields["notes"],
                    _utcnow_iso(),
                ),
            )
            cid = cur.lastrowid
            cur.execute(
                "INSERT OR IGNORE INTO contact_roles (contact_id, role) VALUES (?, 'client');",
                (cid,))
            created += 1
            # register new identity so later groups can't duplicate
            if fields["pib"]:
                by_pib.setdefault(fields["pib"], cid)
            if fields["mb"]:
                by_mb.setdefault(fields["mb"], cid)
            by_name.setdefault(fold(p0["name"]), cid)

        target = existing if existing is not None else cid
        # locations: distinct (address, city) pairs across ALL matched rows;
        # a city-only pair (no street) carries no site info and is skipped
        pairs = []
        for i in items:
            pair = (i["address"], i["city"])
            if pair not in pairs and pair[0] and any(pair):
                pairs.append(pair)
        # existing locations of the contact (idempotent re-run) + billing
        # street so a matched pair never duplicates the master address
        cur.execute(
            "SELECT address, city FROM contact_locations WHERE contact_id = ?;",
            (target,))
        have = {(r["address"] or "", r["city"] or "") for r in cur.fetchall()}
        cur.execute("SELECT billing_address, city FROM contacts WHERE id = ?;",
                    (target,))
        row = cur.fetchone()
        billing = (row["billing_address"] or "").strip()
        have.add((row["billing_address"] or "", row["city"] or ""))
        def _addr_key(s):
            return "".join((s or "").split()).casefold()
        billing_key = _addr_key(billing)
        for n_, (address, city) in enumerate(pairs, 1):
            if (address, city) in have:
                continue
            if billing_key and (billing_key in _addr_key(address)
                                or _addr_key(address) in billing_key):
                continue  # same street as billing -> not a separate site
            name = city or address or f"Lokacija {n_}"
            cur.execute(
                """
                INSERT INTO contact_locations (contact_id, name, address, city,
                                               contact_name, contact_phone, notes)
                VALUES (?, ?, ?, ?, '', '', 'Iz uvoza musterije 2024-2026');
                """,
                (target, name, address, city),
            )
            have.add((address, city))

    conn.commit()
    conn.close()
    print(f"\ncreated={created} linked={linked} skipped={skipped}")


def richness(p):
    return sum(1 for v in (p["pib"], p["mb"], p["address"], p["city"],
                           p["phone"], p["email"]) if v)


def _utcnow_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _enrich(cur, contact_id, p0, fields):
    """Fill ONLY empty fields of an existing contact (never overwrite)."""
    cur.execute(
        "SELECT kind, display_name, pib, mb, billing_address, city, country,"
        " email, phone, notes, first_name, last_name, jmbg"
        " FROM contacts WHERE id = ?;", (contact_id,))
    row = cur.fetchone()
    updates, params = [], []
    for col, val in (("pib", fields["pib"]), ("mb", fields["mb"]),
                     ("billing_address", fields["billing_address"]),
                     ("city", fields["city"]),
                     ("email", fields["email"]), ("phone", fields["phone"]),
                     ("country", fields["country"])):
        if val and not (row[col] or "").strip():
            updates.append(f"{col} = ?")
            params.append(val)
    if fields["notes"]:
        new = ((row["notes"] + "\n") if (row["notes"] or "").strip() else "") + fields["notes"]
        updates.append("notes = ?")
        params.append(new)
    if updates:
        updates.append("kind = ?")
        params.append(row["kind"] or ("company" if p0["pib"] or p0["mb"] else "person"))
        params.append(contact_id)
        cur.execute(f"UPDATE contacts SET {', '.join(updates)} WHERE id = ?;", params)
    cur.execute(
        "INSERT OR IGNORE INTO contact_roles (contact_id, role) VALUES (?, 'client');",
        (contact_id,))
    return True, "ok"


if __name__ == "__main__":
    main()
