"""Price rounding rule management routes."""

from flask import render_template, request, redirect, url_for, flash

from ..app import bp, get_db

@bp.route("/rounding_rules")
def list_rounding_rules():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM price_rounding_rules ORDER BY target ASC, limit_val ASC;")
    rules = cur.fetchall()
    
    rules_by_target = {'price': [], 'discount': []}
    for r in rules:
        if r['target'] in rules_by_target:
            rules_by_target[r['target']].append(r)
            
    conn.close()
    return render_template("admin/rounding_rules.html", rules_by_target=rules_by_target)

@bp.route("/add_rounding_rule", methods=["POST"])
def add_rounding_rule():
    target = request.form.get("target")
    limit_val = float(request.form.get("limit_val") or 0)
    step_val = float(request.form.get("step_val") or 0)
    method = request.form.get("method", "UP")
    
    if not target or limit_val <= 0 or step_val <= 0:
        flash("Invalid rule data.", "error")
        return redirect(url_for("admin.list_rounding_rules"))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO price_rounding_rules (target, limit_val, step_val, method)
        VALUES (?, ?, ?, ?);
    """, (target, limit_val, step_val, method))
    conn.commit()
    conn.close()
    
    flash("Rounding rule added.", "success")
    return redirect(url_for("admin.list_rounding_rules"))

@bp.route("/delete_rounding_rule", methods=["POST"])
def delete_rounding_rule():
    rule_id = request.form.get("rule_id")
    if not rule_id:
        return redirect(url_for("admin.list_rounding_rules"))
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM price_rounding_rules WHERE id = ?;", (rule_id,))
    conn.commit()
    conn.close()
    
    flash("Rounding rule deleted.", "success")
    return redirect(url_for("admin.list_rounding_rules"))
