# Agent Note: device-table-brand-enrichment

Status: implemented

## Problem

Glavna tabela uređaja (2012 redova) imala je 1341 red bez kolone Brend — skripta build_table.py je detektovala brend samo iz naziva stavke preko ~50 token-lista. Ali mnogi izvorni fajlovi SU po brendu (OMCN 2023.xlsx = sve OMCN stavke; CASCOS KALKULACIJE = sve Cascos), a deo brendova je zaključiv samo iz konteksta familije ili je sporan pa traži internet potvrdu. Korisnik je tražio prolaz kroz celu tabelu sa dopunom iz Izvora ili interneta.

## Decision

tmp-excel/enrich_brands.py dopunjava kolono Brend u postojećoj tabeli-uredjaja.xlsx idempotentno (postojeći brend se nikad ne dira). Prioritet pravila: (1) postojeći brend iz naziva stavke; (2) brend iz imena izvornog fajla — FILE_BRANDS mapa za Hofmann TP kalkulacije (VALJCI/TERETNI/Putnički/MOTOCILI/LIFTS → HOFMANN) + prefiksno mapiranje OMCN/CASCOS/JOSAM/TREAD READER→JOSAM/CAR-O-LINER/BLACKHAWK/PRO CUT/EAE/MONTY/GEODYNA/GEOLINER→HOFMANN/TEXA/MECLUBE/TECNOLUX/BRAIN BEE/GIULIANO/GUERNET/ATEK/WHEEL RESTORE/GAT MATIC/NUSSBAUM; (3) NAME_BRANDS regex pravila po nazivu stavke: IDC5/IDC6/NAVIGATOR TXT/TXB/CONNEX/RCCS3/'Panel VAG|MERCEDES|FIAT|MAN|FORD|SCANIA|IVECO'→TEXA; AIRNEX/^101\d{6}/^501\d{6}/DIGITAL ADAS→BRAIN BEE; BODYGUARD/FASTLIGN/^BG\d+|^BG \+/CLY/TR UK|TR NA→BL INOVARE; Geodyna/Monty/Geoliner/Safelane/Duolift/Variolift/Quatrolift/Hofmann→HOFMANN; AGS-688/OPA-300/MGT-300/CENTRAFARI/WEARTEST/WT 4600/^LD 5/PK pedale→HOFMANN; ^EE-modeli→EAE; plus HERRMANN, COMPAC, NUSSBAUM, OMCN, CASCOS, JOSAM, CAR-O-LINER, BLACKHAWK, PRO CUT, MECLUBE, TECNOLUX, ATEQ/VT37, AUTOOL, PCE-\d+. (4) ništa ne pogodi → ostaje prazno. Stil vrednosti: UPPER CASE kao u postojećoj tabeli. Internet potvrde urađene DuckDuckGo HTML fetch-om: BODYGUARD+FASTLIGN=BL Innovare (bl-innovare.com), TreadReader=Josam/Snap-on tehnologija (josam.se), RCCS 3=TEXA (texa.com), Cosberg≠TP oprema. Skripta upisuje u obe kopije odjednom: tmp-excel/tabela-uredjaja.xlsx i 'Tabela uredjaja 2023-2026.xlsx' u korenu. Negativne garancije: NE dira postojeće brende, NE upisuje brend bez izvora-pravila, NE dodiruje pricing.db ni druge listove tabele osim kolone Brend na Uredjaji listu i jedne napomene na Sumarno.
## Alternatives considered

**Web search plugin** — ne radi u ovoj sesiji (DeepSeek search endpoint vraća nevalidan JSON), pa su potvrde rađene direktnim DuckDuckGo HTML fetch-om (html.duckduckgo.com/html/?q=…). Radi za ove potrebe; ako se plugin popravi, ne menja ništa u skripti.

**Fajl-prefiks 'BL ' kao direktna brend-dodela** — odbijeno: BL fajlovi (BL 2025/2026/KALKULATOR/CENE) sadrže i John Bean stavke pored BL Innovare proizvoda; preciznija su NAME pravila (BODYGUARD/FASTLIGN/BG12/CLY/TR UK-NA → BL INOVARE). Fajl-dodela bi pogrešno označila John Bean redove.

**'KALKULATOR.xlsx' i 'BMW ROTARY' fajl-dodela → HOFMANN** — odbijeno: mešani sadržaj; VARIOLIFT/Geoliner stavke već pokriva NAME pravilo, pa fajl-dodela ne dodaje pokrivenost a nosi rizik.

**Goli T-prefiks kataloški brojevi (T2000501732 Procesorska ploca) → HOFMANN** — odbijeno kao neizvesno: T-prefiks se javlja uz Safelane delove, ali bez potvrde da je ceo prefiks Hofmannov katalog. Ostavljeno prazno (ništa se ne izmišlja).

**Cosberg kao brend za 'VALJCI COSBERG' fajl** — odbijeno: cosberg.com potvrđuje da je Cosberg italijanski proizvođač industrijske montažne automatike, ne TP opreme; sadržaj fajla je identičan Hofmann kalkulacijama (PK pedale, SAFELANE) → HOFMANN.
## Consequences

Kupljeno: 53% redova sada ima brend (1083/2012), od toga 142 novih dodela ovom prolazu; nove brend-vrednosti u koloni koje nisu u CRM bazi (OMCN, TEXA, BRAIN BEE, ECOTECHNICS, COMPAC, HERRMANN...) biće ponuđene korisniku pri ručnom unosu — pricing.db NIJE diran. Cena: 929 redova ostaje prazno — generički nazivi (delovi, sonde, pantljike, usluge) gde brend zaista nije bio u izvoru; korisnik ih dopunjuje pri unosu po potrebi. Skripta je idempotentna (postojeći brend se ne dira) i može se ponovo pokretati posle svake regeneracije build_table.py. Obe kopije tabele (tmp-excel/ i koren) moraju se uvek osvežavati zajedno — skripta to radi sama.

