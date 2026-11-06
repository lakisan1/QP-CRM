# Agent Note: sync-link-modal-tomselect-load

Status: implemented

## Problem

Na /pricing/products/product_sync, modal „Poveži sa CRM proizvodom" ima polje „Pretraži CRM proizvod..." ali kucanje nikada ne prikaže rezultate — povezivanje sa postojećim CRM proizvodom je praktično nemoguće, pa korisnik mora da pravi duplikat preko „Dodaj u CRM". TomSelect je ispravno inicijalizovan (placeholder i input postoje), što je maskiralo uzrok u JS callback-u.

## Decision

Uzrok: TomSelect (2.2.2) poziva remote `load` callback sa JEDNIM argumentom — nizom opcija (`settings.load.call(this, query, loadCallback)`, a `loadCallback(options, optgroups)` prosleđuje `options` u `setupOptions`). Stranica je koristila jQuery-UI stil `callback(null, data.map(...))`, pa je `options` bio `null` i `setupOptions` nije dodao nijednu opciju — dropdown je uvek bio prazan, bez greške u konzoli. Popravka u `product_sync.html::loadCRMForLink` je `callback(data.map(p => ({ id: p.id, name: p.name })))`; greške i dalje rade `callback()` (prazan rezultat). Reprodukcija: jsdom + tačno taj TomSelect build (v2.2.2) — buggy oblik 0 opcija, ispravan 2; završna provera urađena nad ŽIVIM HTML-om stranice sa realnim TomSelect-om i stub API-jem (unos „ATEQ" → 2 opcije). Test `tests/pricing/test_sync_add_product.py::test_link_modal_load_callback_passes_options_as_single_argument` pinuje oblik poziva (postoji `callback(data.map(...))`, nema `callback(null, data)`). Ceo suite 573 passed / 3 skipped; commit 35cf020; CI success; lokalna instanca pull-ovala image.
## Alternatives considered

**Zameniti TomSelect običnim inputom + sopstvenim dropdownom** — više koda i novi rizici; TomSelect već radi na drugim mestima, pa je popravka callback ugovora minimalna i bezbedna. **Učitati sve CRM proizvode odjednom u `<select>` i filtrirati lokalno** — katalog ima stotine/više proizvoda; TomSelect remote `load` je već postojao i skalira; problem nije bio u pristupu nego u potpisu callback-a. **Zadržati `callback(null, options)` i dodati adapter** — nema svrhe držati jQuery-UI stil kad je TomSelect jednostavan single-arg ugovor. **Pisati browser test u pytest suite-u** — CI image nema node/jsdom, pa bi test bio preskočen ili bi zahtevao novu infrastrukturu; umesto toga suite pinuje oblik poziva, a ponašanje je verifikovano jednokratnim jsdom skriptom van suite-a (i live HTML-om).
## Consequences

Dobijeno: „Poveži" modal ponovo pretražuje CRM katalog (live HTML + realni TomSelect 2.2.2 u jsdom: unos „ATEQ" daje 2 opcije) i prikazuje rezultate dok se kuca. Cena: greška je bila nevidljiva jer TomSelect ne baca grešku za pogrešan potpis callback-a — tiho prikaže prazan dropdown, pa je trebalo reprodukovati sa jsdom; suite sada pinuje samo oblik poziva (`callback(data.map(...))`, bez `callback(null, data)`) jer browser test nije izvodljiv u CI image-u. Negativna garancija: API se ne menja (`/api/v1/products?search=` je i dalje isti, već je radio); izbor proizvoda (`link-save` → `/api/v1/sync/link`) i ostali modali su netaknuti. Ako se TomSelect jednog dana zameni drugom bibliotekom, ovaj callback ugovor i test moraju da se preispitaju.

