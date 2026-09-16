"""Single-source QP-CRM database schema (Phase 2 stage 3).

Every CREATE TABLE/INDEX lives here. The per-module init_db functions
(pricing/app.py, offer/app.py, admin/app.py, rent/app.py) are thin wrappers
that execute these functions against their own connection, preserving the
boot sequence pricing_init_db -> pricing_migrate_schema -> offer_init_db ->
admin_init_db -> rent_init_db.

Canonical union of the historical duplicates:

* ``offers``/``offer_items`` were created in pricing/app.py with a subset of
  the columns offer/app.py needed and then ALTERed into shape by
  offer.init_db. The canonical definitions below are the offer supersets
  (country, is_template, client_pib, client_mb, discount_percent live in the
  CREATE instead of being appended by ALTER on a fresh database). All code
  addresses columns BY NAME, so the mid-table vs appended position is
  irrelevant; pricing's stale subset CREATEs are deleted.

* The idempotent ALTER migrations are kept verbatim (legacy databases may
  lack any of these columns; on fresh ones they are no-ops). The pricing
  step-3 trio and the site_products.included_items ALTER were duplicated
  between init_db and migrate_schema -- one copy each now.

* New UNIQUE constraint (the only data-safe one): products.name
  case-insensitive. Creation is guarded -- if legacy data carries duplicate
  names the boot still succeeds and only a warning is printed. NO other
  UNIQUE constraints were added: offers.offer_number, prices(product_id,
  date), price_rounding_rules.min/max and rent_contracts.contract_number
  all legally carry duplicates today (duplicate-offer copies, price
  history, bracket boundaries, imported contracts).
"""

import sqlite3


# ---------------------------------------------------------------------------
# pricing module tables
# ---------------------------------------------------------------------------

def create_pricing_tables(cur):
    """products, category_pricing_defaults, brands, global_settings (+seed),
    site_products, prices. Verbatim from pricing/app.py init_db."""

    # Products table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            brand TEXT,
            photo_path TEXT
        );
    """)

    # Category defaults table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS category_pricing_defaults (
            category TEXT PRIMARY KEY,
            import_percent REAL,        -- e.g. 0.07 for 7%
            margin_percent REAL,        -- e.g. 0.40 for 40%
            domestic_transport REAL,    -- fixed cost per unit
            default_extras REAL,        -- extra costs per unit
            warranty_percent REAL,
            service_percent REAL,
            instalation REAL,
            traning REAL,
            other REAL
        );
    """)

    # Brands table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS brands (
            name TEXT PRIMARY KEY
        );
    """)

    # Global Settings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS global_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # Set default date format if not exists
    cur.execute("INSERT OR IGNORE INTO global_settings (key, value) VALUES ('date_format', 'YYYY-MM-DD');")

    # Website sync snapshot table (Sajt <-> CRM product sync, manual only)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS site_products (
            id           INTEGER PRIMARY KEY,   -- WP product ID
            name         TEXT NOT NULL,
            url          TEXT,
            brand_id     INTEGER,               -- WP brand ID
            brand_name   TEXT,                  -- denormalized for display speed
            cat_id       INTEGER,               -- WP category ID (first category)
            cat_name     TEXT,
            image_url    TEXT,
            modified     TEXT,
            fetched_at   TEXT,
            included_items TEXT                -- ACF 'Obim isporuke' (what's in the box)
        );
    """)

    # Prices table (base definition)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            date TEXT NOT NULL,

            base_price REAL NOT NULL,       -- CENA
            extras REAL DEFAULT 0,          -- dodaci
            import_percent REAL,            -- tro.uvoz (0.07 = 7%)
            margin_percent REAL,            -- marža (0.40 = 40%)
            domestic_transport REAL,        -- Dom. tr.

            warranty_percent REAL,
            service_percent REAL,
            instalation REAL,
            traning REAL,
            other REAL,

            base_total REAL,                -- base_price + extras
            cost_total REAL,                -- total cost
            calculated_price REAL,          -- theoretical price
            final_price REAL,               -- your nice rounded price
            profit_final REAL,              -- final_price - cost_total

            discount_percent REAL,          -- 0.10 for 10% discount
            discount_price REAL,            -- final_price after discount
            profit_discount REAL,           -- discount_price - cost_total

            FOREIGN KEY (product_id) REFERENCES products(id)
        );
    """)


# ---------------------------------------------------------------------------
# offers / offer_items (canonical definitions -- see module docstring)
# ---------------------------------------------------------------------------

def create_offer_tables(cur):
    """offers + offer_items (canonical supersets) and their indexes.

    Compared with pricing's stale subset CREATE: country/is_template/
    napomena and the special/third discount columns are in the CREATE, and
    client_pib/client_mb (which existed ONLY as offer ALTERs) are folded in
    after client_phone. offer_items carries discount_percent in the CREATE.
    """

    # Offers table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_number TEXT,
            date TEXT,
            client_name TEXT,
            client_address TEXT,
            client_email TEXT,
            client_phone TEXT,
            client_pib TEXT,
            client_mb TEXT,
            country TEXT,

            currency TEXT,
            exchange_rate REAL,

            discount_percent REAL,
            vat_percent REAL,

            total_net REAL,
            total_discount REAL,
            total_net_after_discount REAL,
            special_discount_percent REAL DEFAULT 0.0,
            total_special_discount REAL DEFAULT 0.0,
            total_net_after_special_discount REAL DEFAULT 0.0,
            third_discount_percent REAL DEFAULT 0.0,
            total_third_discount REAL DEFAULT 0.0,
            total_net_after_third_discount REAL DEFAULT 0.0,
            total_vat REAL,
            total_gross REAL,

            payment_terms TEXT,
            delivery_terms TEXT,
            validity_days INTEGER,
            notes TEXT,
            napomena TEXT,
            is_template INTEGER DEFAULT 0
        );
    """)

    # Offer items table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS offer_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            offer_id INTEGER NOT NULL,
            product_id INTEGER,
            line_order INTEGER,
            item_name TEXT NOT NULL,
            item_description TEXT,
            item_photo_path TEXT,
            quantity REAL NOT NULL,
            unit_price REAL NOT NULL,
            discount_percent REAL DEFAULT 0.0,
            line_net REAL NOT NULL,
            FOREIGN KEY (offer_id) REFERENCES offers(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
    """)

    # Indexes (previously created in pricing.init_db, which owned the stale
    # duplicate CREATEs; they belong with the tables' single definition)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_client_name ON offers(client_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_offer_number ON offers(offer_number);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offer_items_offer_id ON offer_items(offer_id);")


# ---------------------------------------------------------------------------
# admin module tables
# ---------------------------------------------------------------------------

def create_admin_tables(cur):
    """text_presets, pdf_templates, price_rounding_rules. Verbatim from
    admin/app.py init_presets_table / init_pdf_templates_table /
    init_rounding_rules_table."""

    cur.execute("""
        CREATE TABLE IF NOT EXISTS text_presets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL, -- 'delivery', 'note', 'extra'
            name TEXT NOT NULL,
            content TEXT,
            is_default INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pdf_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            header_html TEXT,
            body_html TEXT,
            footer_html TEXT,
            css TEXT,
            is_readonly INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS price_rounding_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target TEXT NOT NULL, -- 'price' or 'discount'
            limit_val REAL NOT NULL,
            step_val REAL NOT NULL,
            method TEXT DEFAULT 'UP' -- 'UP', 'DOWN', 'NEAREST'
        );
    """)


# ---------------------------------------------------------------------------
# rent module tables
# ---------------------------------------------------------------------------

def create_rent_tables(cur):
    """rent_clients, rent_equipment, rent_contracts, rent_templates,
    rent_contract_documents. Verbatim from rent/app.py init_db."""

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mb TEXT,
            pib TEXT,
            account TEXT,
            address TEXT,
            representative TEXT,
            email TEXT,
            rent_address TEXT,
            guarantor TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0,
            default_rent_months INTEGER DEFAULT 48,
            default_guarantee_rate REAL DEFAULT 5.0,
            default_downpayment_percent REAL DEFAULT 20.0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_number TEXT,
            contract_date TEXT,
            client_name TEXT,
            client_mb TEXT,
            client_pib TEXT,
            client_account TEXT,
            client_address TEXT,
            client_representative TEXT,
            client_email TEXT,
            rent_address TEXT,
            guarantor TEXT,
            delivery_time TEXT,
            delivery_date TEXT,
            equipment_model TEXT,
            price REAL DEFAULT 0,
            vat_percent REAL DEFAULT 20.0,
            period_months INTEGER DEFAULT 48,
            downpayment_percent REAL DEFAULT 20.0,
            salvage_value_percent REAL DEFAULT 20.0,
            interest_rate REAL DEFAULT 14.0,
            insurance_rate REAL DEFAULT 1.13,
            guarantee_rate REAL DEFAULT 5.0,
            admin_fee REAL DEFAULT 50.0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            content_html TEXT NOT NULL DEFAULT ''
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rent_contract_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contract_id INTEGER NOT NULL,
            template_slug TEXT NOT NULL,
            custom_content_html TEXT NOT NULL DEFAULT '',
            updated_at TEXT,
            UNIQUE(contract_id, template_slug)
        );
    """)


# ---------------------------------------------------------------------------
# auth subsystem tables (Phase 3)
# ---------------------------------------------------------------------------

def create_users_table(cur):
    """Single user-account table for the whole stack (Phase 3 step 1).

    Replaces the four legacy per-app passwords stored in global_settings
    (keys admin_password / pricing_password / offer_password / rent_password,
    with shared.auth.DEFAULT_PASSWORDS as the fallback when no row existed).
    Roles: 'admin' (everything) and 'staff' (pricing/offer/rent business
    modules); sale/settings and /api/v1/health stay public.
    password_hash is a werkzeug generate_password_hash() serialization
    (scrypt:"..." for rows created/changed on and after Phase 3).
    must_change_password is retired: the column exists for schema
    compatibility and every writer keeps it at 0 -- password changes live
    exclusively in Admin -> Users (no self-service page, no forced detour).
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'staff',
            is_active INTEGER NOT NULL DEFAULT 1,
            must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_login TEXT
        );
    """)

    # Per-user API keys (Phase 3 step 7). The RAW key is shown exactly once
    # at issue time and never stored -- only its SHA-256 hash plus a short
    # display prefix. Revocation is is_active = 0 (rows are kept for the
    # audit trail). The legacy global api_key in global_settings stays valid
    # during the transition and is deprecated (see API_INSTRUCTIONS.md).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            label TEXT DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            last_used TEXT
        );
    """)

    # API audit log (Phase 3 step 7): one row per authenticated /api/v1
    # request. kind='user' carries the username attribution; 'user-denied'
    # audits a refused revoked key / deactivated holder. The legacy 'global'
    # kind stopped occurring when the shared key was retired (2026-09-16).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            kind TEXT NOT NULL,
            username TEXT,
            status INTEGER NOT NULL
        );
    """)

    # Login audit log (Phase 3 step 8): every login attempt -- successful or
    # not -- with the source IP. detail is a short reason code/message
    # ('ok', 'bad password', 'unknown user', 'inactive account',
    # 'lockout: NNs remaining', ...).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS login_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            username TEXT,
            ip TEXT,
            success INTEGER NOT NULL,
            detail TEXT
        );
    """)

    # Per-user app access (post-Phase-3 user request): WHICH business module
    # a staff user may open. admin-role users bypass this check entirely
    # (superset). Seeding grants existing staff all three modules so the
    # migration never removes access; the admin trims from the Users UI.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_modules (
            user_id INTEGER NOT NULL REFERENCES users(id),
            module TEXT NOT NULL,
            UNIQUE(user_id, module)
        );
    """)


# ---------------------------------------------------------------------------
# deals module tables (Phase 4 — the deals spine)
# ---------------------------------------------------------------------------

def create_deals_tables(cur):
    """customers, customer_locations, deal_counters, deals, deal_events.

    Three-level party model (blueprint §2, note amendments 1/6):
      customer (who pays) -> location (where work happens) -> deal (the thread).
    Conventions applied here (blueprint §4):
      * names resolved at read time -- callers JOIN customers/locations by id,
        nothing stores another entity's name as its key;
      * NO deletes -- customers archive (archived=1), locations and deals
        stay (no workflow ever deletes a deal row);
      * statuses are NOT stored -- derived in deal_service from linked
        documents + events;
      * deal code D-YYYY-NNN is UNIQUE (it is the human reference in emails)
        and comes from the per-year deal_counters row (global per-year
        sequence, per blueprint §5 numbering rule).
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            pib TEXT, mb TEXT,
            billing_address TEXT, city TEXT, country TEXT,
            email TEXT, phone TEXT,
            notes TEXT,
            created_at TEXT,
            archived INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS customer_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            name TEXT,
            address TEXT, city TEXT,
            contact_name TEXT, contact_phone TEXT,
            notes TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS deal_counters (
            year INTEGER PRIMARY KEY,
            last_number INTEGER NOT NULL DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            customer_id INTEGER NOT NULL REFERENCES customers(id),
            location_id INTEGER REFERENCES customer_locations(id),
            title TEXT NOT NULL,
            owner_user_id INTEGER REFERENCES users(id),
            created_at TEXT,
            closed_at TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS deal_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id INTEGER NOT NULL REFERENCES deals(id),
            event_type TEXT NOT NULL,
            author_user_id INTEGER REFERENCES users(id),
            body TEXT,
            linked_doc_type TEXT,
            linked_doc_id INTEGER,
            created_at TEXT
        );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_deals_customer ON deals(customer_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deals_code ON deals(code);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deal_events_deal ON deal_events(deal_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_customer_locations_customer ON customer_locations(customer_id);")

    # --- invoices + payments (Phase 4.x): the financial tail of a deal ---
    create_invoices_tables(cur)


def create_invoices_tables(cur):
    """invoices, invoice_items, payments, invoice_counters (Phase 4.x).

    Conventions carried over from the deal spine (blueprint §4/§5):
      * issuance-time snapshot -- client fields + items are COPIED from the
        accepted offer when the invoice is issued; later edits to the offer
        or the customer master data never leak into issued invoices;
      * NO deletes -- an invoice is voided (voided_at), payments are never
        deleted (mistakes are corrected by a reversing entry, not a DELETE);
      * invoice status is NOT stored -- 'paid' is derived at read time by
        comparing SUM(payments.amount) with total_gross;
      * code F-YYYY-NNN comes from the GLOBAL per-year invoice_counters
        bucket (user decision: one sequence for all invoices, no
        per-customer or per-deal series).
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoice_counters (
            year INTEGER PRIMARY KEY,
            last_number INTEGER NOT NULL DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            deal_id INTEGER NOT NULL REFERENCES deals(id),
            customer_id INTEGER REFERENCES customers(id),
            location_id INTEGER REFERENCES customer_locations(id),
            source_offer_id INTEGER REFERENCES offers(id),
            issue_date TEXT,
            due_date TEXT,
            currency TEXT,
            exchange_rate REAL DEFAULT 1.0,
            total_gross REAL DEFAULT 0,
            -- issuance-time client snapshot (frozen copy from the offer)
            client_name TEXT, client_address TEXT, client_email TEXT,
            client_phone TEXT, client_pib TEXT, client_mb TEXT, client_country TEXT,
            notes TEXT,
            created_at TEXT,
            voided_at TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoice_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id),
            position INTEGER DEFAULT 0,
            description TEXT,
            qty REAL DEFAULT 1,
            unit TEXT,
            unit_price REAL DEFAULT 0,
            discount_percent REAL DEFAULT 0,
            line_total REAL DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id INTEGER NOT NULL REFERENCES invoices(id),
            paid_at TEXT,
            amount REAL NOT NULL,
            currency TEXT,
            method TEXT,
            reference TEXT,
            note TEXT,
            created_by_user_id INTEGER REFERENCES users(id),
            created_at TEXT
        );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoices_deal ON invoices(deal_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoices_code ON invoices(code);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_invoice ON payments(invoice_id);")


def migrate_deals(cur):
    """Deals-side idempotent migrations (Phase 4).

    offers gain deal_id/location_id (blueprint §2: offers keep working,
    gain the link columns). Legacy databases ALTERed on boot; fresh
    canonical CREATEs carry the columns already via migrate_offer_tables.
    """
    add_column_if_missing(cur, "offers", "deal_id INTEGER REFERENCES deals(id)")
    add_column_if_missing(cur, "offers", "location_id INTEGER REFERENCES customer_locations(id)")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_deal_id ON offers(deal_id);")


# ---------------------------------------------------------------------------
# idempotent ALTER migrations
# ---------------------------------------------------------------------------

def add_column_if_missing(cur, table, column_ddl):
    """The codebase's try/except OperationalError ALTER idiom, single copy.
    column_ddl is the full 'name TYPE [DEFAULT ...]' fragment."""
    try:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column_ddl};")
    except sqlite3.OperationalError:
        # Already exists (or table missing on an exotic legacy DB) - no-op.
        pass


def migrate_users(cur):
    """Auth-side idempotent migrations (post-Phase-3 evolution).

    users.modules_set marks that a user's module grants have been
    MATERIALIZED once (either by the one-time all-modules default seed or by
    an explicit admin save in the Users UI). Without the marker, a user
    whose grants the admin deliberately emptied would be re-granted all
    modules on the next boot.
    """
    add_column_if_missing(cur, "users", "modules_set INTEGER NOT NULL DEFAULT 0")


def migrate_pricing(cur):
    """Pricing-side migrations. Verbatim pricing/app.py migrate_schema steps
    plus the ALTERs that were duplicated in init_db (site_products.
    included_items; prices discount trio) and the one new, guarded UNIQUE
    index on products.name."""

    # site_products.included_items for older DBs (was in init_db)
    add_column_if_missing(cur, "site_products", "included_items TEXT")

    # prices discount columns for legacy DBs (was duplicated in init_db AND
    # migrate_schema; single copy now)
    for col_name, col_type in (
        ("discount_percent", "REAL"),
        ("discount_price", "REAL"),
        ("profit_discount", "REAL"),
    ):
        add_column_if_missing(cur, "prices", f"{col_name} {col_type}")

    # 1. Add columns to category_pricing_defaults if missing
    new_cols = [
        ("warranty_percent", "REAL"),
        ("service_percent", "REAL"),
        ("instalation", "REAL"),
        ("traning", "REAL"),
        ("other", "REAL")
    ]
    for col_name, col_type in new_cols:
        add_column_if_missing(cur, "category_pricing_defaults", f"{col_name} {col_type}")

    # 2. Add columns to prices if missing
    for col_name, col_type in new_cols:
        add_column_if_missing(cur, "prices", f"{col_name} {col_type}")

    # 3b. Add site_product_id column to products (Sajt <-> CRM sync, 1:1 link)
    # UNIQUE so one CRM product links to at most one site product and vice versa.
    # NOTE: SQLite's ALTER TABLE ADD COLUMN cannot add a column with a UNIQUE
    # constraint, so we add a plain column and enforce uniqueness via a UNIQUE
    # index (NULLs are treated as distinct in a unique index - which is correct).
    add_column_if_missing(cur, "products", "site_product_id INTEGER")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_site_product_id ON products(site_product_id);")
    # Index for fast lookups by name when building the comparison table
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_site_products_name ON site_products(name);")

    # Phase 2 stage 3: the only data-safe new UNIQUE constraint. product
    # add/edit already reject duplicate names case-insensitively, so legacy
    # data should pass; if it does not, boot continues without the index.
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_name_unique ON products(name COLLATE NOCASE);")
    except sqlite3.OperationalError as e:
        print(f"WARNING: could not add UNIQUE index on products(name): {e}")

    # 4. Remove UNIQUE constraint from prices if present
    cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='prices'")
    row = cur.fetchone()
    # Check if constraint exists in definition
    if row and "UNIQUE" in row["sql"] and "product_id" in row["sql"] and "date" in row["sql"]:
        print("Migrating prices table: removing UNIQUE(product_id, date) constraint...")

        # Rename old table
        cur.execute("ALTER TABLE prices RENAME TO prices_old")

        # Re-create table with NEW schema (matches create_pricing_tables)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                date TEXT NOT NULL,

                base_price REAL NOT NULL,
                extras REAL DEFAULT 0,
                import_percent REAL,
                margin_percent REAL,
                domestic_transport REAL,

                warranty_percent REAL,
                service_percent REAL,
                instalation REAL,
                traning REAL,
                other REAL,

                base_total REAL,
                cost_total REAL,
                calculated_price REAL,
                final_price REAL,
                profit_final REAL,

                discount_percent REAL,
                discount_price REAL,
                profit_discount REAL,

                FOREIGN KEY (product_id) REFERENCES products(id)
            );
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_prices_product_id ON prices(product_id);")

        # Copy data
        # Since we added columns to prices_old (step 2), schemas match
        cur.execute("INSERT INTO prices SELECT * FROM prices_old")
        cur.execute("DROP TABLE prices_old")


def migrate_offer_tables(cur):
    """offers/offer_items ALTERs for legacy databases (verbatim from
    offer/app.py init_db; no-ops on the canonical fresh schema)."""

    # --- Migration for existing databases ---
    add_column_if_missing(cur, "offers", "napomena TEXT")
    add_column_if_missing(cur, "offers", "is_template INTEGER DEFAULT 0")
    add_column_if_missing(cur, "offers", "client_pib TEXT")
    add_column_if_missing(cur, "offers", "client_mb TEXT")
    add_column_if_missing(cur, "offers", "country TEXT DEFAULT 'Srbija'")
    add_column_if_missing(cur, "offers", "special_discount_percent REAL DEFAULT 0.0")
    add_column_if_missing(cur, "offers", "total_special_discount REAL DEFAULT 0.0")
    add_column_if_missing(cur, "offers", "total_net_after_special_discount REAL DEFAULT 0.0")
    add_column_if_missing(cur, "offers", "third_discount_percent REAL DEFAULT 0.0")
    add_column_if_missing(cur, "offers", "total_third_discount REAL DEFAULT 0.0")
    add_column_if_missing(cur, "offers", "total_net_after_third_discount REAL DEFAULT 0.0")

    add_column_if_missing(cur, "offer_items", "discount_percent REAL DEFAULT 0.0")

    # Phase 4: the deal-spine link columns. Kept here (not only in
    # migrate_deals) so offer_init_db alone upgrades an offers schema the
    # same way it historically absorbed its own column ALTERs.
    add_column_if_missing(cur, "offers", "deal_id INTEGER REFERENCES deals(id)")
    add_column_if_missing(cur, "offers", "location_id INTEGER REFERENCES customer_locations(id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_deal_id ON offers(deal_id);")


def migrate_rent_tables(cur):
    """rent ALTERs for legacy databases (verbatim from rent/app.py)."""
    add_column_if_missing(cur, "rent_contracts", "is_signed INTEGER DEFAULT 0")
