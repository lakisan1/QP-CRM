import os

# Base directory = the repo/deployment root (the "QP-CRM" folder).
# Structure since the Phase-2 qp_crm/ package move:
# QP-CRM/
#   qp_crm/            <- this package (main, wsgi, shared/, pricing/, ...)
#   app_data/
#   static/
#   app_assets/
#   templates/         <- landing page (stays at the root, NOT in qp_crm/)
#
# This file lives at <root>/qp_crm/shared/config.py, so BASE_DIR needs THREE
# dirnames (was two before the package move): file -> shared/ -> qp_crm/ -> root.
# docker-compose bind-mounts ./app_data, ./app_assets and ./static/img at the
# same absolute paths, so this value must keep resolving to the root.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# app_data folder inside QP-CRM
APP_DATA_DIR = os.path.join(BASE_DIR, "app_data")

# pricing.db inside app_data
DATABASE = os.path.join(APP_DATA_DIR, "pricing.db")

# product image data
IMAGE_DIR = os.path.join(APP_DATA_DIR, "product_images")

# static/css path
STATIC_DIR = os.path.join(BASE_DIR, "static")

# app_assets inside app_data
APP_ASSETS_DIR = os.path.join(BASE_DIR, "app_assets")

# ---------- Website sync (Sajt <-> CRM product sync) ----------
# Public WP REST API for autoservisnaoprema.com (no auth keys needed).
# Sync is EXCLUSIVELY manual - triggered only by clicking the button in the UI.
SITE_BASE_URL = os.environ.get("QP_SITE_BASE_URL", "https://autoservisnaoprema.com")
SITE_API_BASE = SITE_BASE_URL.rstrip("/") + "/wp-json/wp/v2"
SITE_PER_PAGE = int(os.environ.get("QP_SITE_PER_PAGE", "100"))
SITE_TIMEOUT = 15          # seconds
SITE_RETRIES = 2           # retry count on network error
SITE_MAX_DESC_LEN = 1000   # max chars for generated description
