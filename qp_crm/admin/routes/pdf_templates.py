"""PDF template management and product image cleanup routes."""

from flask import render_template, request, redirect, url_for, flash
import os
import re

from qp_crm.shared.config import IMAGE_DIR

from ..app import bp, get_db, check_password

@bp.route("/pdf_templates")
def list_pdf_templates():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pdf_templates ORDER BY id ASC;")
    templates = cur.fetchall()
    
    cur.execute("SELECT value FROM global_settings WHERE key = 'active_pdf_template_id';")
    row = cur.fetchone()
    active_id = int(row["value"]) if row else 0
    
    conn.close()
    return render_template("admin/pdf_templates.html", templates=templates, active_id=active_id)

@bp.route("/add_pdf_template", methods=["POST"])
def add_pdf_template():
    name = request.form.get("name", "New Template")
    source_id = request.form.get("source_id") # Clone from existing
    
    conn = get_db()
    cur = conn.cursor()
    
    header, body, footer, css = "", "", "", ""
    if source_id:
        cur.execute("SELECT * FROM pdf_templates WHERE id = ?;", (source_id,))
        src = cur.fetchone()
        if src:
            header, body, footer, css = src["header_html"], src["body_html"], src["footer_html"], src["css"]
            
    cur.execute("""
        INSERT INTO pdf_templates (name, header_html, body_html, footer_html, css, is_readonly)
        VALUES (?, ?, ?, ?, ?, 0);
    """, (name, header, body, footer, css))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    
    flash("Template created.", "success")
    return redirect(url_for("admin.edit_pdf_template", template_id=new_id))

@bp.route("/edit_pdf_template/<int:template_id>", methods=["GET", "POST"])
def edit_pdf_template(template_id):
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == "POST":
        name = request.form.get("name")
        header = request.form.get("header_html")
        body = request.form.get("body_html")
        footer = request.form.get("footer_html")
        css = request.form.get("css")
        
        cur.execute("SELECT is_readonly FROM pdf_templates WHERE id = ?;", (template_id,))
        row = cur.fetchone()
        if row and row["is_readonly"]:
            flash("System template is read-only.", "error")
        else:
            cur.execute("""
                UPDATE pdf_templates 
                SET name=?, header_html=?, body_html=?, footer_html=?, css=?
                WHERE id=?;
            """, (name, header, body, footer, css, template_id))
            conn.commit()
            flash("Template updated.", "success")
            
    cur.execute("SELECT * FROM pdf_templates WHERE id = ?;", (template_id,))
    template = cur.fetchone()
    
    # For preview testing: get all offers
    cur.execute("SELECT id, client_name, offer_number FROM offers ORDER BY date DESC, id DESC;")
    offers = cur.fetchall()
    
    conn.close()
    if not template:
        return "Template not found", 404
        
    return render_template("admin/pdf_template_edit.html", template=template, offers=offers)

@bp.route("/cleanup_images", methods=["POST"])
def cleanup_images():
    current_admin_pass = request.form.get("current_admin_password")
    if not check_password("admin", current_admin_pass):
        flash("Invalid Admin Password", "error")
        return redirect(url_for('admin.index'))

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT id, name, photo_path FROM products")
    products = cur.fetchall()

    renamed_count = 0
    deleted_count = 0
    missing_count = 0

    valid_paths_in_db = set()

    for p in products:
        pid, pname, pphoto = p[0], p[1], p[2]
        
        if not pphoto:
            continue
            
        # 1. Check if the file physically exists
        old_full_path = os.path.join(IMAGE_DIR, pphoto)
        if not os.path.exists(old_full_path):
            missing_count += 1
            # Opt: we could clear it here, but leaving it as-is is safer
            continue

        # 2. Check if the name needs standardization
        ext = os.path.splitext(pphoto)[1].lower()
        if not ext:
            ext = ".jpg"

        base = (pname or "").strip().lower()
        base = re.sub(r"\s+", "_", base)
        base = re.sub(r"[^a-z0-9_-]", "", base)
        if not base:
             base = "product"

        new_filename = base + ext

        if new_filename != pphoto:
            new_full_path = os.path.join(IMAGE_DIR, new_filename)
            try:
                # Rename file
                os.rename(old_full_path, new_full_path)
                # Update DB
                cur.execute("UPDATE products SET photo_path = ? WHERE id = ?", (new_filename, pid))
                renamed_count += 1
                valid_paths_in_db.add(new_filename)
            except Exception as e:
                print(f"Error renaming {old_full_path} to {new_full_path}: {e}")
                valid_paths_in_db.add(pphoto) # Fallback to tracking old name
        else:
            valid_paths_in_db.add(pphoto)

    conn.commit()
    conn.close()

    # 3. Clean up orphaned files in IMAGE_DIR
    # G35: Only delete a file if it is NOT referenced anywhere else in the DB,
    #      not just in `products`. This avoids deleting shared images.
    conn = get_db()
    cur2 = conn.cursor()
    if os.path.exists(IMAGE_DIR):
        for filename in os.listdir(IMAGE_DIR):
            if filename not in valid_paths_in_db:
                # Check every table that may reference image paths before deleting
                cur2.execute("SELECT COUNT(*) AS c FROM products WHERE photo_path = ?", (filename,))
                used = cur2.fetchone()["c"] > 0
                if not used:
                    # Also check rent equipment photos if that table exists
                    try:
                        cur2.execute("SELECT COUNT(*) AS c FROM rent_equipment WHERE photo_path = ?", (filename,))
                        used = cur2.fetchone()["c"] > 0
                    except Exception:
                        pass
                if not used:
                    file_path = os.path.join(IMAGE_DIR, filename)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                            deleted_count += 1
                        except Exception as e:
                            print(f"Error removing orphaned image {file_path}: {e}")
    conn.close()

    flash(f"Image Cleanup Complete: {renamed_count} renamed/fixed, {deleted_count} orphaned files deleted, {missing_count} DB records pointing to missing files.", "success")
    return redirect(url_for("admin.index"))

@bp.route("/delete_pdf_template", methods=["POST"])
def delete_pdf_template():
    tpl_id = request.form.get("template_id")
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT is_readonly FROM pdf_templates WHERE id = ?;", (tpl_id,))
    row = cur.fetchone()
    if row and row["is_readonly"]:
        flash("Cannot delete system template.", "error")
    else:
        cur.execute("DELETE FROM pdf_templates WHERE id = ?;", (tpl_id,))
        # If it was active, reset to 0
        cur.execute("SELECT value FROM global_settings WHERE key = 'active_pdf_template_id';")
        r = cur.fetchone()
        if r and r["value"] == str(tpl_id):
            cur.execute("UPDATE global_settings SET value = '0' WHERE key = 'active_pdf_template_id';")
        conn.commit()
        flash("Template deleted.", "success")
        
    conn.close()
    return redirect(url_for("admin.list_pdf_templates"))

@bp.route("/set_active_pdf_template", methods=["POST"])
def set_active_pdf_template():
    tpl_id = request.form.get("template_id")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE global_settings SET value = ? WHERE key = 'active_pdf_template_id';", (tpl_id,))
    conn.commit()
    conn.close()
    flash("Active template updated.", "success")
    return redirect(url_for("admin.list_pdf_templates"))
