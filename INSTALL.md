# 📦 Instalacija — QP-CRM (Docker)

Najlakši način da pokreneš QP-CRM: skineš gotov image sa GitHub-a i startuješ.
**Ne treba ti git niti bilo kakav build** — samo Docker.

---

## Šta ti treba

- Linux server ili računar (Ubuntu/Debian — testirano na Ubuntu 24.04)
- **Docker Engine** + **Compose v2 plugin**:
  ```bash
  sudo apt install docker.io docker-compose-v2
  sudo usermod -aG docker $USER    # da ne koristiš sudo za docker; odjavi se pa se ponovo prijavi
  docker --version && docker compose version   # provera
  ```

---

## Instalacija (3 koraka)

### 1. Pripremi folder

```bash
mkdir qp-crm && cd qp-crm
```

Preuzmi [docker-compose.yml](https://github.com/lakisan1/QP-CRM/blob/main/docker-compose.yml)
i [`.env.example`](https://github.com/lakisan1/QP-CRM/blob/main/.env.example)
iz repozitorijuma (klikni fajl → *Raw* → sačuvaj u `qp-crm/` folder),
ili ako imaš git:

```bash
git clone https://github.com/lakisan1/QP-CRM.git
cd QP-CRM
```

### 2. Podesi tajne ključeve (`.env`)

```bash
cp .env.example .env
```

Otvori `.env` i popuni **svih šest** ključeva (koriste se za potpisivanje
sesija — svaki mora biti jedinstven nasumičan heks):

```bash
# za svaki ključ generiši vrednost ovako:
python3 -c "import secrets; print(secrets.token_hex(32))"
```

```ini
PRICING_SECRET_KEY=< nalepi generisano >
OFFER_SECRET_KEY=< nalepi generisano >
RENT_SECRET_KEY=< nalepi generisano >
ADMIN_SECRET_KEY=< nalepi generisano >
SALE_SECRET_KEY=< nalepi generisano >
SETTINGS_SECRET_KEY=< nalepi generisano >
```

> 💡 Za pristup samo preko nginx-a (HTTPS + domen) pogledaj sekciju
> `nginx reverse proxy` u [DOCKER.md](DOCKER.md).

### 3. Startuj

```bash
docker compose up -d
```

Prvo startovanje skine image sa GitHub Container Registry-ja
(`ghcr.io/lakisan1/qp-crm:latest`) i kreira bazu. Sačekaj ~1 min pa proveri:

```bash
docker compose ps    # treba: STATUS = Up (healthy)
```

Otvori **http://<ip-servera>:5000** u browseru. Gotovo! 🎉

---

## Prva prijava

| Nalog | Početna šifra |
|---|---|
| `admin` | `Admin1` |

**Obavezno promeni šifru odmah** — Admin → Users. Nema drugih default naloga;
sve zaposlene dodaješ sam u Admin → Users.

---

## Šta gde živi (podaci)

| Folder na serveru | Sadržaj |
|---|---|
| `app_data/` | baza (`pricing.db`) — korisnici, šifre, ponude, ugovori + slike proizvoda |
| `app_assets/` | logo, favicon, footer slike |
| `static/img/` | uploadovani logo |

Sve je **van image-a** — update nikad ne gubi podatke.

## Backup

Admin panel → **System Backup & Maintenance** → *Download Full System Backup (.zip)*
(baza + slike zajedno). Radi i dok app radi.

---

## Update

Pogledaj [UPDATE.md](UPDATE.md) — update je jedna komanda (`./deploy.sh`),
sa automatskim backup-om i rollback-om.
