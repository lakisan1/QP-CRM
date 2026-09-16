"""Admin per-user API keys management (Phase 3 step 7).

Issue / list / revoke keys that authenticate /api/v1 as the HOLDING
USER. Every POST is admin-only + CSRF-protected (blueprint hook + app
hook) and additionally confirms the acting admin password. The raw key
is flashed exactly once at issue; storage is its SHA-256 hash.

The legacy global api_key (dashboard section) remains valid during the
transition but is deprecated -- see API_INSTRUCTIONS.md.
"""

from flask import flash, redirect, render_template, request, session, url_for

from ..app import bp
from qp_crm.shared.auth import (
    confirm_current_password,
    delete_user_api_key,
    issue_user_api_key,
    list_user_api_keys,
    set_user_api_key_active,
)
from qp_crm.shared.db import get_db


def _guard_sensitive():
    """Confirm the ACTING admin's password. Returns (None, response) on
    failure, (acting_id, None) when confirmed."""
    acting_id = session.get("user_id")
    current = request.form.get("current_password") or ""
    if not confirm_current_password(acting_id, current):
        flash("Invalid current password for your own account.", "error")
        return None, redirect(url_for("admin.list_api_keys"))
    return acting_id, None


@bp.route("/api_keys")
def list_api_keys():
    """Keys overview + issue form (user dropdown)."""
    conn = get_db()
    users = conn.execute(
        "SELECT id, username, role FROM users WHERE is_active = 1 ORDER BY username ASC;"
    ).fetchall()
    conn.close()
    return render_template("admin/api_keys.html", keys=list_user_api_keys(), users=users)


@bp.route("/api_keys/issue", methods=["POST"])
def issue_api_key_action():
    acting_id, err = _guard_sensitive()
    if err:
        return err
    user_id = request.form.get("user_id", type=int)
    label = request.form.get("label") or ""
    if not user_id:
        flash("Select a user for the new key.", "error")
        return redirect(url_for("admin.list_api_keys"))
    raw_key, error = issue_user_api_key(user_id, label)
    if raw_key is None:
        flash(error, "error")
    else:
        # Shown EXACTLY ONCE: only the SHA-256 hash is stored. The admin
        # copies it into the integration now; it cannot be re-displayed.
        flash(f"New API key issued (copy it now, it is shown only once): {raw_key}", "success")
    return redirect(url_for("admin.list_api_keys"))


@bp.route("/api_keys/<int:key_id>/toggle", methods=["POST"])
def toggle_api_key_action(key_id):
    acting_id, err = _guard_sensitive()
    if err:
        return err
    active = request.form.get("active") == "1"
    ok, error = set_user_api_key_active(key_id, active)
    if ok:
        flash("API key revoked." if not active else "API key re-enabled.", "success")
    else:
        flash(error, "error")
    return redirect(url_for("admin.list_api_keys"))


@bp.route("/api_keys/<int:key_id>/delete", methods=["POST"])
def delete_api_key_action(key_id):
    """Hard-delete a revoked key row (cleanup of dead entries).

    Same guard as the other sensitive actions: acting admin's own password.
    The service refuses to delete an ACTIVE key (revoke first).
    """
    acting_id, err = _guard_sensitive()
    if err:
        return err
    ok, error = delete_user_api_key(key_id)
    if ok:
        flash("API key deleted.", "success")
    else:
        flash(error, "error")
    return redirect(url_for("admin.list_api_keys"))
