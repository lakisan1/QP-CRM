"""Text preset management routes."""

from flask import request, redirect, url_for, flash

from ..app import bp, get_db

@bp.route("/add_preset", methods=["POST"])
def add_preset():
    category = request.form.get("category")
    name = request.form.get("name")
    content = request.form.get("content")
    is_default = 1 if request.form.get("is_default") else 0

    if not category or not name:
        flash("Category and Name are required.", "error")
        return redirect(url_for("admin.index"))

    conn = get_db()
    cur = conn.cursor()
    
    if is_default:
        # Unset other defaults in same category
        cur.execute("UPDATE text_presets SET is_default = 0 WHERE category = ?;", (category,))
    
    cur.execute("""
        INSERT INTO text_presets (category, name, content, is_default)
        VALUES (?, ?, ?, ?);
    """, (category, name, content, is_default))
    
    conn.commit()
    conn.close()
    
    flash("Preset added successfully.", "success")
    return redirect(url_for("admin.index"))

@bp.route("/delete_preset", methods=["POST"])
def delete_preset():
    preset_id = request.form.get("preset_id")
    if not preset_id:
        return redirect(url_for("admin.index"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM text_presets WHERE id = ?;", (preset_id,))
    conn.commit()
    conn.close()
    
    flash("Preset deleted.", "success")
    return redirect(url_for("admin.index"))

@bp.route("/set_default_preset", methods=["POST"])
def set_default_preset():
    category = request.form.get("category")
    preset_id = request.form.get("preset_id")
    
    if not category or not preset_id:
        return redirect(url_for("admin.index"))

    conn = get_db()
    cur = conn.cursor()
    # Unset others
    cur.execute("UPDATE text_presets SET is_default = 0 WHERE category = ?;", (category,))
    # Set this one
    cur.execute("UPDATE text_presets SET is_default = 1 WHERE id = ?;", (preset_id,))
    conn.commit()
    conn.close()
    
    flash("Default preset updated.", "success")
    return redirect(url_for("admin.index"))
