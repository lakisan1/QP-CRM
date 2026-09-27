# 📦 Install — QP-CRM (Docker)

The easiest way to run QP-CRM: pull the ready-made image from GitHub and start it.
**No git and no build needed** — just Docker.

---

## What you need

- A Linux server or computer (Ubuntu/Debian — tested on Ubuntu 24.04)
- **Docker Engine** + **Compose v2 plugin**:

  ```bash
  sudo apt install docker.io docker-compose-v2
  sudo usermod -aG docker $USER    # run docker without sudo; log out and back in once
  docker --version && docker compose version   # check
  ```

---

## Installation (3 steps)

### 1. Prepare a folder

```bash
mkdir qp-crm && cd qp-crm
```

Download [docker-compose.yml](https://github.com/lakisan1/QP-CRM/blob/main/docker-compose.yml)
and [`.env.example`](https://github.com/lakisan1/QP-CRM/blob/main/.env.example)
from the repository (open the file → *Raw* → save into the `qp-crm/` folder),
or — if you have git:

```bash
git clone https://github.com/lakisan1/QP-CRM.git
cd QP-CRM
```

### 2. Set up the secret keys (`.env`)

```bash
cp .env.example .env
```

Open `.env` and fill in **all six** keys (they sign sessions — each must be a
unique random hex string):

```bash
# generate each value like this:
python3 -c "import secrets; print(secrets.token_hex(32))"
```

```ini
PRICING_SECRET_KEY=< paste generated value >
OFFER_SECRET_KEY=< paste generated value >
RENT_SECRET_KEY=< paste generated value >
ADMIN_SECRET_KEY=< paste generated value >
SALE_SECRET_KEY=< paste generated value >
SETTINGS_SECRET_KEY=< paste generated value >
```

> 💡 For access through nginx only (HTTPS + domain), see the
> `nginx reverse proxy` section in [DOCKER.md](DOCKER.md).

### 3. Start

```bash
docker compose up -d
```

The first start pulls the image from GitHub Container Registry
(`ghcr.io/lakisan1/qp-crm:latest`) and creates the database. Wait ~1 min, then check:

```bash
docker compose ps    # STATUS should show: Up (healthy)
```

Open **http://<server-ip>:5000** in your browser. Done! 🎉

---

## First login

| Account | Initial password |
|---|---|
| `admin` | `Admin1` |

**Change the password immediately** — Admin → Users. There are no other
default accounts; create every staff user yourself in Admin → Users.

---

## Where your data lives

| Folder on the server | Contents |
|---|---|
| `app_data/` | database (`pricing.db`) — users, passwords, offers, contracts + product images |
| `app_assets/` | logo, favicon, footer images |
| `static/img/` | uploaded logo |

All of it is **outside the image** — updates never lose any data.

## Backup

Admin panel → **Backup** tab:
* **Create quick backup** — one-click DB snapshot stored on the server (restore points, one-click restore)
* **Download Full System Backup (.zip)** — database + images + assets, for manual copies on other servers or migration

---

## Updating

See [UPDATE.md](UPDATE.md) — updating is one command (`./deploy.sh`),
with an automatic pre-deploy backup and rollback. Fully unattended
updates (Watchtower) are covered there too.
