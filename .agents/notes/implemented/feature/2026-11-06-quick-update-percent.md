# Agent Note: quick-update-percent

Status: implemented

## Problem

Na /pricing/products/quick_update nabavna cena se mogla menjati samo upisivanjem apsolutnog broja u polje Purchase Price. Korisnik hoće da umesto toga (ili pored toga) unese procenat, npr. +7 ili -7, i da se nabavna cena automatski preračuna — ista akcija kao ručni unos, samo procentualno. Stranicu koristi admin i na produkciji qp.hofmann-srbija.rs.

## Decision

Svaki red na quick_update strani ima, ispod apsolutnog `base_price` polja, malo `base_price_percent` polje („± %", placeholder i aria-label; sr prevodi u shared/utils.py). Page JS (`input` delegacija nad tabelom) uživo računa `base_price = data-stored * (1 + p/100)` dok se procenat kuca, sa clamp-om na 0; ručna izmena apsolutnog polja briše procenat i postavlja `data-stored` na unetu vrednost (nema kompoundovanja). Server u `quick_update_save` NE veruje JS-u: parsira `base_price_percent`; ako je validan broj i postoji bar jedna cena u `prices`, posted `base_price` se ignoriše i nova nabavna cena = `round(max(0, latest_base_price * (1 + p/100)), 2)`; neparsabilan procenat (npr. „abc") se ignoriše i koristi se apsolutno polje; nema istorije cena → apsolutno polje. Ostatak kalkulacije (extras, marža, zaokruživanje, popust) je nepromenjen. Negativna garancija: procenat menja SAMO base_price, ne extras ni prodajnu cenu direktno; nema bulk primene na sve redove; -100% i niže clamp-uje na 0 umesto negativne cene. 7 regresionih testova u tests/pricing/test_quick_update_percent.py pokrivaju +7/-7, „stored vs posted", ručni režim, invalid fallback, clamp i prisustvo polja u HTML-u; ceo suite 568 passed / 3 skipped. Lokalna LAN instanca je rebuild-ovana i restartovana; produkcija nije dirana.
## Alternatives considered

**Procenat samo u JavaScript-u (live preview je dovoljan)** — odbijeno: bez JS-a (ili sa blokiranim JS-om) polje bi se slalo kao apsolutni broj i admin bi sačuvao staru cenu; server-side račun garantuje rezultat. **Procenat na finalnu (prodajnu) cenu** — korisnik je izričito tražio nabavnu cenu. **Kompoundovanje uzastopnih procenata** (+7 pa +7 = +14,49%) — odbijeno: JS re-anchors data-stored na ručno unetu vrednost, pa je ponašanje predvidivo; server uvek računa od poslednje sačuvane baze. **Posebno „bulk %" polje za sve redove odjednom** — nije traženo; per-red unos je minimum i ne menja tok rada. **Novi tip polja / toggle €↔% po redu** — složeniji UI bez potrebe; drugo malo polje je dovoljno i vidi se u svakom redu.
## Consequences

Dobijeno: nabavna cena se menja procentom u dva klika, uz live preview pre Save; sačuvana vrednost je identična bez obzira na browser; negativan procenat je podržan i clamp-uje se na 0 (nema negativne nabavne cene); ručni režim radi nepromenjeno. Cena: procenat je vezan za NAJSVEŽIJU cenu iz baze, ne za ono što piše u polju — ako je neko u međuvremenu sačuvao drugu cenu, procenat se primenjuje na nju (namerno, ali može iznenaditi); JS re-anchoring pravilo (manual edit briše %) je implicitno, ne vidi se u UI-ju. Negativna garancija: ne dira se ništa drugo — extras, marže, popusti i istorija cena idu kroz isti, nepromenjen put; nema bulk primene na sve redove niti na druge kolone. Produkcija (qp.hofmann-srbija.rs, GHCR main@c06939c) NIJE ažurirana ovim commitom — potreban je merge Dev→main + CI + deploy.sh na serveru.

