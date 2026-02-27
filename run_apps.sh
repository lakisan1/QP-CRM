#!/usr/bin/env bash
set -e

#############################################
# Auto-setup & run merged CustomCRM app
# - optional: apt update + install packages
# - create app_data + product_images
# - create venv if missing
# - install requirements
# - start merged app in background
#############################################

# Go to the folder where this script lives (repo root)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Working directory: $PWD"

# Pulling latest code from Git
echo "Pulling latest code from Git..."
if command -v git >/dev/null 2>&1; then
  git pull
else
  echo "git not found, skipping git pull."
fi

#############################################
# 1) Optional: system packages via apt
#############################################

# If 'apt' exists (Debian/Ubuntu), we can install dependencies.
# Comment this whole block out if you prefer to do it manually.
if command -v apt >/dev/null 2>&1; then
  echo "Updating apt and installing system packages (python, venv, WeasyPrint deps)..."

  PKGS="python3 python3-venv python3-pip \
        libcairo2 libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 libgdk-pixbuf-2.0-0 \
        libffi-dev shared-mime-info fonts-dejavu-core"

  if [ "$(id -u)" -eq 0 ]; then
    apt update
    apt install -y $PKGS
  else
    sudo apt update
    sudo apt install -y $PKGS
  fi
else
  echo "apt not found, skipping system package installation."
fi

#############################################
# 2) app_data + folders
#############################################

echo "Ensuring app_data structure exists..."
mkdir -p app_data/product_images

# IMPORTANT:
# - pricing.db will be created automatically by the apps (init_db)
# - if you want to use your existing DB later, copy it into:
#   app_data/pricing.db

#############################################
# 3) Python venv + requirements
#############################################

if [ ! -d venv ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv venv
fi

echo "Activating venv..."
# shellcheck source=/dev/null
source venv/bin/activate

echo "Upgrading pip and installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt
# Ensure Werkzeug is installed as it's needed for dispatcher
pip install Werkzeug

#############################################
# 4) Start Merged Flask App
#############################################

echo "Stopping any old instances (if running)..."
pkill -f "pricing/app.py" || true
pkill -f "offer/app.py" || true
pkill -f "main.py" || true

echo "Starting merged app on port 5000..."
# We use nohup to keep it running after shell closes
nohup python3 main.py > main.log 2>&1 &

echo "All done. App should now be up:"
echo "  - Custom CRM : http://localhost:5000/"
