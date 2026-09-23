# Agent Note: product-item-type

Status: implemented

## Problem

Korisnik: 'proizvod može da bude fizički proizvod ili usluga, to je obavezno polje, i sve do sada je fizički proizvod.' Products tabela ne razlikuje fizički proizvod od usluge — treba obavezna klasifikacija na svakom proizvodu, sa backfillom svih postojećih redova kao fizičkih proizvoda.

## Decision

products.item_type je TEXT NOT NULL DEFAULT 'proizvod' (shared/schema.py korak 3e: CREATE TABLE kolona + idempotentni add_column_if_missing). DEFAULT pokriva sve postojeće redove pri ALTER-u (253/253 'proizvod' verifikovano u live kontejneru) i programski inserte koji polje ne šalju (offer TEMP quick-create, site-sync import u api_v1 import_product_from_site). Validirani Choice skup je ('proizvod', 'usluga') — primenjen na tri mesta: pricing add_product/edit_product (greška 'Vrsta stavke je obavezna: fizički proizvod ili usluga.', input preserved kroz re-render), api_v1 create_product (400 bez validne vrednosti) i api_v1 update_product (odsutan = zadrži, prisutan mora biti validan, inače 400). Forma: required select 'Vrsta stavke *' na vrhu pricing product forme (Fizički proizvod default selektovan; prekidač omogućava uslugu). products lista: 'Usluga' badge (ljubičasti pill) na uslužnim redovima + 'Vrsta stavke' filter (session-persisted products_filter_item_type, clear=1 resetuje); sale pricelist isto (sale_filter_item_type) + badge u redu + 'Vrsta stavke' red u view_product kartici. API list/detail izlažu item_type; API_INSTRUCTIONS.md dokumentuje obaveznost i vrednosti. Prevodi: 'Item type' → 'Vrsta stavke', 'Physical product' → 'Fizički proizvod', 'Service' → 'Usluga'. Testovi: tests/smoke/test_product_item_type.py (11) + stari smoke helperi (product_code, product_links, csrf probe) dopunjeni novim obaveznim poljem. Suite 338 passed, 3 skipped.
## Alternatives considered

"**BOOLEAN is_service flag**: manje eksplicitno na nivou šeme i API-ja ('usluga' se čita direktno); TEXT Choice je samodokumentirajući i otvara put trećoj vrednosti (npr. 'paket') bez migracije tipa. **Backfill skript umesto DEFAULT**: nepotrebno — SQLite NOT NULL DEFAULT na ALTER TABLE postavlja vrednost postojećim redovima odmah; nula dodatnog koda. **Opciono polje**: korisnik je eksplicitno rekao 'obavezno polje'; server-side validacija na oba unosa (forma i API create/update). **item_type u offer_items snapshot-u**: ponude su snapshot-by-design; ako korisnik bude htéo da ponuda nosi vrstu stavke, to je nova kolona + template rad — nije deo ovog zahteva."
## Consequences

Kupljeno: svaki proizvod sada ima deklarisanu vrstu (obavezno na unosu), filtriranje na obe liste (pricing + sale), vidljiv badge na 'usluga' redovima, API kontrakt sa obaveznom vrednošću pri kreiranju. Cena: stari programski klijenti koji POST-uju /api/v1/products bez item_type sada dobijaju 400 (dokumentovano u API_INSTRUCTIONS); web forma je uvek slala novi field pa UI flow ne trpi breaking. Negativne garancije: item_type NE ulazi u offer_items snapshot ni PDF (familija offer-invisible polja); TEMP quick-create u ponudi i site-sync import hard-kodiraju 'proizvod' (TEMP proizvodi su fizički do daljeg); nema unique constraint; filter se pamti po sesiji (kao ostali filteri). Ako korisnik bude hteo treću vrstu (npr. 'paket'), dodaje se u dva Choice skupa (rute + API) i opciono u prevod — bez šeme-migracije.

