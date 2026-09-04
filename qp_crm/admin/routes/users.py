"""Admin Users management (Phase 3 step 6).

List / create / deactivate / role change / password reset for user
accounts. Every POST here is admin-only (the admin blueprint's
require_role("admin") hook) AND CSRF-protected (the app-level check_csrf).
Sensitive actions additionally require the ACTING ADMIN'S OWN password
('current_password' form field) -- the same confirm-with-password pattern
the dashboard already used for backups/uploads/API-key actions, now backed
by the users table instead of the legacy per-app password.

Self-service password change (every user, any role) lives on the unified
auth blueprint at /change-password.
"""

from flask import flash, redirect, render_template, request, session, url_for

from ..app import bp
from qp_crm.shared.auth import (
    admin_reset_user_password,
    change_user_role,
    confirm_current_password,
    create_user,
    list_users as list_users_rows,
    set_user_active,
)


def _guard_sensitive():
    """Common sensitive-action guard: acting admin confirms own password.

    Returns (acting_id, None) when confirmed, else (None, response).
    """
    acting_id = session.get("user_id")
    current = request.form.get("current_password") or ""
    if not confirm_current_password(acting_id, current):
        flash("Invalid current password for your own account.", "error")
        return None, redirect(url_for("admin.list_users"))
    return acting_id, None


@bp.route("/users")
def list_users():
    return render_template("admin/users.html", users=list_users_rows(), current_user_id=session.get("user_id"))


@bp.route("/users/create", methods=["POST"])
def create_user_action():
    acting_id, err = _guard_sensitive()
    if err:
        return err
    ok, result = create_user(
        request.form.get("username") or "",
        request.form.get("password") or "",
        request.form.get("confirm_password") or "",
        request.form.get("role") or "staff",
    )
    if ok:
        flash(f"User '{result}' created. They must change the password on first login.", "success")
    else:
        flash(result, "error")
    return redirect(url_for("admin.list_users"))


@bp.route("/users/<int:user_id>/toggle_active", methods=["POST"])
def toggle_user_active_action(user_id):
    acting_id, err = _guard_sensitive()
    if err:
        return err
    active = request.form.get("active") == "1"
    ok, error = set_user_active(acting_id, user_id, active)
    if ok:
        flash("User activated." if active else "User deactivated.", "success")
    else:
        flash(error, "error")
    return redirect(url_for("admin.list_users"))


@bp.route("/users/<int:user_id>/role", methods=["POST"])
def change_user_role_action(user_id):
    acting_id, err = _guard_sensitive()
    if err:
        return err
    ok, error = change_user_role(acting_id, user_id, request.form.get("role") or "")
    if ok:
        flash("Role updated.", "success")
    else:
        flash(error, "error")
    return redirect(url_for("admin.list_users"))


@bp.route("/users/<int:user_id>/reset_password", methods=["POST"])
def reset_user_password_action(user_id):
    acting_id, err = _guard_sensitive()
    if err:
        return err
    ok, error = admin_reset_user_password(
        acting_id,
        user_id,
        request.form.get("new_password") or "",
    )
    if ok:
        flash("Password reset. The user must change it on next login.", "success")
    else:
        flash(error, "error")
    return redirect(url_for("admin.list_users"))
