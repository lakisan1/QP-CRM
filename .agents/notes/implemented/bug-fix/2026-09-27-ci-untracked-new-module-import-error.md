# Agent Note: ci-untracked-new-module-import-error

Status: implemented

## Problem

CI na main je dva puta uzastopno pao sa "Process completed with exit code 2" za ~30s (runovi 36317069903 i 36318077047), dok je isto drvo lokalno prošlo 513/513 u kontejneru. Kolektivni test-suite je prolazio na dev mašini pa je failure delovao kao CI flake; deploy novog batch-a je bio blokiran bez vidljivog uzroka (logovi nedostupni anonimno, 403).

## Decision

CI reprodukcija se radi fresh-clone buildom: git clone u privremeni dir, checkout crveni commit, docker build, pytest u kontejneru. To je reprodukoalo tačan CI failure (22 collection errors: ImportError qp_crm.services.order_service) dok je lokalni disk-build prolazio, jer lokalni disk ima fajl a checkout nema. Commit disciplina promenjena: novi moduli se commit-uju sa git add celog direktorijuma novog paketa (qp_crm/orders/ qp_crm/services/order_service.py), ne ručnom enumeracijom koja može preskočiti fajl; verifikacija pre push-a main je git status + ls-files za svaki novi fajl batch-a. Uz to, vremenski podatak: CI total 27–40s sa gha cache znači pytest je umro na collection-u (exit 2), nikad nije stvarno pokrenuo testove — zeleni run traje 45–60s.
## Alternatives considered

**Ručno listanje fajlova u git add uz pažnju** — upravo izgubio: to je tačno što je napravljeno (git add sa eksplicitnom listom u batch-B commitu) i preskočilo je novi modul. **git add -A za batch commite** — funkcionalno ali gaži disciplinu "commit poruka prati fajlove"; bolja zaštita je fresh-clone build kao CI proxy. **Proširenje CI-a sa fresh-clone smoke korakom pre pytest-a** — razmatran i odložen: kost ~40s dodatnog runner vremena po run; umesto toga, reprodukcija se radi ručno tek kad CI crven (dokazano: 10 minuta od crvene do zeleno sa tačnim uzrokom). **Re-run CI bez dijagnoze** — proban implicitno (empty commit) i izgubio: dva uzastopna crvena runa sa istim exit kodom; re-run ne čisti strukturne greške.
## Consequences

Kupio: CI ponovo gradi pouzdano (run ec19f03 success), a disciplina "nikad ne enumerisati fajlove ručno u batch commitu kad se uvodi NOVI modul" je dokumentovana; fresh-clone reprodukcija je sada dokazana metoda koja razdvaja CI-flake od strukturne greške za ~10 min. Platio: Dockerfile nosi CACHE_BUST arg koji je ostao (bezopšten, ali u istoriji dva crvena runa i jedan cache-bust commit). Negativna garancija: ovo NIJE bila gha cache flake — cache-bust je ostao u Dockerfile-u i bez dejstva; ako se opet pojavi brzi CI exit 2, prvi korak je proveriti git ls-files vs disk za nove module, ne cache. Import-chain svake nove app mora biti pokriven barem jednim testom koji importuje qp_crm.main (smoke suite to radi — zato je pao).

