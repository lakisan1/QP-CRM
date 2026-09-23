# Agent Note: pdf-continuation-marker

Status: implemented

## Problem

Posle rows-whole ispravke, visok sledeći red ostavlja vidljiv prazan prostor na dnu strane. Korisnik: 'da li možemo da dodamo nešto što ukazuje da ima još sadržaja na sledećoj strani ili je to komplikovano a realno je nepotrebni hir.' Traži diskretan indikator nastavka, ne komplikovan sistem.

## Decision

CSS running-string mehanizam u static/css/pdf.css: @page @bottom-right margin box sa content: string(nastavak, last) (7.5pt italic #999, vertical-align top); .items-table td:last-child (Total ćelija — uvek čistan tekst bez ugnežđenog sadržaja) postavlja string '▼ nastavlja se na sledećoj strani'; .items-table tr:last-child td:last-child ga briše. string(..., last) vraća poslednju dodelu NA strani, pa strane gde tabela nastavlja pokazuju marker, a strana poslednjeg reda (i sve posle) ništa. Postavljanje je namerno na poslednjoj ĆELIJI a ne redu: WeasyPrint 69 tiho gubi string-set kad red sadrži ugnežđenu tabelu (markdown spec tabelama u opisima stavki) — otkriveno sintetičkim testovima protiv pravog MarinkovicHofmann css-a. Custom template (id 3, aktivan) zakrpljen direktno u DB; System Default reseedovan iz fajla pri bootu; oboje verifikovano u kontejneru. Verifikacija: render žive ponude 112 — marker na stranama 1-3 (tabela se nastavlja), čisto na 4 (poslednji red WA613) i 5 (summary).
## Alternatives considered

"**string-set na tr (prva ideja)**: izgubi se kad red sadrži ugnežđenu tabelu (markdown spec tabelu EE6604 proizvoda) — WeasyPrint 69 tiho odbacuje string-set sa kompleksnih boxova; otkriveno sintetičkim testovima (nested table row → mark False). **string-set na svim td + markdown-content td**: isto propada na nested redu. **JS/measure pristup**: nema JS u PDF renderu; dupli render bi duplirao vreme generisanja. **Ništa ne raditi (thead repetition je dovoljan signal)**: korisnik je eksplicitno tražio indikator; marker je 7.5pt italic sivi — diskretan. **Marker na nivou dokumenta (svaka strana osim poslednje)**: summary ide posle tabele pa bi marker lažno najavljivao tabelu; string iz tabele precizno prati tabelu — što je bio subjekt zahteva (prazan prostor ispod poslednjeg reda tabele)."
## Consequences

Kupljeno: svaka strana gde tabela stavki nastavlja nosi diskretan '▼ nastavlja se na sledećoj strani' u donjem desnom margin boxu (7.5pt italic, #999); strana sa poslednjim redom i sve posle nje su čiste — verifikovano na živoj ponudi 112 (mark strane 1-3, čisto 4-5). Cena: marker se oslanja na WeasyPrint string-set semantiku ('last' = poslednja dodela na strani) — WeasyPrint upgrade može promeniti semantiku, marker treba tada re-verifikovati (capability testovi su ad-hoc u /tmp, nisu u suite-u). Negativne garancije: nema markera na strani poslednjeg reda tabele (čak i ako posle tabele ide summary); ne postoji za header tabelu (jednostrana). Živi na dva mesta: static/css/pdf.css (System Default izvor, reseed pri bootu) + pdf_templates.css kolona custom templata u DB (boot NE dira custom).

