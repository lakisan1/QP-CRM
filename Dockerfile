# QP-CRM — production image (Phase 0, P0-T3).
#
# One image serves the whole multi-app stack: gunicorn runs wsgi.py
# (wsgi:application), whose DispatcherMiddleware merges pricing / offer /
# rent / admin / sale / settings on port 5000.
FROM python:3.12-slim

# WeasyPrint renders the offer/rent PDFs — these are the same system libs
# run_apps.sh installs on bare metal (the PKGS list), plus tzdata so
# TZ=Europe/Belgrade actually resolves. This also fixes machines where
# bare-metal boot failed on the missing libpango.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz-subset0 \
        libgdk-pixbuf-2.0-0 \
        libcairo2 \
        shared-mime-info \
        fonts-dejavu-core \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Europe/Belgrade \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first: this layer only rebuilds when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code. Build-context junk (venv, .git, PDFs, scratch scripts,
# app_data, .env, ...) is kept out by .dockerignore. custom_libs/ MUST ship —
# the vendored markdown library is loaded via sys.path at runtime.
COPY . .

# Non-root runtime user with uid/gid 1000: matches the host user that owns
# the bind mounts in docker-compose.yml (./app_data, ./app_assets,
# ./static/img), so the container can read/write them without root.
# Only the mutable data dirs are chowned — code stays root-owned read-only.
RUN groupadd -g 1000 appuser && useradd -m -u 1000 -g appuser appuser \
    && mkdir -p /app/app_data/product_images /app/app_assets /app/static/img \
    && chown -R appuser:appuser /app/app_data /app/app_assets /app/static/img

USER appuser

EXPOSE 5000

# --preload: wsgi.py's DB init sequence then runs exactly once in the master
# process instead of racing between workers on a fresh volume (the init is
# idempotent, but ALTER TABLE migrations + SQLite would rather not race).
# Debugger/reloader stay OFF — production server (audit C1).
CMD ["gunicorn", "--workers", "2", "--threads", "4", "--preload", "--bind", "0.0.0.0:5000", "wsgi:application"]
