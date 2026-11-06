# Agent Note: api-v1-admin-session-bypass

Status: implemented

## Problem

Korisnik prijavljuje: kao ulogovan admin, odlazak na /pricing/products/product_sync prikaže „Your account has no pricing app access." Strana se adminu normalno renderuje (web require_module gate propušta admina kao superset), ali njen JS poziva /api/v1/sync/table i /api/v1/sync/* bez Bearer header-a, oslanjajući se na session fallback u require_api_key(); taj fallback je zahtevao `user_has_module(user_id, 'pricing')`, a admin-role korisnici nikad ne dobijaju user_modules redove — pa je svaki sync poziv vraćao 403 i strana je prikazivala tu grešku.

## Decision

require_api_key() u qp_crm/pricing/api_v1.py sada u session fallback-u preskače proveru granta kad je `user["role"] == "admin"` (`if user["role"] != "admin" and not user_has_module(user_id, "pricing")`), čime se API ponaša identično web require_module() gate-u: admin rola je superset i otvara svaki modul bez user_modules reda. Bearer-key autentifikacija je netaknuta — per-user ključ i dalje nema module proveru (postojeće ponašanje). Regresioni test tests/auth/test_api_keys.py::test_api_v1_session_fallback_admin_bypasses_app_grant briše SVE adminove user_modules redove, pa dokazuje da je bypass po roli a ne po grantu, i pinuje 200 za /api/v1/products, /api/v1/sync/table i samu /pricing/products/product_sync stranu dok staff-bez-granta 403 ostaje u postojećem testu. Isporučeno na :5000 lokalnim rebuild-om image-a (container healthy; md5 api_v1.py u kontejneru = repo); ceo suite 561 passed / 3 skipped.
## Alternatives considered

**Skinuti grant-check sa session fallback-a u celini** — API bi tada propuštao svakog ulogovanog korisnika (i staff bez pricing pristupa) na /api/v1, što je širi pristup nego što UI dozvoljava; odbijeno. **Dati admina kroz user_modules grant red** — ne odgovara modelu (admin rola je superset i nikad ne dobija grant redove; test je to i dokazao brisanjem redova), a i zahtevalo bi seed/migraciju i tiho kršenje „admins bypass grants" pravila. **Poseban `user_has_module_or_admin()` helper u shared/auth.py** — čisto rešenje, ali za sada postoji samo jedan pozivalac sa ovim problemom; helper bi dodao API površinu bez drugog korisnika. Pravi refaktor na `require_module`-kompatibilan helper može doći kad još neki API endpoint bude tražio modul-proveru.
## Consequences

Dobijeno: product_sync strana (i svaki budući /api/v1 poziv iz first-party JS-a) radi za admina bez lažnog 403; audit log i dalje beleži admina kao korisnika (kind='user', status 200). Cena: session fallback i web gate sada imaju dve kopije istog pravila „admin je superset" (jedna u require_module, jedna u require_api_key) — buduća izmena pravila mora dirati oba mesta; Bearer-key put i dalje NEMA module proveru (postojeće ponašanje, nije dirano). Negativna garancija: staff bez pricing granta i dalje dobija tačno isti 403 (test to pinuje), a admin sa uklonjenim SVIM user_modules redovima prolazi — bypass je po roli, ne po podacima.

