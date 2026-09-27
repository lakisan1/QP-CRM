# Agent Note: warehouse-stock-equipment-module

Status: implemented

## Problem

QP-CRM could price and sell products but had no idea where its physical machines were or who was holding them. The blueprint (planning/INTEGRATION_TECHNICAL.md §3–§5) called for stock and equipment tracking, but two of its premises had expired: the `/deals` spine it referenced for reservations and movement links was deleted on 2026-09-16, and the retired `rent_equipment` catalogue had already been removed (R-T8). The risk was building an inventory-value system for a business whose real counting happens in separate audit-warehouse software, and making 254 existing catalogue rows suddenly demand tracking data nobody had.

## Decision

The warehouse app lives at `/warehouse` as its own blueprint with its own per-user grant (`warehouse`, grants version 5) and a `Magacin` landing card; its logic is in `qp_crm/services/warehouse_service.py` and its DDL in `qp_crm/shared/schema.py` (`create_warehouse_tables`), with four tables: `equipment`, `stock_movements`, `reservations`, `equipment_shortfalls`. Tracking is opt-in per product through `products.tracking_regime` (`untracked` default | `qty` | `serialized`); untracked products are rejected by `record_movement` and never appear in `coverage_rows()`, so the pre-P5 catalogue behaves exactly as before. Serialized stock is DERIVED from instance rows (`custodian_type='warehouse' AND status='in_stock'`), never a parallel quantity ledger, so a serialized count always equals an instance count. There is no DELETE anywhere: a mistake in the ledger is corrected with a reversing movement, a machine exits via the terminal `scrap` transition, reservations close via `released_at`, shortfalls via `closed_at`. Custodian types are `warehouse|customer|scrap` and the customer counterparty is a `contacts` row (the directory is the only party registry — the deals spine was deleted 2026-09-16), so reservations carry a free-text `for_whom` instead of a deal link. `register_equipment` and `transition_equipment` share one `_DEFAULT_STATUS_BY_CUSTODIAN` map so the two paths cannot disagree. `stocktake_adjustment` is the one movement reason that requires a note. Every service call returns `(False, message)` on rejection rather than raising, because routes render that as a flash error. NOT done: fleet vehicles, purchase orders and PO lines (a shortfall's `po_ref` is free text), and the API surface for tracking fields.

## Alternatives

**Keep the blueprint's `deal_id` links on movements and reservations.** Rejected because the `/deals` spine (customers, deals, invoices, payments) was deleted at the user's request on 2026-09-16 — the columns would have pointed at tables that no longer exist, and reviving them would have resurrected an app the user deliberately removed. The directory (`/contacts`) is the surviving party registry, so the counterparty became a `contacts` row and "for whom" became free text.

**Give serialized products a quantity ledger too.** Rejected because two sources of truth for the same number is exactly how counts drift: the instance rows already say which machine is where, so the warehouse count is derived (`custodian_type='warehouse' AND status='in_stock'`). This is what makes the acceptance criterion "serialized count = instance count" true by construction rather than by discipline.

**Fold the screens into the existing pricing app** instead of a new `warehouse` grant. Rejected because the users who move machines are not the users who set prices; a separate grant lets the operator be given Magacin without the price list, and it keeps the landing page honest about what each person can open.

**Default new products to `qty` so tracking starts working immediately.** Rejected: the live catalogue has 254 rows and the user's explicit answer was an empty, opt-in start — defaulting to `qty` would have made every existing product appear in stock views with a balance of zero, which reads as "out of stock" rather than "not tracked".

**Delete the duplicate product row when merging.** Rejected because the repository is archive-only: a merge records the source's name as an alias and re-points references, so offer and price history survive and the merge stays legible afterwards (see the sibling note `../feature/2026-09-27-product-alias-merge-map.md`).

## Consequences

Cost: a fourth app-level grant and landing card to maintain, three closed sets that can only grow by migration, and a custody model that deliberately cannot answer "how much stock is this worth" — anyone wanting inventory value is told to keep the audit-warehouse software. `equipment_history()` caps at the most recent 1000 movements before reversing, so a machine past that many events gets its window reversed, not its whole life. Bought: the whole feature adds zero friction to the existing catalogue (all 254 products stay `untracked`), the ledger is append-only so no stock question is ever unanswerable from history, and a machine's custody can be changed in two taps without opening a document. Coverage gap: `qp_crm/pricing/api_v1.py` does not accept or expose the tracking fields, so an API-created product can only be `untracked`; the reservations/ATP view also has no incoming-PO term yet, so `available` is on-hand minus reservations only.

