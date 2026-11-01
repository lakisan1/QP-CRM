# Agent Note: device-table-from-pricelists

Status: implemented

## Problem

Korisnik ima ~112 Excel fajlova (cenovnici i kalkulacije Hofmann/Marinković-Hofmann 2023–2026) rasutih po prilozima i traži jedan konsolidovan katalog uređaja sa opisima koji će ručno, postepeno unositi kao proizvode u QP-CRM. Prethodna sesija je pukla na ask_user_question petlji lokalnog modela; odluke su nakon toga zaključane u tmp-excel/START-HERE.md §2 i trebalo ih je primeniti bez daljih pitanja. Izvori imaju ~10 različitih struktura (kalkulacije sa NAZIV-headerom, cenovnici sa sekcijama i brend-podnaslovima, NUSSBAUM EN sheet od reda 48, agregirani Katalog uredjaja), plus đubre: imena kupaca u NAZIV koloni, telefoni, goli kataloški brojevi, sekcijski naslovi.

## Decision

tmp-excel/build_table.py obrađuje sve Excel fajlove iz /home/dsh/.dsh/attachments/v1/files/<2>/<hash>/<ime> (trostruki os.listdir hod — glob ne radi zbog hash direktorijuma): openpyxl za .xlsx, xlrd 2.0.1 preko PYTHONPATH=/tmp/xlrd-extract/usr/lib/python3/dist-packages za .xls. Specijalni tretmani: Uredjaji_iz_ponuda.xlsx čita 'Katalog uredjaja' (naziv=col B, familija=col A) + 'Stavke (sirove)' (col E); NUSSBAUM cenovnik samo EN sheet od reda 48 (Description col C, brand kontekst NUSSBAUM); ADAS kalkulacije čitaju naziv iz col B kad je col A čist broj; CENOVNIK SAJAM/RENT SIMA prate sekcije 'N. NASLOV' kao kategoriju i brend-podnaslove kao brand kontekst; generički fajlovi čitaju col A ispod NAZIV-headera i odbacuju redove bez ijedne numeričke ćelije (zaglavlja sekcija). Filteri đubreta: telefon/kataloški broj ([0-9+/ -\.]{8,} sa ≥8 cifara), goli brojevi bez slova, prekratko <3 znaka, sekcijski naslovi (exact-normalized lista), pravna lica (\bdoo\b|d.o.o.|\ba.d.\b|preduzeće — '&' uklonjen iz patterna jer je presecao stvarne proizvode 'Set za čišćenje AD BLUE sistema'). Spajanje: konzervativan ključ (lowercase, bez interpunkcije .,;:()[]„""'', – — → -, višestruki razmaci) — Geodyna 7340 ≠ Geodyna 7340 S ostaje razdvojeno. Naziv za prikaz: najčešća varijanta, nerešeno → mešovita velika/mala pa najduža. Opisi hibridni: exact-normalized lookup u mh-products-baseline-by-category.xlsx (146 pogodaka → 'izvor', URL/emoji/[pic] čišćenje), inače generisan minimalni opis ('generisan': bold tip+naziv, PROIZVODJAC ako detektovan, bulleti samo iz naziva — prečnik felne 13–26'' za mašine guma/balansirke, EV/truck/touch/SmartSpeed flagovi). Brend detekcija preko ~50 token-lista; Hofmann familija (geodyna/geoliner/monty/safelane/duolift/variolift/quatrolift/easymont) → HOFMANN kao proizvođač. Tip uređaja: familija → tip mapa + regex pravila po nazivu, sa izuzetkom 'dodatak ZA familiju' ('Stezač točka za Geodyna' nije balansirka). Izlaz tabela-uredjaja.xlsx: Uredjaji (≥2 pojavljivanja, sortiran po broju opadajuće), Singlovi (iskljuceni), Odbaceno (Naziv/Razlog/Izvor), Sumarno; zamrznut header, wrap text na Opis, širine kolona. Negativne garancije: nema cena ni URL-ova u opisima (QC provera = 0 pogodaka), max opis 1999 znakova, pricing.db netaknut, nema uvoza u bazu, attachments dir samo-čitaj.
## Alternatives considered

**Fuzzy spajanje varijanti naziva** (npr. „Mašina za balansiranje točkova HOFMANN GEODYNA 7340S" vs „Geodyna 7340 S") — odbijeno: START-HERE.md §5 eksplicitno kaže da je van obima i da je „bolje propustiti duplikat nego pogrešno spojiti dva proizvoda". Posledica: ~15 varijanti Geodyna 7340 ostaje kao zasebne grupe; korisnik ih ručno spaja pri unosu.

**Fuzzy poklapanje sa baseline opisima** — odbijeno: samo exact-normalized ključ (144/1262 katalog redova ima opis iz izvora). Agresivnije poklapanje bi unosilo opise sličnih ali različitih proizvoda.

**Korišćenje mh-baseline kao izvora pojavljivanja** — odbijeno: baseline je derivat istih ponuda (ima source_count kolonu), pa bi duplo brojao. Koristi se isključivo kao opis-lookup (528 unosa).

**Izmišljeni CRM kategorije za familije** — odbijeno: prvobitno mapiranje familija na izmišljene CRM kategorije krši „ništa se ne izmišlja". Kategorija = familija iz Katalog uredjaja verbatim; Hofmann familije (Geodyna/Geoliner/Monty) se mapiraju iz naziva po CRM konvenciji.

**Čitanje .msg preko python-msg biblijske** — nije instalirana; umesto toga raw UTF-16LE dekodovanje OLE fajla. MSG sadrži samo 8 akcijskih redova (GEODYNA/MONTY/GEOLINER zimska akcija) koji već postoje u Excel fajlovima — preskočen bez gubitka podataka.
## Consequences

Kupljeno: pouzdan, reprodukibilan katalog sa 100% QC poklapanjem sirovi=tabela+singlovi+odbačeni; korisnik dobija i jednokratne stavke (ne gubi ništa) i razlog odbacivanja za svaki red. Cena: 2012 glavnih stavki sadrži varijante istog uređaja koje će korisnik ručno spajati pri unosu (~45 već postoji u bazi po HANDOFF analizi); generisani opisi su minimalni (naziv+tip+brend) pa ~92% redova traži dopunu opisa pri unosu. Skripta je jednoprolazna i deterministička — ponovno pokretanje daje isti izlaz. pricing.db i QP-CRM aplikacija nisu dirani.

