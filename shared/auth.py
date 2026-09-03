import secrets
from .db import get_db

DEFAULT_PASSWORDS = {
    "admin": "Admin1",
    "pricing": "Price1",
    "offer": "Offer1",
    "rent": "Rent1"
}

# ---------- API Key Management ----------

def generate_api_key():
    """
    Generate a new 48-character hex API key and store it in global_settings.
    Returns the generated key.
    """
    new_key = secrets.token_hex(24)  # 48 hex chars
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR REPLACE INTO global_settings (key, value)
        VALUES ('api_key', ?);
    """, (new_key,))
    conn.commit()
    conn.close()
    return new_key

def get_api_key():
    """
    Retrieve the current API key from global_settings.
    Returns None if no key has been generated yet.
    """
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT value FROM global_settings WHERE key = 'api_key';")
        row = cur.fetchone()
    except Exception:
        row = None
    conn.close()
    if row:
        return row["value"]
    return None

def validate_api_key(key):
    """
    Validate that the given API key matches the stored key.
    Returns True if valid, False otherwise.
    """
    if not key:
        return False
    stored = get_api_key()
    if not stored:
        return False
    return secrets.compare_digest(key, stored)

def revoke_api_key():
    """
    Remove the API key from global_settings (revoke access).
    """
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM global_settings WHERE key = 'api_key';")
    conn.commit()
    conn.close()


def get_password(app_name):
    """
    Get the current password for the given app_name from global_settings.
    app_name can be 'admin', 'pricing', 'offer', 'rent'.
    """
    key = f"{app_name}_password"
    conn = get_db()
    cur = conn.cursor()
    
    # Ensure the table exists (it might not if init_db hasn't run fully yet, 
    # but practically we run init_db on startup).
    try:
        cur.execute("SELECT value FROM global_settings WHERE key = ?;", (key,))
        row = cur.fetchone()
    except Exception:
        row = None
        
    conn.close()

    if row:
        return row["value"]
    
    # Return default if not set in DB
    return DEFAULT_PASSWORDS.get(app_name)

def check_password(app_name, input_password):
    """
    Verify if input_password matches the stored password for app_name.
    """
    if not input_password:
        return False
        
    stored = get_password(app_name)
    return input_password == stored

def set_password(app_name, new_password):
    """
    Update the password for the given app_name.
    """
    key = f"{app_name}_password"
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT OR REPLACE INTO global_settings (key, value)
        VALUES (?, ?);
    """, (key, new_password))
    
    conn.commit()
    conn.close()
