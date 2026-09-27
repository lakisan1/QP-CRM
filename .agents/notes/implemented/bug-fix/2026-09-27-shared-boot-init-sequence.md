# Agent Note: shared-boot-init-sequence

Status: implemented

## Problem

Both Admin → Backup restore paths (quick restore and full zip restore) re-ran only `init_users_table()`. Boot init runs once at process start, so restoring a backup that predates a module — e.g. any pre-P5 file, which has no `equipment`/`stock_movements`/`reservations`/`equipment_shortfalls` tables and no `products.tracking_regime` column — left the live database missing those objects and serving 500s on the affected pages until the container was restarted. The underlying reason the fix was not a one-liner: the ordered init sequence was duplicated in three places (`qp_crm/wsgi.py`, the `__main__` block of `qp_crm/main.py`, `tests/conftest.py`), so the restore flow would have needed a fourth copy, and divergence between copies silently produces a half-initialised schema.

## Decision

`qp_crm/shared/bootstrap.py` now owns the only definition of the boot sequence: `init_all_modules()` runs `pricing_init_db → pricing_migrate_schema → offer_init_db → admin_init_db → rent_init_db → contacts_init_db → warehouse_init_db`, in that order. Order is load-bearing (warehouse references both `products` and `contacts`) and is documented in the module docstring. Imports are function-local on purpose: importing `bootstrap` must not trigger the app package import graph, because `tests/conftest.py` has to patch `shared.config` before any app module binds `DATABASE`. `wsgi.py`, the `__main__` block of `main.py` and `tests/conftest.py` all call it; the `init_db`/`migrate_schema` imports in `main.py` are gone as dead. `init_all_modules()` deliberately does NOT swallow exceptions — a failed init must surface as a loud boot failure rather than a server that starts and then 500s. Both restore paths in `qp_crm/admin/routes/backup.py` (quick restore and full zip restore) call it after their existing `init_users_table()`, wrapped in their own try/except that flashes an error if the schema re-init fails. The factory-reset allow-list in the same file gained the P5 warehouse tables children-first — `stock_movements`, `equipment_shortfalls`, `reservations`, `equipment`, `product_aliases` — before `products`/`contacts`, because foreign keys are enforced and the clearing order therefore matters. NOT done: the restore paths still do not verify the restored file's schema version, and no migration-version table exists — recovery relies entirely on idempotency.

## Consequences

Cost: `init_all_modules()` imports the app package inside the function body, so a typo in a module path fails only at call time rather than import time — acceptable because every call site is a boot path that fails loudly anyway. Also, conftest no longer names the modules it initializes, so a reader must follow the import to see the order. Bought: adding a module to the app is now a one-line change in one file instead of four, and the restore flow can no longer restore the app into a half-missing schema. Coverage gap: the recovery test emulates a pre-P5 file by rebuilding `products` by hand; it does not exercise a real old backup zip through the upload route — the byte-level restore path itself remains untested end to end.

