# Agent Note: pdf-continuation-marker-revert

Status: implemented

## Problem

Korisnik: 'taj tekst je preko footera, sad može ipak samo da se vrati kako je bilo, ok je sasvim.' '▼ nastavlja se na sledećoj strani' marker u @bottom-right margin boxu se preklapao sa running futerom (element(doc-footer) zauzima @bottom-center a footer sadržaj je širok) — tekst markera je padao preko futera.

## Decision

Marker je uklonjen iz oba izvora: static/css/pdf.css (oboreno @bottom-right margin box i string-set pravila; komentar ostaje samo na break-inside: avoid pravilu koje je zadržano) i MarinkovicHofmann css kolone u DB (regex + line-filter čišćenje @bottom-right bloka i oba string-set pravila sa svojim komentarima). rows-whole fix ostaje netaknut. Verifikacija: sintetički render sa custom css-om bez markera + provera u kontejneru posle deploy-a (nastavak/@bottom-right odsutni u oba šablona, avoid prisutan). System Default se reseedovao iz fajla pri bootu.
## Alternatives considered

"**Pomeriti marker iznad futera (margin-top umesto preklapanja)**: bio je na 4mm od dna ali je element(doc-footer) box zauzeo donji centar — pozicioniranje dva margin boxa jedan uz drugi je krhko po visini futera (slike u futeru menjaju visinu); umesto debagovanja preklapanja, korisnik je rekao 'ok je sasvim' — revert. **Marker u sam footer element (content element())**: uslovno prikazivanje po strani i dalje zahteva string() mehanizam — isti korenski problem, dodatna složenost bez garancije. **Dovoljno dobro rešenje koje ostaje**: thead se ponavlja na svakoj strani tabele (postojeće ponašanje) — korisniku je to prihvatljivo."
## Consequences

Kupljeno: footer je opet čist — nema preklapanja; rows-whole fix (break-inside: avoid) ostaje i dalje živi. Cena: prazan prostor ispod poslednjeg reda na strani gde visok red skače je opet neobjašnjen vizuelno (thead na sledećoj strani je jedini signal). Negativne garancije: revert je KOMPLETAN na oba mesta (pdf.css fajl za System Default + MarinkovicHofmann css kolona u DB) — provereno u kontejneru posle deploy-a; ako se marker ikad vrati, lekcija je da margin box sa string() mora koegzistirati sa element(doc-footer) boxom — pozicioniranje mora računati na visinu futera.

