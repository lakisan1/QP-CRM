# Agent Note: legacy-backup-conversion-restore

Status: implemented

## Problem

Korisnik je dostavio FULL_SYSTEM_BACKUP_2026-09-22.zip — backup STARE pre-Phase-3 verzije (legacy plaintext {app}_password ključevi u global_settings, nema users/user_modules/api_keys/login_audit tabela, nema contacts trio, nema site_products, nema novih kolona). Tražio je konverziju u aktuelnu šemu i učitavanje kao test podataka u lokalnu verziju. Postojao je rizik: produkcioni podaci bi se izgubili zamnom, a konverzija ručnim SQL-om bi driftovao od boot migracija koje su jedini izvor istine.

## Decision

Procedura (ponovljiva, dokumentovana ovde): (1) WAL-safe sqlite3.backup() kopija žive baze + tgz slika u backups/ sa timestampom; (2) staging sandbox /tmp: raspakovati zip, ukopirati pricing.db + product_images + app_assets; (3) pokrenuti REALNI boot sekvens (pricing_init_db → pricing_migrate_schema → offer_init_db → admin_init_db → rent_init_db → contacts_init_db) sa config patch-om pre app import-a — to dodaje users/user_modules/api_keys/api_audit/login_audit, contacts trio, site_products, sve ALTER kolone (uklj. nove website_url/manufacturer_url), kopira rent_clients→contacts sa 'client' rolom, seeduje admin iz legacy 'admin_password' vrednosti i scrubuje legacy ključeve; (4) ručno počistiti 'quotation_password' (nije u LEGACY_PASSWORD_KEYS) i retired 'api_key' red; (5) postaviti poznatu admin šifru + sačuvati realne staff naloge iz pre-restore backupa (zorica: contacts/offer/sale grantovi, stale 'deals' uklonjen); (6) PRAGMA integrity_check, docker stop → cp baze + images → docker start, healthcheck; (7) HTTP verifikacija kroz živi server (login, products pretraga, offers, contacts, PDF-ovi). Verifikovano na živom serveru: 253 proizvoda, 77 ponuda, offer PDF custom-template branch (417KB) i rent document PDF rade na konvertovanim podacima.
## Alternatives considered

**/admin/restore_full UI ruta.** Postoji i radi (sa auth re-init pozivom), ali radi SNIMANJE upload-a preko žive baze dok app piše u nju i zahteva admin password u formi; pre swap-a bismo izgubili današnje produkcione podatke bez spoljnog backup-a. Ručni swap uz `docker stop` prvo je deterministički i bezbedan.

**Ručna SQL konverzija skriptom (CREATE novih tabela + INSERT SELECT).** Duplira logiku koju boot migracije već rade idempotentno (ALTERs, contacts backfill, users seed) i rizikuje šema-drift — svaka buduća migracija bi morala biti odražavana na dva mesta. Korišćenje realnog boot sekvence znači da konvertovana baza prolazi kroz IDENTIČAN kod kao produkcija pri svakom boot-u.
## Consequences

Bought: stari podaci (253 proizvoda + slike, 77 ponuda, 213 stavki, 152 cene, 4 ugovora, custom 'MarinkovicHofmann' PDF template) sada žive u aktuelnoj appi bez ijedne ručne SQL izmene; proces je ponovljiv za svaki budući stari backup (stage → boot → swap). Cost: produkciona baza je sada TEST sadržaj (stari backup, ne današnje stanje) — današnje produkcione stanje (1 test product, admin+zorica) živi samo u backups/pricing.db.pre-legacy-restore.*.bak; 'quotation_password' legacy ključ nije bio u LEGACY_PASSWORD_KEYS pa je izbačen ručno (bez toga bi ostao kao plaintext u global_settings); admin šifra morala biti ponovo postavljena jer restore nosi legacy 'admin1' hash.

