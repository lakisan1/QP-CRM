# Agent Note: sync-add-to-crm-opens-edit

Status: implemented

## Problem

Na /pricing/products/product_sync, „Dodaj u CRM" otvara modal (slika sa sajta, opis, brend, kategorija). Posle klika na „Dodaj u CRM" proizvod se sačuva, ali stranica se samo ponovo učita — korisnik mora ručno da nađe novi proizvod u katalogu da bi ga uredio (dodao cenu, proverio opis). Korisnik traži da ga dugme posle čuvanja odvede pravo na edit formu tog proizvoda.

## Decision

`/api/v1/sync/add_product` (qp_crm/pricing/api_v1.py) sada u `data` vraća i `edit_url` izgrađen sa `url_for("pricing.edit_product", product_id=new_id)` — ruta edit strane ostaje definisana na jednom mestu (Flask url_for), šablon je ne hardkoduje. U `product_sync.html` success handler modala zatvara modal i postavlja `window.location.href = data.edit_url` (fallback `/pricing/products/<id>/edit` ako polja nema); stari tok „showMsg + loadTable()" je uklonjen. Greške (duplikat imena, neuspešno preuzimanje slike, itd.) ostaju u modalu sa istim porukama. Proizvod se i dalje odmah 1:1 povezuje sa site proizvodom. Negativna garancija: ne menja se validacija, preuzimanje slike, niti API za eksterne klijente (novo polje je aditivno); nema novog endpointa. 2 nova testa u tests/pricing/test_sync_add_product.py pinuju `edit_url` ugovor (i da ciljna edit strana vraća 200) i redirect u šablonu; ceo suite 570 passed / 3 skipped. Live: CI image sha-fbbbc3a je pull-ovan na lokalnu instancu; product_sync 200 sa edit_url/redirectom, edit strana 200, /api/v1/products 200.
## Alternatives considered

**Hardkodovan edit URL u JS-u** — odbijeno: dupliranje rute, lako se pokvari pri refaktoru; API vraća `edit_url` preko url_for. **Redirect na listu proizvoda sa filterom po imenu** — korisnik je izričito tražio da se otvori edit meni baš tog proizvoda. **Prikaz „Proizvod dodat" poruke sa linkom, bez automatskog prelaska** — dodatni klik i ostajanje na sync strani; automatski prelazak je traženo ponašanje. **Novi endpoint za edit URL** — nepotrebno; polje u postojećem odgovoru je dovoljno. **Bump verzije na 1.1.6** — nije traženo; verzija ostaje 1.1.5, a build se razlikuje po sha tagu.
## Consequences

Dobijeno: jedan klik manje posle dodavanja — proizvod se odmah uređuje (slika, opis, cene) umesto da se traži kroz katalog; URL edit strane dolazi sa servera pa se ne može razići sa rutom. Cena: API odgovor `sync_add_product` ima novo polje `edit_url` (aditivno, stari klijenti ga ignorišu); JS prelazak znači da korisnik ne vidi potvrdu „povezan sa sajtom" — veza je i dalje napravljena i vidljiva na edit strani/istoriji; ako je preusmeravanje blokirano (npr. ekstenzija), ostaje na sync strani bez poruke. Negativna garancija: ne menja se način kreiranja proizvoda, 1:1 link, ni ponašanje pri grešci (modal ostaje otvoren sa porukom). Produkcija i dalje zahteva ./deploy.sh na serveru (image sha-fbbbc3a).

