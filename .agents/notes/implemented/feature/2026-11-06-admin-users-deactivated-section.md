# Agent Note: admin-users-deactivated-section

Status: implemented

## Problem

Na Admin → Users deaktivirani nalozi su izgledali identično aktivnima (samo bi Active checkbox bio otkačen), pa se na prvi pogled nije videlo ko zapravo može da se prijavi. Korisnik je tražio da deaktivirani budu sivi/tamni ILI u odvojenom delu stranice, uz napomenu „treba da postoji samo default admin nalog, ponuda/pdf nalozi ne treba sami da se prave". Live baza je imala 6 naloga (admin, zorica, pricing, offer, rent, pdf_probe); staff nalozi su ostaci legacy restore-a od 22.09., ne auto-kreiranje — seeding od commita 4f3a2a1 pravi isključivo admin bootstrap nalog.

## Decision

Admin → Users je sada podeljen na dve kartice koje dele isti markup reda: „Active users" (jedini nalozi koji mogu da se prijave) i „Deactivated users" na dnu. Deaktivirani redovi imaju `class="user-row-inactive"` (opacity .5, hover .85, leva siva ivica) i uppercase DEACTIVATED bedž pored imena; sekcija nosi objašnjenje da se nalozi nikad ne brišu (evidencija ko je šta radio) i da se reaktivacija radi kroz Active + Save. Ruta `admin/routes/users.py:list_users` deli redove na `active_users`/`inactive_users` (ostalo nepromenjeno: moduli, kontakt-link, poslednji login). Admin redovi sada takođe renderuju Active toggle (bez app checkbox-ova), inače deaktivirani drugi admin ne bi mogao da se vrati iz UI-ja; sopstveni red namerno nema active/role kontrole (servis ih ionako blokira). Nema delete dugmeta ni delete rute — `users` ostaje append-only po dizajnu. Live instance je rebuild-ovana iz Dev stabla (korisnikov izbor, bez main/CI) i kontejner je zdravo podignut; md5 šablona u kontejneru se poklapa sa repo fajlom, a HTTP provera sa privremeno deaktiviranim `pdf_probe` pokazala je red u odvojenoj sekciji i vraćena je u aktivno stanje.
## Alternatives considered

**Samo sivi red bez razdvajanja** — korisnik je eksplicitno izabrao oba („sivi red + odvojen deo"), pa jedan signal nije dovoljan; **samo odvojen deo, normalan izgled** — isti razlog, korisnik želi da se deaktivirano vidi i unutar sekcije; **brisanje starih pricing/offer/rent/pdf_probe naloga** — korisnik odbio: „ne želim opciju brisanja naloga jer je plan da imam evidenciju šta je ko radio, samo ću da ih deaktiviram"; **delete dugme u UI-ju** — protivno istoj odluci i postojećem pravilu „users are deactivated, never deleted"; **deploy preko Dev→main + CI + deploy.sh** — korisnik je za ovaj put izabrao lokalni rebuild jer je brži; dokumentovani pull-deploy ostaje standard za sledeći release.
## Consequences

Dobijeno: deaktivirani nalozi su nedvosmisleno vidljivi i reaktivacija radi iz istog reda; admin nalozi se više ne mogu „zaglaviti" deaktivirani. Cena: dve tabele umesto jedne (stranica je i dalje ~1.7 MB zbog dropdown-a sa 2.156 kontakata — postojeći problem, nije rešavan ovim zahvatom), sekcija „Deactivated users" se renderuje i kad je prazna (radi otkrivljivosti), i korisnik i dalje ručno deaktivira stare naloge — agent ih nije dirao. Negativna garancija: brisanje korisnika nije implementirano nigde (nema rute), a `pdf_probe` je vraćen u aktivno stanje posle verifikacije. Lokalni rebuild znači da About tab i `backups/last-deployed-tag` neće pokazati novi CI tag dok se ne uradi pravi pull-deploy.

