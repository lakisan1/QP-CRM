# Agent Note: legacy-document-contact-backfill

Status: implemented

## Problem

Korisnik: postojeće ponude nisu vezane u imeniku za sve kliente. Pre unifikacije izdati dokumenti imaju contact_id NULL (79/83 ponuda, 4/4 rent ugovora), pa detail stranica kontakta pokazuje praznu istoriju 'Povezani dokumenti' iako je musterija poslovala. Potrebno vezati stari fond za zajednički imenik — bez menjanja print-snapshotova i bez lažnih veza.

## Decision

contact_service.link_documents_to_contacts(cur) radi iz migrate_contacts (shared/schema.py) na svakom boot-u, posle backfill_rent_clients_into_contacts. Idempotentno: razmatra samo redove sa contact_id IS NULL. Rezolucija po redu: (1) PIB (pa MB) poklapanje prihvaćeno SAMO kad se naziv dokumenta slaže sa kontaktom (normalizacija: casefold + squeeze whitespace; unicode prolazi) ili dokument nema naziv; (2) bez poreškog broja — tačno normalizovano poklapanje naziva; (3) PIB/MB postoji ali je nepoznat imeniku ILI pripada kontaktu drugog naziva — red ostaje nevezan (svesno, za ručni pregled). Nikad ne menja snapshot polja (client_name/pib/...), samo id link. Ne kreira kontakte, ne briše ništa. Testovi: tests/characterization/test_document_backfill.py (8) — uključuju HIDRAULIK FLEX konflikt i boot-hook pin. Live DB posle deploy-a: 76/78 ponuda + 4/4 renta vezano; obrisani moji test-artefakti iz live baze (5 ponuda, 3 kontakta) nastali headless runovima bez conftest patcha.
## Alternatives considered

"**Jednokratni skript umesto boot hook-a**: manje rizika za buduće boot-ove, ali svaki novi dokument bez linka bi zahtevao ponovno ručno pokretanje; boot hook je već uspostavljen obrazac (backfill_rent_clients_into_contacts radi isto) i idempotentan je po kontraktu. **Vezati i po neskladu PIB-a (isti naziv = isti kontakt)**: HIDRAULIK FLEX dokaz zašto ne — dva različita PIB-a pod istim nazivom; veza po nazivu bi jedan od njih vezala za pogrešan identitet. **Fuzzy matching**: 'DOO AutoBeli' vs 'AUTO-BELI' bi možda uhvatio, ali lažna poklapanja u 78 dokumenata su gora cena od 2 ručno vezana reda; tačan naziv + PIB pravila su proveriva. **MERGE kontakata AUTO-BELI/DOO AutoBeli automatski**: merge alat je P5 stock/equipment opseg (rename/merge-safe već planiran tamo); ovde samo nevezati, merge je eksplicitna ručna radnja. **Izveštaj nevezanih (korisnik odbio)**: ponuđen i odbijen — korisnik traži samo da veza postoji; nevezani redovi su vidljivi kao obični dokumenti bez imenik-historije."
## Consequences

Kupljeno: imenik istorija (Povezani dokumenti na detail stranici) pokriva i stari fond — 76/78 ponuda + 4/4 renta vezano; pravilo traje: svaki budući dokument bez linka se poveže pri narednom restartu ako poklapanje dozvoli. Cena: 2 ponude (P-1034 sa PIB-om 108028497 kog nema u imeniku, P-1197 'DOO AutoBeli' — isti PIB kao AUTO-BELI ali drugačiji naziv) ostaju nevezane — ručni pregled/merge; boot svakog starta radi jedan SELECT po tabeli (jeftino na ovom obimu). Negativne garancije: snapshot polja se Nikad ne prepisuju backfill-om; nevezani redovi nemaju flag — jedini znak je prazna sekcija Povezani dokumenti u imeniku; backfill ne kreira Nove kontakte — musterija van imenika ostaje nevezana dok je neko ne doda. Opoziv: linkovi su obične FK vrednosti, ručno se čiste UPDATE-om. Tokom verifikacije ustanovljeno da headless probne skripte bez tests.conftest patcha pišu u live DB — 5 test-ponuda i 3 test-kontakta obrisano; ubuduće headless run mora kroz conftest patch ili QP_TEST_ROOT.

