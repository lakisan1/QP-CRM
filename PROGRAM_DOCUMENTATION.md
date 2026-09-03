# PROGRAM_DOCUMENTATION.md — Kako program radi

Ovaj fajl beleži, korak po korak, kako QP-CRM program radi. Pregled se radi jedan task po jedan, polako i tačno. Za svaki fajl upisuje se objašnjenje njegove uloge i načina rada.

---

## 1. `main.py` — Glavna (kombinovana) aplikacija

**Uloga:** Spaja svih 6 podaplikacija u jednu celinu koja se pokreće na jednom portu (5000).

### Kako radi

1. **Dodaje putanju u sys.path** (`CURRENT_DIR`) — omogućava uvezivanje modula iz projekta (npr. `shared`, `pricing`, ...).
2. **Uvoz svih podaplikacija** iz projekta:
   - `pricing.app` → `pricing_app` (sa `init_db` i `migrate_schema`)
   - `offer.app` → `offer_app` (sa `init_db`)
   - `admin.app` → `admin_app` (sa `init_db`)
   - `sale.app` → `sale_app`
   - `settings.app` → `settings_app`
   - `rent.app` → `rent_app` (sa `init_db`)
   - `pricing.api_v1` → `api_v1` blueprint
3. **Kreira glavnu (landing) Flask aplikaciju** `app`:
   - `template_folder='templates'`
   - `static_folder=STATIC_DIR`, `static_url_path='/static'`
   - služi CSS/JS za landing stranu i za podaplikacije
4. **Registruje API blueprint** `api_v1` na `url_prefix="/api/v1"` (na vrhu, NE pod `/pricing` prefiksom).
5. **Rute na glavnom app-u:**
   - `GET /` → prikazuje `landing.html`
   - `GET /app_assets/<path:filename>` → servira fajlove iz `app_assets/` (npr. logo, favicon, PDF footer slika)
6. **i18n ubacivanje:** funkcija `inject_i18n()` čita trenutni jezik (`get_current_language()`) i ubacuje `_` (prevodi) i `current_lang` u sve template-ove.
   - Ubacuje se u **svaku** podaplikaciju: `pricing_app`, `offer_app`, `admin_app`, `sale_app`, `settings_app`, `rent_app` + glavni `app` (preko `context_processor`).
7. **Spajanje aplikacija** pomoću `DispatcherMiddleware`:
   - Glavni `app` služi `/`
   - `/pricing` → pricing_app
   - `/sale` → sale_app
   - `/offer` → offer_app
   - `/admin` → admin_app
   - `/settings` → settings_app
   - `/rent` → rent_app
8. **Pokretanje (`if __name__ == "__main__"`)**:
   - Poziva inicijalizacije i migracije baze: `pricing_init_db()`, `pricing_migrate_schema()`, `offer_init_db()`, `admin_init_db()`, `rent_init_db()`
   - Pokreće WSGI server `run_simple('0.0.0.0', 5000, application, use_reloader=True, use_debugger=True, threaded=True)` — na portu 5000, sa auto-restart (reloader) i interaktivnim debugger-om.

### Povezanost
- Glavni `app` je **roditelj** svih podaplikacija.
- Sve podaplikacije dele istu bazu `pricing.db` (preko `shared.db`).
- API blueprint `api_v1` dostupan na `/api/v1/...` bez obzira na podaplikacije.

---

## 2. `shared/` — Osnovni (zajednički) moduli

Ovi moduli su **zajednički** za sve podaplikacije — dele se preko `shared.*` importa.

### 2.1 `shared/config.py` — Centralne putanje

**Uloga:** Definiše sve putanje do foldera i baze, koje koriste svi moduli.

- `BASE_DIR` = roditeljski folder projekta (izračunato iz `__file__`).
- `APP_DATA_DIR` = `BASE_DIR/app_data` — folder za podatke.
- `DATABASE` = `app_data/pricing.db` — **zajednička baza** za sve podaplikacije.
- `IMAGE_DIR` = `app_data/product_images` — folder za slike proizvoda.
- `STATIC_DIR` = `BASE_DIR/static` — CSS/JS fajlovi.
- `APP_ASSETS_DIR` = `BASE_DIR/app_assets` — logo, favicon, PDF footer slika.

### 2.2 `shared/db.py` — Pristup bazi

**Uloga:** Daje funkciju `get_db()` koja otvara konekciju na zajedničku bazu.

- `get_db()`:
  - `sqlite3.connect(DATABASE, timeout=20.0)` — timeout 20s da se izbegne "database is locked".
  - `row_factory = sqlite3.Row` — pristup kolonama po imenu.
  - `PRAGMA foreign_keys = ON` — integritet podataka.
  - `PRAGMA journal_mode = WAL` — bolja konkurentnost (više čitača + 1 pisac).
  - `PRAGMA synchronous = NORMAL` — bolje performanse sa WAL.
  - **Vraća otvorenu konekciju** — pozivaoc je dužan da je zatvori.

### 2.3 `shared/auth.py` — Autentifikacija i API ključ

**Uloga:** Upravljanje lozinkama podaplikacija i API ključem.

- `DEFAULT_PASSWORDS` — podrazumevane lozinke: admin/Admin1, pricing/Price1, offer/Offer1, rent/Rent1.
- **API ključ:**
  - `generate_api_key()` → pravi 48-znak heks ključ i čuva ga u tabeli `global_settings` (ključ `api_key`).
  - `get_api_key()` → čita API ključ iz `global_settings`.
  - `validate_api_key(key)` → sigurna provera (constant-time `compare_digest`).
  - `revoke_api_key()` → briše API ključ (ukida pristup).
- **Lozinke:**
  - `get_password(app_name)` → čita lozinku aplikacije iz `global_settings` (ako nema, vraća podrazumevanu).
  - `check_password(app_name, input_password)` → proverava lozinku (obično poređenje).
  - `set_password(app_name, new_password)` → menja lozinku aplikacije.

### 2.4 `shared/utils.py` — Pomoćne funkcije i prevodi

**Uloga:** Formatiranje, i18n prevodi, kurs.

- `format_amount(value)` → formatira broj u evropski stil "12.312,00".
- `format_date(date_str, fmt)` → formatira `YYYY-MM-DD` u željeni format (`DD/MM/YYYY`, `MM/DD/YYYY`, `DD.MM.YYYY`).
- `TRANSLATIONS` — rečnik prevoda (samo `sr`; `en` je prazan jer su engleski izvorni).
- `get_current_language()` → čita jezik iz `global_settings` (ključ `language`).
- `translate(text, lang)` → prevodi tekst; `_` je skraćenica za `translate`.
- `get_nbs_rate(currency)` → preuzima srednji kurs iz API-ja `kurs.resenje.org` (vremenski limit 5s), vraća float ili None.

### 2.5 `shared/countries.py` — Lista zemalja

**Uloga:** Centralna lista zemalja za ponude/prodaju.

- `COUNTRIES` — lista rečnika: `{code, name, name_en}` (regionalne prvo, pa ostatak sveta abecedno).
- `get_country_list()` → vraća celu listu.
- `get_country_name(code)` → vraća srpski naziv zemlje po kodu (ako ne nađe, vraća kod).

---

## 3. `pricing/` — Modul za cene proizvoda

Najveći modul. Upravlja proizvodima, cenama, brendovima i kategorijama.

### 3.1 `pricing/app.py` — Glavna aplikacija za cene

**Uloga:** CRUD za proizvode, cene, brendove, kategorije. Dostupna pod prefiksom `/pricing`.

**Kako radi:**
- Dodaje `CUSTOM_LIBS_DIR` u `sys.path` (folder koji **ne postoji** — mrtav kod).
- Koristi zajedničku bazu preko `shared.db`.
- Funkcije:
  - `init_db()` — pravi tabele: `products`, `prices`, `brands`, `category_pricing_defaults`.
  - `migrate_schema()` — migracija šeme baze.
  - `add_product()` — dodaje proizvod (ime, opis, kategorija, brend, slika).
  - `edit_product(product_id)` — menja proizvod.
  - `delete_product(product_id)` — briše proizvod + sliku.
  - `price_history(product_id)` — istorija cena proizvoda.
  - `new_price(product_id)` — nova cena (sa podrazumevanim parametrima iz kategorije).
  - `edit_price(product_id, price_id)` — menja cenu.
  - `delete_price(product_id, price_id)` — briše cenu.
- **Rute (pod `/pricing`):**
  - `/products` — lista proizvoda (sa filtrima brand/category/search, sortiranje, paginacija)
  - `/products/quick_update` — brzo ažuriranje
  - `/products/add` — dodavanje
  - `/products/<id>/edit` — izmena
  - `/products/<id>/delete` — brisanje
  - `/products/<id>/prices` — istorija cena
  - `/products/<id>/prices/new` — nova cena
  - `/products/<id>/prices/<price_id>/edit` — izmena cene
  - `/products/<id>/prices/<price_id>/delete` — brisanje cene
  - `/category-defaults` — kategorije
  - `/brands` — brendovi
- Slike proizvoda se čuvaju u `IMAGE_DIR` (iz `shared.config`).

### 3.2 `pricing/api_v1.py` — REST API

**Uloga:** AI-friendly REST API za proizvode/cene/brendove/kategorije. Dostupan na `/api/v1/...`.

**Kako radi:**
- Blueprint `api_v1` (registrovan u `main.py` na `/api/v1`).
- Autentifikacija preko API ključa (`Bearer <api_key>`).
- Endpoint-i:
  - `GET /api/v1/health` — provera (javno, bez ključa).
  - `GET /api/v1/products` — lista sa filtrima i paginacijom.
  - `GET /api/v1/products/<id>` — jedan proizvod.
  - `GET /api/v1/products/<id>/photo` — slika proizvoda.
  - `POST /api/v1/products` — kreira proizvod (JSON ili multipart).
  - `PUT /api/v1/products/<id>` — menja proizvod.
  - `DELETE /api/v1/products/<id>` — briše proizvod.
  - `GET /api/v1/categories` — kategorije.
  - `POST /api/v1/categories` — kreira/menja kategoriju.
  - `DELETE /api/v1/categories/<name>` — briše kategoriju.
  - `GET /api/v1/brands` — brendovi.
  - `POST /api/v1/brands` — kreira brend.
  - `DELETE /api/v1/brands/<name>` — briše brend.
- Koristi `shared.db` i `shared.auth` (provera ključa).

---

## 4. `offer/` — Modul za ponude (quotation)

Upravlja ponudama, stavkama, PDF generisanjem, poređenjem proizvoda i email-om.

### 4.1 `offer/app.py` — Glavna aplikacija za ponude

**Uloga:** Kreiranje/izmena/brisanje ponuda, stavke, PDF, duplikati, poređenje.

**Kako radi:**
- Dostupna pod prefiksom `/offer` (preko DispatcherMiddleware).
- Koristi zajedničku bazu i `shared` module.
- Funkcije/ključne stvari:
  - `init_db()` — pravi tabele: `offers`, `offer_items`, `text_presets`, `offer_email_templates` (delimice).
  - `list_offers()` — lista ponuda.
  - `edit_offer(offer_id)` — izmena ponude + stavke (dodavanje/izmena/brisanje stavki).
  - `view_offer(offer_id)` — prikaz ponude.
  - `offer_pdf(offer_id)` — generisanje PDF (preko `weasyprint`).
  - `duplicate_offer(offer_id)` — duplira ponudu + stavke.
  - `delete_offer(offer_id)` — briše ponudu + stavke.
  - `update_item_order(offer_id)` — reorder stavki (JSON).
  - `compare_offers()` — alat za poređenje proizvoda (JS, bez čuvanja u bazi).
- **PDF generisanje:**
  - Koristi `weasyprint` (`HTML(...).write_pdf()`).
  - Ako postoji aktivni PDF template (iz `pdf_templates`), renderuje header/body/footer iz baze.
  - Ako nema, koristi `pdf_offer.html` + `static/css/pdf.css`.
  - Slike proizvoda se pretvaraju u `file://` URI za PDF.
- **i18n:** koristi `get_date_format()`, `format_amount`, `format_date`, prevodi.
- **Rute (pod `/offer`):**
  - `/offers` — lista
  - `/offers/add` — nova ponuda
  - `/offers/<id>` — izmena
  - `/offers/<id>/view` — prikaz
  - `/offers/<id>/pdf` — PDF
  - `/offers/<id>/duplicate` — duplikat
  - `/offers/<id>/delete` — brisanje
  - `/offers/<id>/reorder` — reorder
  - `/compare` — poređenje
- **Email:** čita `email_offer_subject` i `email_offer_body` iz `global_settings`.

---

## 5. `sale/` — Modul za prodaju (read-only pricelist)

### 5.1 `sale/app.py`

**Uloga:** Javni (read-only) cenovnik za klijente. Nema login, nema izmenu — samo prikaz.

**Kako radi:**
- Dostupna pod prefiksom `/sale` (preko DispatcherMiddleware).
- Koristi `shared` module i zajedničku bazu.
- Funkcije:
  - `get_theme()` — čita temu iz cookie-ja (`theme`, default `dark`).
  - `product_image(filename)` — servira slike iz `IMAGE_DIR` na `/sale/product-image/...`.
  - `list_sale()` — cenovnik sa filtrima (brand/category/search), sortiranjem i paginacijom.
  - `view_product(product_id)` — prikaz jednog proizvoda (opis se prevodi iz Markdown u HTML).
- **Rute (pod `/sale`):**
  - `/` → preusmerava na `/sale/pricelist`
  - `/pricelist` — lista
  - `/product/<id>` — detalji proizvoda
  - `/product-image/<path>` — slika proizvoda
- **Sortiranje:** name_asc, name_desc, price_asc, price_desc.
- **Paginacija:** čita `default_items_per_page` iz `global_settings`.
- `app.secret_key` je tvrdo kodiran (read-only session).

---

## 6. `settings/` — Modul za podešavanja

### 6.1 `settings/app.py`

**Uloga:** Podešavanja aplikacije (jezik, format, kurs, itd.).

**Kako radi:**
- Dostupna pod prefiksom `/settings` (preko DispatcherMiddleware).
- Čita/menja podešavanja u `global_settings` tabeli.
- Verovatno koristi `shared` module (auth, utils, countries).
- **Rute (pod `/settings`):**
  - `/settings` — podešavanja
  - login (zaštita)
- Detalji zavise od sadržaja — pregledan je u delovima.

---

## 7. `rent/` — Modul za zakup (rental) opreme

Upravlja ugovorima o zakupu, dokumentima, PDF šablonima i obračunom rata.

### 7.1 `rent/app.py` — Glavna aplikacija za zakup

**Uloga:** Upravljanje klijentima, opremom, ugovorima, dokumentima, obračunom i PDF.

**Kako radi:**
- Dostupna pod prefiksom `/rent` (preko DispatcherMiddleware).
- Koristi zajedničku bazu i `shared` module.
- Funkcije/ključne stvari:
  - `init_db()` — pravi tabele: `rent_clients`, `rent_equipment`, `rent_contracts`, `rent_templates`, `rent_contract_documents`.
  - `calculate_rent(...)` — obračun rata (neto/bruto, učešće, PDV, zatvaranje, ostatak, osiguranje, garancija).
  - `_build_doc_context(contract, calc)` — gradi kontekst za PDF dokumente (formatira vrednosti).
  - `_sort_templates(templates)` — sortira šablone po željenom redosledu (`TEMPLATE_SORT_ORDER`).
  - `contract_documents(contract_id)` — lista dokumenata za ugovor (+ email preset/subject).
  - `document_editor(contract_id, slug)` — editor dokumenta (GET učitava/kreira draft, POST čuva izmene).
  - `document_pdf(contract_id, slug)` — generiše PDF dokument (preko `weasyprint`).
- **Rute (pod `/rent`):**
  - `/clients` — klijenti
  - `/equipment` — oprema
  - `/contracts` — ugovori
  - `/contracts/<id>` — forma ugovora
  - `/contracts/<id>/documents` — lista dokumenata
  - `/contracts/<id>/documents/<slug>` — editor dokumenta (GET/POST)
  - `/contracts/<id>/documents/<slug>/pdf` — PDF dokumenta
- **PDF generisanje:**
  - Koristi `weasyprint` (`HTML(...).write_pdf()`).
  - Logo se koristi kao `file://` URI (lokalna putanja).
  - Ako postoji custom_content_html (draft), koristi njega; inače preuzima iz šablona i zamenjuje placeholdere (`{{ key }}`).
- **Obračun:** `calculate_rent` računa sve finansijske vrednosti (rata, učešće, PDV, osiguranje, garancija).
- **Email:** čita `rent_email_preset` i `rent_email_subject` iz `global_settings`, zamenjuje placeholdere klijenta/broja ugovora.
- **Templates:** `TEMPLATE_SORT_ORDER` — redosled prikaza dokumenata (ugovor-zakup, prilozi, menično ovlašćenje, itd.).

---

## 8. `admin/` — Modul za administraciju

### 8.1 `admin/app.py` — Glavna aplikacija za administraciju

**Uloga:** Admin panel — podešavanja, PDF template-ovi, presets, backup/restore, factory reset, API ključ, rent template-ovi.

**Kako radi:**
- Dostupna pod prefiksom `/admin` (preko DispatcherMiddleware).
- Zaštita: `check_auth()` (before_request) — sve osim `/login` i `static` zahteva `admin_authenticated` session.
- Funkcije:
  - `init_db()` — poziva: `init_presets_table`, `init_pdf_templates_table`, `init_rounding_rules_table`.
  - `login()` / `logout()` — admin prijava/odjava (check_password("admin")).
  - `index()` — admin dashboard (čita sva podešavanja iz `global_settings`).
  - `add_preset` / `delete_preset` / `set_default_preset` — presets (delivery/payment/note/extra).
  - `update_passwords` — menja lozinke (admin/pricing/offer/rent), provera trenutnog admin passworda.
  - `upload_logo` / `upload_footer` / `upload_favicon` — otpremanje branding slika (logo se kopira i u `static/img` i `app_assets`).
  - `update_settings` — menja podešavanja (date_format, theme, jezik, vat, validnost, zemlja, email, items_per_page, mandatory fields, rent defaults).
  - `backup_db` / `restore_db` — backup/restore samo baze.
  - `backup_full` / `restore_full` — backup/restore celog sistema (baza + slike + assets) u ZIP.
  - `factory_reset` — potpuni reset (backup, čišćenje tabela, reset global_settings, re-seed rent templates, brisanje slika, restore branding, vraća backup ZIP).
  - `list_pdf_templates` / `add_pdf_template` / `edit_pdf_template` / `delete_pdf_template` / `set_active_pdf_template` — PDF template-ovi (System Default je read-only).
  - `cleanup_images` — standardizuje imena slika proizvoda i briše orphaned fajlove.
  - `list_rounding_rules` / `add_rounding_rule` / `delete_rounding_rule` — pravila zaokruživanja cena.
  - `api_key_generate` / `api_key_revoke` — upravljanje API ključem (zahteva admin password).
  - `admin_rent_templates` / `admin_rent_template_edit` — editor rent master template-a (u bazi `rent_templates`).
- **Rute (pod `/admin`):**
  - `/login`, `/logout`
  - `/` — dashboard
  - `/add_preset`, `/delete_preset`, `/set_default_preset`
  - `/update_passwords`
  - `/upload_logo`, `/upload_footer`, `/upload_favicon`
  - `/update_settings`
  - `/backup_db`, `/restore_db`
  - `/backup_full`, `/restore_full`
  - `/factory_reset`
  - `/pdf_templates`, `/add_pdf_template`, `/edit_pdf_template/<id>`, `/delete_pdf_template`, `/set_active_pdf_template`
  - `/cleanup_images`
  - `/rounding_rules`, `/add_rounding_rule`, `/delete_rounding_rule`
  - `/api_key/generate`, `/api_key/revoke`
  - `/rent/templates`, `/rent/templates/<slug>`
- **Factory reset:** čisti tabela: products, prices, offers, offer_items, brands, category_pricing_defaults, text_presets, price_rounding_rules, rent_clients, rent_equipment, rent_contracts, rent_contract_documents, rent_templates; resetuje PDF templates (čuva System Default); resetuje global_settings na podrazumevane; re-seed rent templates; briše slike; restaura branding iz `app_assets/defaults`.

---

## 9. `settings/` — Modul za podešavanja (korisnički nivo)

### 9.1 `settings/app.py` — Glavna aplikacija za podešavanja

**Uloga:** Jednostavna stranica za korisničke podešavanja (tema i format datuma) koja čuva vrednosti u cookie-jima.

**Kako radi:**
- Dostupna pod prefiksom `/settings` (preko DispatcherMiddleware).
- Funkcije:
  - `inject_helpers()` — ubacuje `theme`, `_` (prevod) i `current_lang` u sve template-ove.
  - `settings_index()` — GET prikazuje podešavanja (čita iz cookie-ja), POST čuva `theme` i `date_format` u cookie-je (1 godina) i preusmerava na `/`.
- **Rute (pod `/settings`):**
  - `/` — GET/POST podešavanja.
- **Čuvanje:** `theme` i `date_format` se čuvaju kao cookie-je (path=/, max_age=1 godina), NE u bazi.
- **Napomena:** Ovo je korisnički nivo (per-browser), dok admin podešavanja (global) idu u `global_settings` tabelu preko admin modula.

---

## 10. `rent/import_templates.py` — Seed-ovanje rent šablona

### 10.1 Uloga i način rada

**Uloga:** Popunjava `rent_templates` tabelu sa podrazumevanim šablonima dokumenata (ugovor, prilozi, menično ovlašćenje, itd.).

**Kako radi:**
- `seed_templates(conn)` — glavni javni ulaz (poziva se u `init_db`).
- **Idempotentno:** Ako `rent_templates` već ima redove → preskače (ne duplira).
- **Prioritet:**
  1. Ako `rent_templates_defaults.json` postoji (preferirano, uvek dostupno na udaljenom serveru) → seed-uje iz JSON-a.
  2. Ako ne, koristi legacy `.docx` putanju (Word fajlovi u `excell Rent calc/word documents`) — konvertuje `.docx` u HTML.
- **Legacy .docx konverzija:**
  - `FIELD_MAP` — mapa MERGEFIELD → Jinja2 promenljive (npr. `broj_ugovora` → `{{ contract_number }}`).
  - `_clean_xml_fields(xml_bytes)` — obrađuje XML i zamenjuje MERGEFIELD polja sa `{{ ... }}`.
  - `_docx_to_html(docx_path)` — koristi `mammoth` biblioteku za konverziju.
  - Zahteva `mammoth` (ako nije instaliran → preskače sa upozorenjem).
- **Templates:** `TEMPLATES` — lista (fajl, slug, prikazni naziv) za 8 dokumenata.







