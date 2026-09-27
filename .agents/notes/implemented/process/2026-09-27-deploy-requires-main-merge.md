# Agent Note: deploy-requires-main-merge

Status: implemented

## Problem

Korisnik traži redeploy da bi video P5 Magacin, ali GHCR :latest image je potiho zastareo: CI gradi image samo iz main grane, a sav aktuelni rad (P5 Magacin, imenik model, backup tab, update v2 — 43 commit-a) živi na Dev grani koju niko nije merge-ovao u main od 23. septembra. Deploy.sh je uspešno "deployovao" 4-dnevno-stari image i healthcheck je prošao — ništa u procesu nije signalizovalo da novi kod NIJE u image-u. Rizik: svaki budući "redeploy" dok rad bude samo na Dev-u ponoviće ovu grešku.

## Decision

Produkcioni deploy ide isključivo preko CI-građenog GHCR image-a: merge ciljne grane u main (ovaj put direktan push deploy-main:main = 5b61a74, po korisnikovoj odluci), čekati CI success (pytest + coverage gate + push latest/sha- tagova), pa tek onda sudo ./deploy.sh. Lokalni suite run (venv/bin/pytest) pre push-a main-a je obavezan korak. Verifikacija posle deploy-a mora da bude container-side (docker exec: fajl md5 vs repo, url_map ruta, prod DB tabele), nikad ne zaključak iz lokalnog repo stanja. Dev grana je radna i OSTAJE nepushovana dok se ne merge-uje — "Everything up-to-date" na Dev push-u je znak da rad NIJE u main-u, ne potvrda deploy-a.
## Alternatives considered

**PR Dev→main sa review-om** — izgubio jer korisnik eksplicitno izabrao "Direktno push u main" kada je upitan; repo je solo-dev (PR #106 je i ranije bio samo merge-vozilo), a deploy-kanal i dalje prolazi kroz CI kapiju. **Lokalni docker build + up --build** — odbijen i ranije i sada: zaobilazi pytest kapiju, pravi image koji rollback.sh ne zna da vrati, i kvari pull-deploy model update sistema v2. **Čekati da korisnik ručno merge-uje** — odbijen jer je korisnik tražio da agent izvede deploy; čekanje bi ostavilo produkciju na starom image-u bez potrebe.
## Consequences

Kupio: produkcija (192.168.1.34:5000) sad ima kompletan P5 Magacin (12 ruta, 9 templejta, product_aliases) i sve do tada nepushovane popravke; rollback tačka je sha-5b61a74; pre-deploy backup na mestu. Platio: main sad sadrži board/notes commite (nije štetno, ali main više nije "samo release" granica), a 40-minutni deploy gap je nastao jer Dev nije bio pushovan na vreme — disciplina "merge u main kad korisnik traži deploy" je sada operativni običaj. Negativna garancija: /warehouse/ (samo trailing slash) i dalje vraća 404 jer warehouse rute nemaju strict_slashes normalization; sve stvarne rute (/warehouse/equipment, /coverage, /movements, /reservations) rade — landing kartica vodi ispravno. Ako korisnik ponovo prijavi "nema izmena", PRVI korak dijagnoze je provera GHCR tag liste i CI run istorije, ne deploy.

