from .db import get_db

DEFAULT_PASSWORDS = {
    "admin": "Admin1",
    "pricing": "Price1",
    "offer": "Offer1"
}

def get_password(app_name):
    """
    Get the current password for the given app_name from global_settings.
    app_name can be 'admin', 'pricing', 'offer'.
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
