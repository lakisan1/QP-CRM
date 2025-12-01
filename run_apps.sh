#!/usr/bin/env bash
set -e

#############################################
# Auto-setup & run pricing + quotation apps
# - optional: apt update + install packages
# - create app_data + product_images
# - create venv if missing
# - install requirements
# - start both apps in background
#############################################

# Go to the folder where this script lives (repo root)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "Working directory: $PWD"

#Pulling latest code from Git
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
        libcairo2 libpango-1.0-0 libgdk-pixbuf-2.0-0 \
        libffi-dev shared-mime-info fonts-dejavu-core"

  if [ "$(id -u)" -eq 0 ]; then
    apt update
    apt install -y $PKGS
  else
    sudo apt update
    sudo sudo apt install -y $PKGS
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

#############################################
# 4) Start both Flask apps in background
#############################################

echo "Stopping any old instances (if running)..."
pkill -f "pricing_app/app.py" || true
pkill -f "quotation_app/app.py" || true

echo "Starting pricing_app on port 5000..."
nohup python3 pricing_app/app.py > pricing.log 2>&1 &

echo "Starting quotation_app on port 5001..."
nohup python3 quotation_app/app.py > quotation.log 2>&1 &

echo "All done. Apps should now be up:"
echo "  - Pricing app   : http://<server-ip>:5000/products"
echo "  - Quotation app : http://<server-ip>:5001/offers"
