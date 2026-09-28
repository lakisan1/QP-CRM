# Agent Note: offer-form-picker-contact-link-lost

Status: implemented

## Problem

U ponudi (offer) kad se na edit strani promeni musterija preko step-1 pickera, link ka Imeniku (offers.contact_id) se gubi pri snimanju. JS u offer_form.html je bio copy-paste iz rent forme: `document.getElementById('picked-contact-id').value = id && id.startsWith('c') ? id.slice(1) : ''`. Rent forma zaista ima opcije `c<id>` (rent/routes/contracts.py:109 `f"c{row['id']}"`), pa joj stripovanje 'c' radi; offer picker pak puni opcije iz `contact_service.directory_choices()` koje vraća ČISTE integer id-jeve (bez 'c'). Zato se hidden `#picked-contact-id` uvek postavljao na '' — contact_id se pri svakom snimanju praznio (NULL), iako je client_name bio ispravno popunjen preko fetch-a `/offer/api/contact/<id>`. Posledica u UI: posle snimanja selected_contact_id=None → dropdown prazan → musterija polja sakrivena gate-om (applyGate) → korisnik vidi „musterija obrisana" i ponovo bira, u krug. Potvrđeno na živoj bazi: offer 115 (P-1251) ima client_name='"AS GAS-PROM" D.O.O' ali contact_id=NULL, dok offer 114 (P-1250) ima contact_id=2160.

## Decision

`qp_crm/offer/templates/offer/offer_form.html` (change handler pickera) sada čuva sirovi id: `if (hidden) hidden.value = id ? (id.startsWith('c') ? id.slice(1) : id) : '';` — za čist id (npr. "2160") ostaje "2160", za eventualni 'c<id>' (defanzivna parnost sa rent) skine 'c', a prazan izbor postavlja '' (unlink). Fetch linija `const cid = id.startsWith('c') ? id.slice(1) : id;` je već bila ispravna za čiste id-jeve i nije menjana. Server-side logika je bila i ostaje ispravna — `new_offer`/`edit_offer` čitaju `request.form.get("contact_id", type=int)` i čuvaju link (test test_offer_party_picker_roundtrip to dokazuje). Bug je isključivo klijentski: hidden polje nije dobijalo vrednost. Negativne garancije: rent forma nije dirana (njene opcije jesu 'c<id>' i njen JS je ispravan); nema auto-repair već pokvarenih redova (contact_id NULL sa postavljenim client_name) — korisnik ih popravi jednim ponovnim izborom musterije i snimanjem.
## Alternatives considered

**Promeniti `directory_choices()` da vraća 'c<id>' (paritet sa rent)** — odbijeno: razbilo bi template poređenje `selected_contact_id == contact_id` (int vs str), server-rendered vrednost hidden polja, `/offer/api/contact/<int:contact_id>` int konverter i test koji asertuje `value="{cid}"` sirovo; popravka na JS strani je najmanja i ne dira API ugovor. **Backfill contact_id=NULL redova po client_name** — odbijeno: van opsega prijave; već postoji `link_documents_to_contacts` za to, a pokvareni redovi su posledica, ne uzrok. **Popraviti samo server da toleriše 'c' prefiks u contact_id** — odbijeno: server već radi; problem je što klijent šalje praznu vrednost, ne pogrešan format.
## Consequences

Kupljeno: izbor musterije preko pickera sada čuva i offers.contact_id, pa posle snimanja dropdown ostaje selektovan i musterija polja vidljiva (nema više „obrisane musterije" petlje). Cena: popravka je klijentski JS u šablonu, a šabloni su bake-ovani u GHCR image (compose bind-mountuje samo app_data/app_assets/static/img, NE kod) — da bi bila vidljiva na tekućoj instanci potreban je deploy (pull + recreate), isto kao za svaku kod-promenu. Već pokvareni redovi (contact_id NULL, client_name postavljen) nisu auto-popravljeni — jednom se ponovo izabere musterija i snimi. 19 karakterizacionih testova (directory_unification + musterija_first_ux) prolazi: testovi vežbaju server-side POST sa contact_id, ne klijentski JS, pa nisu ni hvatali ovaj bug.

