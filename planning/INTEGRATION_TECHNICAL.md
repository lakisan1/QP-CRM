# QP-CRM Expansion — Technical Integration Blueprint

Status: planning complete, not yet built. Companion files: `VISION.md` (plain-language idea),
`OPEN_QUESTIONS.md` (open decisions). Canonical decision log:
`.agents/notes/implemented/architecture/2026-09-07-qp-crm-deal-spine-blueprint.md` (6 amendments).
Board cards: **P4 — Deals spine**, **P5 — Stock & equipment**.

---

## 0. What this document is

The implementation-facing spec for extending QP-CRM from a pricing/offer/rent/sale suite
into the single operational system for MH (undercar equipment: lifts, PTI lanes, testers —
everything except hand tools, for cars, trucks, motorcycles). It records:

- what already exists and gets reused (integration points),
- the new schema (column-level sketches to finalize in the first build task),
- cross-cutting conventions (id+snapshot, no-delete, derived status, alias map),
- the phase plan with acceptance criteria,
- non-goals and risks.

Ground rule from the design conversation: **every future feature must be (a) a new document
type on the deal, (b) a view over existing data, or (c) master data.** Anything that wants
its own workflow engine, its own copy of the customer, or its own status dropdowns is
rejected. This admission rule is the anti-mess mechanism; quote it in code review.

---

## 1. Existing codebase — what gets reused (integration points)

Stack today (verified in repo): Flask, one SQLite DB (`app_data/pricing.db`), single schema
source `qp_crm/shared/schema.py`, blueprint modules under `qp_crm/` (admin, auth, offer,
pricing, rent, sale, settings, shared), service layer in `qp_crm/services/`
(`offer_service`, `pdf_service`, `pricing_service`, `rent_service`), WeasyPrint PDFs with
sandboxed Jinja (P2 stage 4), unified auth (users, roles, per-module grants in
`user_modules`, CSRF, per-user API keys + audit), Docker deploy (`deploy.sh`, image rebuild),
PWA manifest, backup/restore in admin. Test safety net: pytest, characterization tests on
money paths, golden-PDF baselines.

| Asset | Reuse in the expansion |
|---|---|
| `products`, `prices`, `brands`, `category_pricing_defaults` (pricing) | The single catalog. P5 adds columns (tracking regime, min-stock, units). Never forked into a warehouse copy. |
| `offers`, `offer_items`, `text_presets`, `pdf_templates` (offer) | Offers keep working; gain `deal_id` + `location_id` columns. `offer_items` is already the reference pattern for **id + snapshot** lines (nullable `product_id`, NOT NULL `item_name`) — the convention generalizes app-wide. |
| Offer PDF + email pipeline (offer_service, pdf_service, NBS rate fetch) | Same pipeline issues invoices later (P4.x): new template in `pdf_templates`, items/totals identical, payment tracking added. |
| Rent module document engine (`rent_contract_documents`, placeholder substitution, `import_templates.py` seeding) | The **pattern** for travel orders / work orders / service orders (P6): master HTML templates + placeholder context + WeasyPrint + golden tests. Do not couple code to rent; copy the pattern. |
| `rent_clients` (PIB/MB, bank accounts, reps) | Field reference for the new `customers` table. Unifying rent_clients into customers is an **open question** (see Q-file #19) — P4 does not force it. |
| Auth & grants (`users`, `user_modules`, `admin/routes/users*`) | New modules (`deals`, `warehouse`, later `fleet`) join the per-user grant checkboxes; admins bypass. All new forms AJAX+CSRF compliant. |
| Admin: `pdf_templates` editor, branding, backup/restore | Invoice + service-doc templates editable in-app; backups must cover new tables (they already cover the whole DB file). |
| `qp_crm/shared/db.py`, `add_column_if_missing` | Migration style for all new columns/tables: single schema source + idempotent `CREATE TABLE IF NOT EXISTS` + `add_column_if_missing`. |
| pytest infra + golden-PDF tests | New characterization tests for: derived statuses, ATP math, alias resolution, payment allocation, shortfall auto-close. Golden-PDF for the invoice template. |

### 1.1 MH fin analitike (analysis workspace, `/home/dsh/MH fin analitike`)

Separate SQLite (`clean_data/db_v2.sqlite`): 1,606 offers + 7,462 pro-formas + bank GL
parsed; `partners` ≈ 4,657 normalized rows (PIB/MB where captured); `doc_links` funnel
(L1 offer→pro-forma by number rule `P-1016 ↔ 1016`, L2 pro-forma→payment by amount/partner,
L3 direct). It stays the **historical analytics DB** — read-only, no CRM writes into it.

Integration value:
- **Seed import (optional, user decision pending):** one-time push of `partners` (name,
  PIB, MB, address, phone/email where parsed) into the new `customers` table as a starting
  base instead of manual re-entry. Dedupe by PIB/MB; everything without PIB/MB imports as
  name-only rows flagged for review.
- **Funnel analytics pattern:** live CRM answers the same funnel questions trivially
  because documents link at birth (`deal_id`); the ETL linking rules (L1/L2/L3) are only
  needed for pre-2026 history, which stays in the analytics DB.
- **Custody boundary:** QP-CRM is NOT the audit/counting warehouse software (external,
  in-and-sold, no per-customer dimension). CRM tracks custody of machines and debts
  between machines; the audit system keeps counting inventory value. Never duplicate
  its books.

---

## 2. Party model (P4 schema)

Three levels: **customer** (who pays) → **location** (where work happens) → **deal**
(the thread). Documents issue against the customer (billing) and reference the deal +
optionally the location (site).

```sql
-- SKETCH — finalize in P4-T1
CREATE TABLE customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,                 -- resolved by id everywhere; rename-safe
  pib TEXT, mb TEXT,                  -- unique-ish; used for seed dedupe
  billing_address TEXT, city TEXT, country TEXT,
  email TEXT, phone TEXT,             -- parse multi-email like offer clients do
  notes TEXT, created_at TEXT, archived INTEGER DEFAULT 0
);
CREATE TABLE customer_locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  name TEXT, address TEXT, city TEXT,
  contact_name TEXT, contact_phone TEXT, notes TEXT
);
CREATE TABLE deals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE,                   -- D-YYYY-NNN, printed in emails/docs
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  location_id INTEGER REFERENCES customer_locations(id),  -- NULL = customer HQ
  title TEXT NOT NULL,
  owner_user_id INTEGER REFERENCES users(id),
  created_at TEXT, closed_at TEXT     -- status DERIVED (§5); nothing hand-set except 'new'
);
CREATE TABLE deal_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deal_id INTEGER NOT NULL REFERENCES deals(id),
  event_type TEXT NOT NULL,           -- call|email|meeting|note|document|decision
  author_user_id INTEGER REFERENCES users(id),
  body TEXT, linked_doc_type TEXT, linked_doc_id INTEGER,
  created_at TEXT
);
-- ALTER offers: add deal_id INTEGER NULL REFERENCES deals(id),
--               add location_id INTEGER NULL REFERENCES customer_locations(id)
-- Client header fields on offers STAY as issuance-time snapshot (billing copy).
```

Payments (P4, with invoice issuance):

```sql
-- SKETCH
CREATE TABLE payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  amount REAL NOT NULL, currency TEXT DEFAULT 'RSD',
  paid_at TEXT, method TEXT, note TEXT, created_by INTEGER
);
CREATE TABLE payment_allocations (   -- one transfer may cover N invoices
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  payment_id INTEGER NOT NULL REFERENCES payments(id),
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  amount REAL NOT NULL
);
```

`invoices` reuses the offer pipeline (own table, global per-year numbering, client
snapshot fields, items, totals, `deal_id`, `pdf_path`). Build order inside P4:
customers+locations → deals+timeline → offer link → pipeline view → invoice+payments.

---

## 3. Stock & equipment (P5 schema)

Per-product **tracking regime** on `products` (new columns):
`tracking_regime TEXT DEFAULT 'untracked'` (`untracked` | `qty` | `serialized`),
`min_stock REAL NULL`, `unit_base TEXT`, `pack_size REAL NULL` (practical units: box/liter/meter).

```sql
-- SKETCH
CREATE TABLE equipment (             -- serialized instances; rows live forever
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER REFERENCES products(id),   -- NULL allowed = temp product registration
  name_snapshot TEXT NOT NULL,                   -- id+snapshot convention
  serial_number TEXT,
  custodian_type TEXT NOT NULL,       -- warehouse|fleet_vehicle|customer_location|supplier|scrap
  custodian_id INTEGER,               -- fleet_vehicles.id | customer_locations.id | NULL
  since_date TEXT NOT NULL,
  status TEXT NOT NULL,               -- in_stock|sold|loaned|test_demo|in_service_ours|scrapped
  expected_return_at TEXT,            -- loan/test reminders (P7)
  notes TEXT
);
CREATE TABLE stock_movements (       -- the only way anything moves; never deleted
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER REFERENCES products(id),   -- qty-regime rows
  equipment_id INTEGER REFERENCES equipment(id),-- serialized rows
  name_snapshot TEXT,                 -- temp products / free-text part names
  qty REAL,                           -- qty regime only
  reason TEXT NOT NULL,               -- fixed list, see §5
  from_type TEXT, from_id INTEGER, to_type TEXT, to_id INTEGER,  -- same custodian union
  doc_type TEXT, doc_id INTEGER,      -- OPTIONAL evidence: offer|invoice|deal|po
  deal_id INTEGER REFERENCES deals(id),
  note TEXT, moved_at TEXT, moved_by INTEGER
);
CREATE TABLE purchase_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  po_number TEXT, supplier_name TEXT, -- supplier partner ref when partners exist
  ordered_at TEXT, expected_at TEXT,
  deal_id INTEGER REFERENCES deals(id)          -- optional allocation to a deal
);
CREATE TABLE po_lines (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
  product_id INTEGER REFERENCES products(id), name_snapshot TEXT,
  qty REAL NOT NULL, shortfall_id INTEGER REFERENCES equipment_shortfalls(id)
);
CREATE TABLE fleet_vehicles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plate TEXT, name TEXT, default_user_id INTEGER REFERENCES users(id)
);
CREATE TABLE equipment_shortfalls (  -- donor parts = DEBTS, not inventory
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  equipment_id INTEGER NOT NULL REFERENCES equipment(id),  -- device A that owes the part
  part_product_id INTEGER REFERENCES products(id), part_name TEXT NOT NULL,
  taken_for_deal_id INTEGER REFERENCES deals(id),
  taken_for_doc_type TEXT, taken_for_doc_id INTEGER,
  taken_at TEXT, po_line_id INTEGER REFERENCES po_lines(id),
  closed_at TEXT, note TEXT
);
CREATE TABLE product_aliases (       -- merge 2-or-5-into-1 without breakage
  alias_id INTEGER PRIMARY KEY REFERENCES products(id),  -- UNIQUE, may never alias an alias
  canonical_id INTEGER NOT NULL REFERENCES products(id)
);
CREATE TABLE reservations (          -- always "for whom"
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deal_id INTEGER REFERENCES deals(id), for_whom_text TEXT,  -- one of the two required
  product_id INTEGER REFERENCES products(id), qty REAL,      -- qty regime
  equipment_id INTEGER REFERENCES equipment(id),             -- pinned instance
  created_at TEXT, released_at TEXT
);
```

Regime rules:
- `untracked` (default; screws, clamps, most small parts): catalog row used by
  offers/invoices/POs only. **No** movements, reservations, van holdings, ATP. Exists so
  documents can name it. If a part class later needs accountability → flip to `qty`,
  machinery already covers it.
- `qty` (opt-in: oil drums, expensive spares): loose arithmetic ledger, practical units,
  optional `min_stock` alert, corrections via `stocktake/adjustment` movements with
  mandatory note. Drift is expected and tolerated; stocktakes fix it.
- `serialized` (mandatory for anything with a serial plate): identity. Instance rows are
  never deleted — exit is `custodian_type='scrap'` (or sold-off-record). Count mismatch on
  serialized goods is an incident, not a balance edit.

---

## 4. Cross-cutting conventions (apply to every new table)

1. **id + snapshot.** Every line/row references by surrogate id (nullable FK) AND carries
   its own text snapshot (name/description/photo). Quotation already does this
   (`offer_items.product_id` NULL + `item_name`). Warehouse movements, equipment rows, PO
   lines, shortfall entries, deal documents all follow it. Consequence: an ad-hoc part or
   unnamed device needs no catalog row ("temp product"), and a one-click **"make real
   product"** promotes a snapshot into a `products` row and back-fills references in one
   update.
2. **Names resolved at read time.** No module stores another entity's name as its key.
   Renaming a product/customer/location = editing one master row; nothing breaks.
3. **Merges via alias map.** Merge N→1: choose canonical, insert alias rows; old ids keep
   resolving through `product_aliases` (UNIQUE alias id, no chains/diamonds — an alias may
   never itself be aliased). A duplicate-suspect view (similar names, both referenced) and
   a merge tool re-point referencing rows at leisure. Same mechanism later for customers
   and locations. Un-merge is manual by design.
4. **History is frozen.** Issued documents keep issuance-time snapshots — rename/merge
   never rewrites an old offer or invoice. Only new lines resolve to the canonical name.
5. **No deletes.** Equipment: transitions only (→ scrap). Movements: reversing movements
   only. Documents: archived, not destroyed (archive policy = open question).
6. **Derived status, minimal hand events.** Hand-set only: deal `new` (before any
   document), and the offer acceptance/rejection tap (a decision record, not a state
   guess). Everything else derives from links (table below).
7. **Optional document references on custody.** Movements carry a reason; the invoice/
   offer/deal link is evidence, not a requirement (free-issue / loan / test are normal).

---

## 5. Derived statuses, numbering, formulas

| Object | Status | Derivation |
|---|---|---|
| Deal | new | hand-set until first linked document |
| Deal | offered | ≥1 offer linked |
| Deal | won | invoice issued from the deal (or accepted-offer tap recorded as `decision` event) |
| Deal | done | signed work order attached (P6) |
| Deal | closed | hand close (no further activity) |
| Invoice | paid / partially_paid / overdue | Σ `payment_allocations` vs total; due date vs today |
| PO | ordered → partially_received → received | receipt movements referencing the PO/po_line |
| PO | late | `expected_at < today` and not fully received |
| Shortfall | open → closed | `closed_at` set, or receipt of the `po_line` referencing it |
| Van holding | qty per product | Σ movements with van as endpoint |
| Warehouse serialized stock | count | instances with `custodian_type='warehouse'`, status `in_stock` |
| Customer equipment list | rows | instances with custodian `customer_location` under that customer |

Numbering: documents keep **global per-type per-year** sequences (as today's invoices).
Deals additionally carry their own code `D-YYYY-NNN` — the reference humans write in
emails/notes. Implement with a per-year counter table + retry (SQLite single-writer makes
races unlikely; still guard).

ATP (coverage view, qty regime only):
`available = on_hand(ledger) − Σ active reservations + Σ open PO line qty (expected_at not passed)`.
Reservations always show "for whom": `deal → customer name + deal code` or free-text note.
Orders-needed view = ATP shortfalls + open shortfalls (donor debts) + late POs.

Fixed movement reason list (closed set, extend only by migration):
`purchase-in, sale, free-issue, loan, test-demo, return, service-in, transfer, scrap, stocktake-adjustment`.

Custodian union (movement endpoints): `warehouse | fleet_vehicle | customer_location |
supplier | scrap`. Vans are internal custodians in `fleet_vehicles` — **never** rows in
`customers` (keeps customer stats, reminders, invoicing clean).

---

## 6. Module & UX map

- New blueprints: `qp_crm/deals/` (customers, locations, deals, timeline, pipeline),
  `qp_crm/warehouse/` (movements, equipment, POs, coverage, fleet). Admin gains
  fleet management + alias/merge tooling under existing admin routes pattern
  (`admin/routes/*` domain split).
- Shared pickers (build once, reuse): site picker (customer → locations, pre-filled,
  blank = HQ), custodian picker (warehouses + vans + customer locations, grouped),
  reason chooser, for-whom field.
- Deal page = thread: timeline + document cards (offer, invoice, payments, reservations,
  POs, travel/work orders, signed PDFs) + derived status strip.
- Mobile flows (P7, HTTPS prerequisite — pending nginx card): create deal < 30 s; van
  consumption = one tap; donor shortfall = two taps; customer signs on device → PDF
  finalized on the spot. Service worker stays static-only (never cache CRUD).
- API: extend existing per-user-key REST pattern (`pricing/api_v1.py` precedent) when a
  need appears; not part of P4.

---

## 7. Phase plan & acceptance criteria

| Phase | Scope | Kills | Accept when |
|---|---|---|---|
| **P4 — Deals spine** | customers, locations, deals, timeline, offer link (deal_id/site), pipeline view, invoice + payments | old CRM, "no project tracking" | staff log a call→offer→invoice fully in-app; pipeline view matches reality without anyone maintaining statuses; tests green incl. new characterization |
| **P5 — Stock & equipment** | regimes, equipment instances, movements, reservations (for-whom), POs + ATP, fleet vans, shortfalls, aliases, temp products | the tracking Excel | one query answers "reserved/for whom/ordered/needed"; a lift changes custody in 2 taps; rename & merge demos break nothing; serialized count = instance count |
| **P6 — Service docs** | travel/work/service order document types (template engine pattern from rent), equipment registry view = service history | ticketing software | a full service visit: report → offer/shortfall → work order → signed PDF, all on one deal |
| **P7 — Field & reminders** | mobile tech view, on-device signature, maintenance/inspection reminders per machine, loan/test return reminders | paper in the field | tech runs the whole visit from a phone over HTTPS; reminders fire from `expected_return_at` + per-machine maintenance schedule |

Rule between phases: a phase is done only when the tool it replaces is actually retired.

---

## 8. Non-goals (explicit)

- Double-entry accounting, GL, inventory valuation → finance software + audit warehouse
  software stay the truth; app exports/reconciles at most.
- eFaktura / fiscal device integration → later, legal check first (open question).
- Per-unit tracking of small parts → regime `untracked`, by user decision.
- Vans as customer rows, automatic procurement, campaigns/lead-scoring/custom-field
  builders/customer portal → rejected (see note, Alternatives).
- Migrating old CRM/ticketing history → fresh start; only customers may be seeded
  (open question #1).

---

## 9. Risks & prerequisites

- **HTTPS before P7** (device signature + field use need secure context): pending nginx
  card is on the board — do it before P7, not during.
- **SQLite** is sufficient at MH volume (thousands of docs/year); keep single-DB + backup
  discipline. Revisit only if multi-user write contention ever shows in practice.
- **Payments reconciliation**: app payments are deal-truth; the bank feed in the finance
  software stays legal truth. Monthly eyeball reconciliation, no GL sync.
- **Discipline guards**: deal creation must stay <30 s; van consumption one tap; shortfall
  two taps. If any grows beyond that in use, simplify the form, not the model.
- **Adjustment movements** are the one hand-editable ledger event: mandatory note, land in
  the admin audit log.
- Phase numbering P4–P7 continues the repo's historical P0–P3; cosmetic conflict noted in
  the note — renaming optional (open question #3).
