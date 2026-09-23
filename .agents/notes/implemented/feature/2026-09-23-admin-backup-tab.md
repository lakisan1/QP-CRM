# Agent Note: admin-backup-tab

Status: implemented

## Problem

The user wants backup management separated from the crowded admin dashboard: a dedicated tab where all server-side restore points (quick backups + the pre-deploy snapshots deploy.sh writes) are visible, quick backups can be created/restored in one click, and the full-system .zip download remains for manual copies on other servers and migrations. The old "DB only (no images)" download/upload pair should go — images are small, the DB-only backup is redundant with the quick backup.

## Decision

Admin gains a dedicated "Backup" tab (/admin/backup, first link after Dashboard in the shared _nav) backed by admin/routes/backup.py. Quick backups are WAL-safe sqlite3.backup() snapshots of the live DATABASE saved into BACKUP_DIR (new constant in shared/config.py = <BASE_DIR>/backups) named quick-<ts>.db, chmod 600, retention QUICK_BACKUP_KEEP=30 (quick-* only). The tab's table lists EVERY *.db in BACKUP_DIR newest-first, labelling kinds: quick / pre-deploy (update) / pre-rollback — so deploy.sh and rollback.sh restore points are visible in the UI; the app never prunes those (their scripts own retention). Actions: download (exact bytes), restore (password-confirmed, integrity-checked source, sqlite3.backup() swap, init_users_table() re-run, and a pre-restore-<ts>.db safety snapshot of the CURRENT state taken first — a restore is itself undoable), delete (password-confirmed). One password field on the page feeds all Restore/Delete forms via JS. The full-system .zip download (generate_full_backup_zip) and .zip upload-restore (/restore_full) moved onto the tab unchanged for manual off-server copies/migration. REMOVED: /admin/backup_db and /admin/restore_db (DB-only download/upload) — 404 now; smoke/characterization tests updated. New tests: tests/characterization/test_backup_tab.py (9) pin snapshot creation, listing by kind, exact-byte download, traversal rejection (400), password gates, restore rollback semantics + safety snapshot, retention. Full suite: 348 passed, 3 skipped.
## Alternatives considered

**Store quick backups inside the container/filesystem image** — rejected: state outside bind mounts dies with the container; backups/ on the host (same folder deploy.sh already writes) survives everything and shows up in the same list.

**In-UI restore without password** — rejected: a restore replaces the entire user table; a hijacked admin session could silently swap the auth database. Restore and delete both require the acting admin's password, matching the existing confirm-with-password pattern.

**Upload-and-store .zip into the restore-point list** — deferred: zip uploads restore immediately (full system incl. images); folding stored zips into the same list adds 100 MB+ files to backups/ with unclear retention; revisit only if the user asks for server-stored full zips.

**DB-only download/upload kept alongside quick backups** — removed at the user's explicit request: the quick backup IS the DB-only backup, but server-side, listable and one-click restorable; two DB-only paths would overlap confusingly.
## Consequences

Bought: one page answers "what can I restore right now" — quick backups and update-system snapshots in one table, one-click restore with a safety snapshot, full .zip still available for off-server copies/migration; the update system's pre-deploy snapshots are now visible in the UI instead of only on disk. Cost: backup.py rewritten as the tab's module (the old dashboard-embedded backup card is gone; dashboard keeps only Image Cleanup); the .db files live on the host in backups/ — a host-level deletion or disk failure takes them with it (off-server copies remain the .zip's job); the dashboard password field trick means the password sits in the DOM briefly — acceptable on a LAN app, but a per-row prompt would be the stricter UI. NOT done: no automatic scheduled quick backups (create is manual or via deploy.sh); no remote/offsite sync; zip restore still overwrites images in place without a pre-restore images snapshot.

