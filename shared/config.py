import os

# Base directory = the "QP-CRM" folder (parent of this shared folder's parent ideally, but let's be careful)
# We assume structure:
# QP-CRM/
#   shared/
#   pricing_app/
#   offer_app/
#   app_data/
#   static/

# The shared folder is inside QP-CRM. So parent of shared is QP-CRM.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
