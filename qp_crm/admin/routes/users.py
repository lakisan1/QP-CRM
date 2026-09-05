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
    MODULE_CHOICES,
    admin_reset_user_password,
    change_user_role,
    confirm_current_password,
    create_user,
    get_user_by_id,
    get_user_modules,
    list_users as list_users_rows,
    set_user_active,
    set_user_modules,
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
    users = [dict(u) for u in list_users_rows()]
    for u in users:
        u["modules"] = get_user_modules(u["id"])
    return render_template(
        "admin/users.html",
        users=users,
        module_choices=MODULE_CHOICES,
        current_user_id=session.get("user_id"),
    )


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
        modules=request.form.getlist("modules"),
    )
    if ok:
        flash(f"User '{result}' created. They must change the password on first login.", "success")
    else:
        flash(result, "error")
    return redirect(url_for("admin.list_users"))


@bp.route("/users/<int:user_id>/save", methods=["POST"])
def save_user_action(user_id):
    """ONE combined save per user row (user request: a single password
    field + Save button, not one per option). Applies, in order:
    active checkbox, role select, app-access checkboxes, and -- only when
    the optional field is filled -- a password reset. Every change runs
    its own service guard (self-deactivate, self-demote, last active
    admin); a guard failure is flashed and the remaining changes still
    apply, so one bad checkbox never blocks the whole row."""
    acting_id, err = _guard_sensitive()
    if err:
        return err
    target = get_user_by_id(user_id, include_inactive=True)  # reactivation must reach inactive rows
    if target is None:
        flash("User not found.", "error")
        return redirect(url_for("admin.list_users"))

    errors = []
    notes = []

    desired_active = request.form.get("active") == "1"
    if desired_active != bool(target["is_active"]):
        ok, error = set_user_active(acting_id, user_id, desired_active)
        if ok:
            notes.append("activated" if desired_active else "deactivated")
        else:
            errors.append(error)

    desired_role = request.form.get("role") or target["role"]
    if desired_role != target["role"]:
        ok, error = change_user_role(acting_id, user_id, desired_role)
        if ok:
            notes.append(f"role -> {desired_role}")
        else:
            errors.append(error)

    ok, result = set_user_modules(user_id, request.form.getlist("modules"))
    if ok:
        notes.append("apps: " + (", ".join(result) or "none"))
    else:
        errors.append(result)

    new_password = request.form.get("new_password") or ""
    if new_password:
        ok, error = admin_reset_user_password(acting_id, user_id, new_password)
        if ok:
            notes.append("password reset (change forced on next login)")
        else:
            errors.append(error)

    if errors:
        flash(" ".join(errors), "error")
    elif notes:
        flash(f"User '{target['username']}' updated: " + "; ".join(notes) + ".", "success")
    else:
        flash("Nothing to change.", "success")
    return redirect(url_for("admin.list_users"))
