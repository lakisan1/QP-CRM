# Agent Note: komercijala-app-variant-b

Status: implemented

## Problem

Korisnik je u produkciji video meni Magacina sa tri stavke obeležene '(admin)' (Oprema, Rezervacije, Pokrivenost) i tačno uočio da rezervacije i pokrivenost ne pripadaju magacioneru — to su stvari koje interesuju prodaju/komercijalu. Takođe je tražio da komercijalca vidi gde je koja mašina (kod koje mušterije) i da se app preimenuje jer 'Narudžbine' pokriva samo deo sadržaja.

## Decision

Komercijala app (blueprint 'orders' na /orders, ime u UI promenjeno) poseduje: Narudžbine (POs + prijem + statusi), Treba naručiti (dugovi + min-stock praznine), Rezervacije (premeštene iz warehouse: rute u orders/routes/planning.py, templejti orders/templates/orders/), Pokrivenost (ATP, premeštena), i NOVU 'Gde je oprema' (/orders/equipment-map: svi uređaji sa statusom, čuvarom i 'od kada' — searchable). Magacin poseduje SAMO fizički posao: Stanje (/warehouse/stock), Ulaz/Izlaz (/warehouse/intake), Oprema (registar mašina, sada bez (admin) taga — svi sa warehouse grantom vide registar). is_admin injekcija u warehouse context processoru uklonjena (nema više uslovnog menija). URL /orders zadržan interno (nema šeme/URL migracije); ime 'Komercijala' živi u landing kartici i banner naslovima. Old /warehouse/reservations i /warehouse/coverage rute vraćaju 404.
## Alternatives considered

**Zadržati (admin) tag u Magacinu** — odbijen po korisnikovoj primedbi: rezervacije i pokrivenost su komercijalne funkcije, ne administrativne; (admin) tag je bio privremeno rešenje iz prethodne iteracije. **Ime 'Planiranje'** — predlog iz chata, ali korisnik izabrao 'Komercijala' u eksplicitnom pitanju. **Redirectovi starih /warehouse/reservations URL-ova** — odbijeni: modul u produkciji tek od juče (nema bookmarkova), 404 je čistiji od mrtvih redirectova. **Kopirati rute umesto premeštanja** — odbijen: dve istine o rezervacijama bi se rasle; git mv čuva istoriju i endpoint-i postoje na jednom mestu.
## Consequences

Kupio: čista podela rada — Magacin = fizički posao (3 taba), Komercijala = planiranje (5 tabova, uključujući novu 'Gde je oprema' tabelu koja komercijalci daje odgovor 'koji je uređaj kod koje mušterije' bez ulaska u Magacin); grantovi ostaju nezavisni (warehouse i orders), pa Admin → Users kontroliše ko šta vidi. Platio: stari URL-ovi /warehouse/reservations i /warehouse/coverage umiru bez redirecta (svesno, mlad modul); testovi za rezervacije/pokrivenost su premesteni u orders suite (tests/orders/test_orders_module.py planning sekcija), pa test fajl više ne prati strukturu po modulu 1:1. Negativna garancija: is_admin uslovni meni u Magacinu više ne postoji — svaki korisnik sa warehouse grantom vidi i Opremu; shortfall CREATE/CLOSE ostaju na machine page-u u Magacinu (fizički akt kad se skida deo), dok se dug zatvara automatski prijemom narudžbine u Komercijali.

