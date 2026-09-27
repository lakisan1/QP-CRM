# Agent Note: catalog-wide-pickers

Status: implemented

## Problem

Korisnik je video da Oprema registar prikazuje sve uređaje iz Cenovnika, ali picker-i na Ulaz/Izlaz i Narudžbine samo proizvode sa uključenim praćenjem — nepraćeni proizvodi nisu mogli da se unesu u magacin ni naruče dok se režim praćenja ručno ne uključi u Cenovniku (P5 opt-in gate postao friction u svakodnevnom unosu).

## Decision

wh.catalog_products() vraća sve proizvode; nepraćeni dolaze sa effective_regime='qty' (CASE u SQL-u) tako da forma za njih prikazuje količinsku sekciju. Intake ruta i orders/new koriste catalog_products(); Stanje i Pokrivenost ostaju na tracked_products() (display filter). U servisima record_movement/intake_inbound/outtake untracked proizvod se knjiži kao qty umesto odbijanja; jedina preostala brana je serialized proizvod na količinskom putu (odbija se — unos ide po serijskim brojevima). Režim praćenja u Cenovniku ostaje izbor prikaza/organizacije, ne uslov za unos.
## Alternatives considered

**Auto-uključivanje praćenja pri prvom unosu (flip tracking_regime u qty)** — odbijen: tiho menja podatke proizvoda i Stanje/Pokrivenost prikaz bez korisnikove odluke; effective_regime u picker payload-u postiže isto ponašanje forme bez mutacije. **Zadržati gate uz poruku 'uključi praćenje'** — odbijen: upravo friction koji je korisnik prijavio; magacioner ne sme da ide u Cenovnik da bi uneo kamion. **Prikazati nepraćene kao [bez praćenja] sa posebnim tretmanom** — odbijen: tri koncepta u jednoj formi zbunjuju; forma zna samo dve sekcije (količina / serijski).
## Consequences

Kupio: picker-i na Ulaz/Izlaz i Narudžbine sadrže ceo Cenovnik (isti mentalni model kao Oprema registar); unos više ne zahteva prethodno uključivanje praćenja — magacioner knjiži kamion bez izleta u Cenovnik. Platio: gubitak P5 'opt-in' garancije da knjiga sadrži samo svesno praćene proizvode — količine nepraćenih proizvoda sada postoje u stock_movements i utiču na qty_on_hand ( Stanje ih i dalje NE prikazuje jer je tracked-only filter: nevidljivo stanje za nepraćene je poznata posledica, prihvaćena po korisnikovom izričitom zahtevu). Negativna garancija: serialized na qty putu i dalje odbijen (unos ide po komadu); Stanje i Pokrivenost ostaju tracked-only; ako korisnik poželi da vidi i nepraćene u Stanju, to je novi prikaz, ne ovaj scope.

