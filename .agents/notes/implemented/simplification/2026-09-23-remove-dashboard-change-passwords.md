# Agent Note: remove-dashboard-change-passwords

Status: implemented

## Problem

After moving backups and the Danger Zone off the admin dashboard, the top 'Change Passwords' card remained: a per-app password form (admin/pricing/offer/rent) that duplicates Admin -> Users — the single password-management place since Phase 3 — and predates the unified users table. The user asked to delete it and to thoroughly check for any dead code left by the UI reshuffles.

## Decision

The dashboard 'Change Passwords' card (per-app password form: admin/pricing/offer/rent) and the /admin/update_passwords route (admin/routes/settings.py) are deleted. Password management lives exclusively in Admin -> Users — the save form's optional 'New password' field, backed by admin_reset_user_password with the confirm-current-password guard. admin/app.py drops the set_password import (its only caller was the removed route) plus the dead flask/import names left by the route split (render_template, request, redirect, session, flash, send_file, Flask, url_for, time, pathlib, shutil, sqlite3); it keeps check_password and the shared.web/shared.countries re-exports because routes/* import them via `from ..app import ...` (core.py, backup.py, pdf_templates.py, settings.py, rent_templates.py — that hub pattern is intentional). admin/routes/backup.py drops its unused io import. Regression tests added to tests/characterization/test_backup_tab.py (now 12): dashboard renders no Change Passwords form and no new_admin_password field, /admin/update_passwords is absent from app.url_map, /admin/users keeps the new-password field, /admin/backup renders the Danger Zone + Factory Reset. Suite: 351 passed, 3 skipped; CI green on 3563601; the live local instance was pulled/recreated and verifies clean (update_passwords absent from the url map, dashboard form absent, Danger Zone present on /admin/backup).
## Alternatives considered

**Keep the route, hide the form** — rejected: dead endpoints are worse than dead UI (unauthenticated-by-intent attack surface and reader confusion); the url map must not list what the UI does not use.

**Move the per-app form into the Backup tab instead of deleting** — rejected: it manages user accounts, not backups, and duplicates Admin -> Users; deletion was the user's explicit decision.

**Project-wide dead-import purge (offer/pricing/rent app.py hubs)** — deliberately NOT done in this commit: those "unused" names are intentional re-export hubs consumed by routes/* via ..app imports (the module pattern of this codebase), and touching four other apps is out of scope for this UI change. The AST scan result is recorded here so the next cleanup pass starts from evidence.
## Consequences

Bought: one password-management place (Admin -> Users), a dashboard that renders fewer forms, no route in the url map that no UI can reach, and a cleaner import list in the admin hub. Cost: re-export hubs (admin/app.py and the other app.py files) LOOK like dead imports to any AST scan — the pattern is documented here so nobody "cleans" them blindly; net -95 lines. NOT done: no removal of the re-export pattern itself (it works and is consistent across pricing/offer/rent/admin); sale/app.py send_from_directory and IMAGE_DIR unused imports were spotted in the scan but left (other app, other commit); the users.must_change_password column still exists unread (documented in auth/app.py note).

