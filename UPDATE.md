# 🔄 Update — QP-CRM (Docker)

Update menja **samo kod** (image). Tvoji podaci — korisnici, šifre, ponude,
ugovori, slike — su u folderima na serveru (`app_data/`, `app_assets/`,
`static/img/`) i **nikad ne bivaju dirnuti**.

---

## Način 1 — Ručno (jedna komanda) ✅ preporučeno

U folderu gde je `docker-compose.yml` i `deploy.sh`:

```bash
git pull          # skine novi deploy.sh/compose ako je menjan (opciono)
./deploy.sh
```

`deploy.sh` automatski:
1. napravi **backup baze** → `backups/pre-deploy-<datum>.db` (ako backup ne uspe, update se prekida — ništa ne dira)
2. zapamti trenutnu verziju → `backups/last-deployed-tag` (rollback tačka)
3. skine novi image (`docker compose pull`)
4. restartuje kontejner na novi image
5. čeka healthcheck (~90 s) i izveštava

Ako piše `qp-crm is healthy` — update je uspeo. Gotovo.

### Ako nešto pođe naopako — rollback

```bash
./rollback.sh
```

Vraća na verziju koja je radila pre update-a (i njoj pravi backup pre
vraćanja). Podaci ostaju kako jesu. Kad stigne ispravljena verzija, ponovo
`./deploy.sh`.

> Skripte rade i offline od gita: image se skida sa
> `ghcr.io/lakisan1/qp-crm:latest`, ne gradi na serveru — server ne treba
> da ima build kapacitete.

---

## Način 2 — Automatski (Watchtower) 🤖

Želiš li da se update dešava **sam**, bez da iko pokreće bilo šta?
[Watchtower](https://containrrr.dev/watchtower/) je mali pomoćni kontejner
koji periodično proverava da li postoji novi image i, ako ima, uradi tačno
ono što `deploy.sh` radi (pull + recreate).

### Podešavanje (jednom)

Kreiraj fajl `docker-compose.override.yml` **pored** glavnog
`docker-compose.yml` (repo već sadrži primer: `watchtower-compose.example.yml`)
sa sledećim sadržajem:

```yaml
services:
  watchtower:
    image: containrrr/watchtower
    container_name: watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      # (opciono) Docker login za PRIVATAN image — za javan image NE treba:
      # - ~/.docker/config.json:/config.json:ro
    environment:
      # provera svaki dan u 04:00; može i `@hourly`, `@daily`, `@weekly`...
      - WATCHTOWER_SCHEDULE=0 0 4 * * *
      # posle update-a skini stari image (čuvari disk)
      - WATCHTOWER_CLEANUP=true
      # restartuj SAMO kontejnere sa labelom (ne dira ostatak mašine):
      - WATCHTOWER_LABEL_ENABLE=true
    labels:
      # Watchtower prati SAMO kontejnere označene ovom labelom:
      - com.centurylinklabs.watchtower.enable=true
```

> ⚠️ Napomena: `WATCHTOWER_LABEL_ENABLE=true` znači da Watchtower update-uje
> SAMO kontejnere koji imaju labelu `com.centurylinklabs.watchtower.enable=true`.
> Primer iz repozitorijuma (`watchtower-compose.example.yml`) već uključuje
> i tu labelu na `app` servisu — ako ručno pišeš override, dodaj i nju:
>
> ```yaml
> services:
>   app:
>     labels:
>       - com.centurylinklabs.watchtower.enable=true
> ```

Startuj:

```bash
docker compose up -d
```

Od tada: svaki novi image na `ghcr.io/lakisan1/qp-crm:latest` (koji CI
pushuje tek kad prođu svi testovi) se automatski skida i primenjuje noću u 04:00.

### Zašto je ručni način ipak "sigurniji"

Automatika je zgodna, ali:
- update stiže **bez da biraš trenutak** (radno vreme vs. noć)
- rollback i dalje postoji (`./rollback.sh`), ali moraš sam primetiti problem

Preporuka: **ručno** na produkcijskoj instanci (`./deploy.sh` kad god čuješ
za novu verziju), **automatski** na test/tim instanci.

---

## Šta update NE radi

- **Ne dira podatke** — baza, šifre, ponude, slike su na disku van image-a
- **Ne menja `.env`** — tvoji tajni ključevi ostaju kako su
- **Ne briše stare verzije** — `rollback.sh` može uvek nazad na prethodnu
  (stare image-ove čistiš ručno: `docker image prune -f`)

## Česte situacije

| Situacija | Rešenje |
|---|---|
| `deploy.sh` piše *backup FAILED* | Ne dira ništa — proveri prostor na disku (`df -h`), pa ponovo pokreni |
| Update na pola (kontejner unhealthy) | `./rollback.sh` — vraća prethodnu verziju |
| `git pull` greška (lokalne izmene) | Upiše upozorenje i nastavi — bitno je samo da image bude skinut |
| Hoću baš određenu verziju | `./rollback.sh sha-<commit>` (tag sa svakog builda) |

## Update kroz admin panel (dugme u UI)?

Namerno **nema** dugmeta za update u admin panelu. Kontejner ne bi mogao
bezbedno da zameni sam sebe (kontejner koji restartuje sebe ubija proces
koji update-uje — update bi ostao na pola puta). Skripte sa servera su
pouzdan način: `./deploy.sh` (ili Watchtower za potpunu automatiku).
