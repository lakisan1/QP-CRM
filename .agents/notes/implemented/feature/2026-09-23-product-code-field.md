# Agent Note: product-code-field

Status: implemented

## Problem

Korisnik: 'Dodaj i product ID isto kao dodatno opciono polje u proizvodima.' Products tabela nema polje za spoljašnji ID/šifru proizvoda (kataloški broj dobavljača, vendor sku) — postoji samo site_product_id (interni 1:1 link ka sajtu, unique, nije za ručni unos) i dva link-polja. Treba opciono, slobodno tekstualno polje na samom proizvodu.

## Decision

products.product_code je nullable TEXT kolona (shared/schema.py: CREATE TABLE products + idempotentni add_column_if_missing u migrate_pricing kao korak 3d, uz postojeće 3c website/manufacturer linkove). Pricing forma (product_form.html): text input 'ID / šifra proizvoda' ispod naziva/description bloka, vrednost se čuva kroz error re-rendere (add + edit). products lista renderuje 'ID: <code>' pod nazivom proizvoda; sale view_product prikazuje ga u info kartici. api_v1: list/detail vraćaju product_code; create ga prima (multipart i JSON); update: odsutan = zadrži postojeći, prazan string = obriši (isti ugovor kao URL polja). Ponude ga nikad ne vide BY CONSTRUCTION: offer add_item snima samo name/description/photo_path iz products reda — pinned testom (tests/smoke/test_product_code.py, 8 testova). Prevod: 'Product ID / code' → 'ID / šifra proizvoda' (shared/utils.py TRANSLATIONS). API_INSTRUCTIONS.md dokumentovan. Deployed: image rebuild, container recreate, healthcheck green, kolona verifikovana u kontejneru.
## Alternatives considered

"**Brojčani tip (INTEGER) umesto TEXT**: proizvodni kodovi često sadrže slova/nule na početku ('DW-XR-2233'); TEXT je jedini bezbedan izbor. **UNIQUE index na product_code**: kodovi dobavljača se mogu ponavljati među proizvodima (varijante); namerno bez unique — site_product_id je jedinstven jer je 1:1 sync link, product_code nije. **Polje u ponudama/PDF-u**: korisnik je za linkove eksplicitno tražio 'nikad u ponudama'; product_code je dodatek istoj familiji (3d), pa isto pravilo — pinned test. **Odvojena 'šifra' i 'kataloški broj' kolone**: jedno opciono polje je ono što je traženo ('product ID isto kao dodatno opciono polje'); split po potrebi kasnije — nova kolona je idempotentni ALTER."
## Consequences

Kupljeno: strukturiran, API-dostupan spoljašnji kod proizvoda sa jednim redom UI integracije (lista: 'ID: <code>' pod nazivom; sale view: info card red). Cena: products lista sada renderuje još jedan red po proizvodu kad je kod postavljen — zanemarljivo; nevezano: pretraga po kodu NIJE dodata (products list search je po nazivu) — ako korisnik traži pretragu po šifri, to je sledеći korak. Negativne garancije: ponude/PDF nikad ne nose kod (pinned test); nema unique constraint na kodu; ne pojavljuje se u offer_items snapshot-u ni u PDF template-ovima.

