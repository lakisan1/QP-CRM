# Agent Note: pdf-items-row-page-break

Status: implemented

## Problem

Korisnik: 'u nekom trenutku se pokvario deo koji u PDF exportu za ponude izbegava da deli polja tabele na više strana ako samo može da pređe na sledeću' — uz priloženi PDF (E-Taksi Ponuda3 A, 5 strana) u kome je red MONTY 3300 RACING presečen sredine opisa između strana 3 i 4. Git arheologija: commit 1acd9ba (15.03.2026.) je flipovao .items-table tr sa break-inside: avoid na auto 'za duže opise' — od tada WeasyPrint seče red preko granice strane.

## Decision

static/css/pdf.css: .items-table tr je vraćen na page-break-inside: avoid + break-inside: avoid (uz komentar koji navodi regresioni commit 1acd9ba i WeasyPrint force-split garanciju za red viši od stranice). Custom MarinkovicHofmann template (id 3, aktivan) nosi sopstvenu CSS kopiju u pdf_templates.css koloni — zakrpljena direktno regex-zamenom auto→avoid. System Default se reseuje iz static/css/pdf.css pri admin bootu (init_pdf_templates_table), pa je deploy (container recreate) doneo i njega — oboje verifikovano u kontejneru. Verifikacija ispravke: render žive ponude 112 kroz /offer/offers/112/pdf sa test session-om; pypdf provera po stranama — svaka stavka (naziv + poslednji red opisa) na istoj strani; MONTY 3300 red ceo na strani 4.
## Alternatives considered

"**keep-with-next / orphan-widow CSS na ćelijama**: WeasyPrint ne podržava full keep-with-next semantiku kroz tabele; break-inside: avoid na tr je podržana i isprobana izrada. **Razbijati duže opise u više redova tabele**: menja strukturu podataka i snapshot; nepotrebno jer WeasyPrint force-split radi za red viši od stranice. **Ostaviti auto + skratiti opise**: korisnik eksplicitno želi cele redove; opisi su marketing sadržaj koji se ne seče po volji. **Samo zakrpa DB templata bez pdf.css**: System Default se reseuje iz fajla pri bootu — ako se zakrpi samo DB, sledeći boot vraća auto; ispravka MORA u fajlu (izvor istine) + DB custom kopija."
## Consequences

Kupljeno: redovi tabele stavki se više ne seku preko granice strane — red koji ne staje ide ceo na sledeću stranu; verifikovano renderom žive ponude 112 (MONTY 3300 red koji je bio presečen sada je ceo na strani 4; svih 5 stavki row-whole). Cena: redovi sa veoma dugim opisima ostavljaju više praznog prostora na dnu strane; ekstremni red viši od cele strane se i dalje seče (WeasyPrint force) — ispravan fallback. Negativne garancije: ispravka živi na DVA mesta — static/css/pdf.css (izvor System Defaulta, reseuje se pri bootu) i css kolona custom templata u DB (boot je NE dira); novi custom templati kopiraju trenutni System Default pa nose avoid automatski. Ako neko ručno edituje custom template CSS, mora sam zadržati avoid pravilo.

