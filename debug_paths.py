import sys
import os

# Add current dir to path
sys.path.append(os.getcwd())

try:
    from pricing.app import app as pricing_app
    print(f"Pricing App Root Path: {pricing_app.root_path}")
    print(f"Pricing App Template Folder: {pricing_app.template_folder}")
    
    import pricing
    print(f"Pricing Module File: {pricing.__file__}")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Error: {e}")
