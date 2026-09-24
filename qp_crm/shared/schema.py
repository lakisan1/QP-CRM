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
            photo_path TEXT,
            website_url TEXT,        -- optional link to the product's web page
            manufacturer_url TEXT,   -- optional link to the manufacturer's page
            product_code TEXT,       -- optional external ID / catalogue code (offer-invisible)
            item_type TEXT NOT NULL DEFAULT 'proizvod'  -- 'proizvod' | 'usluga'
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
            admin_fee REAL DEFAULT 50.0,
            status TEXT NOT NULL DEFAULT 'u_izradi'
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

    # 3c. Optional informational fields on the product itself. Deliberately
    # offer-invisible: they never flow into offer_items snapshots or any
    # offer/PDF template -- they surface only on product pages (pricing form,
    # products list, sale view).
    add_column_if_missing(cur, "products", "website_url TEXT")
    add_column_if_missing(cur, "products", "manufacturer_url TEXT")
    # 3d. Optional external product ID / catalogue code (vendor sku, kataloški
    # broj). Free text, empty-as-NULL, offer-invisible like 3c.
    add_column_if_missing(cur, "products", "product_code TEXT")
    # 3e. Item type: physical product or service (user request 2026-09-23,
    # REQUIRED on the form). NOT NULL DEFAULT 'proizvod' backfills every
    # existing row as a physical product (user: everything so far is one).
    add_column_if_missing(cur, "products", "item_type TEXT NOT NULL DEFAULT 'proizvod'")
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


def migrate_rent_tables(cur):
    """rent ALTERs for legacy databases (verbatim from rent/app.py)."""
    add_column_if_missing(cur, "rent_contracts", "is_signed INTEGER DEFAULT 0")
    # 2026-09-24 (user request): contract lifecycle status replaces the
    # is_signed boolean. Legacy rows translate once: signed -> 'potpisan_
    # ugovor', everything else -> the default 'u_izradi'. Idempotent (only
    # NULL/unset rows are matched, and the column DEFAULT fills fresh ones);
    # the is_signed column itself stays in the schema untouched -- old
    # backups/fixtures keep inserting it, no reader uses it anymore.
    add_column_if_missing(
        cur, "rent_contracts", "status TEXT NOT NULL DEFAULT 'u_izradi'")
    cur.execute("""
        UPDATE rent_contracts
        SET status = 'potpisan_ugovor'
        WHERE is_signed = 1 AND status = 'u_izradi';
    """)


# ---------------------------------------------------------------------------
# contacts module tables (P5-pre — the shared directory)
# ---------------------------------------------------------------------------

# Fixed KIND list (extend only by migration -- same discipline as the stock
# movement reasons, blueprint §5). One row per directory entry, human OR
# organization; legal-entity fields are simply empty for a person.
CONTACT_KINDS = ("company", "person")

# Fixed ROLE list: what the entry IS to the business. A contact may hold
# several roles at once (a company can be a supplier AND a client; an
# external collaborator is a person who is also a supplier).
CONTACT_ROLES = (
    "client",                # kupac / klijent
    "supplier",              # dobavljač
    "employee",              # zaposleni
    "external_collaborator", # spoljni saradnik
    "partner",               # partner
    "other",                 # ostalo
)


def create_contacts_tables(cur):
    """contacts, contact_roles, contact_links (P5-pre; the deals-spine
    customers tables were REMOVED by user decision 2026-09-16 -- the
    directory is now the ONLY party registry). Roles are ROWS
    (contact_roles), not boolean columns: a role arriving later is a new
    value in the fixed list, never a new column.

    Conventions:
      * NO deletes -- a contact archives (archived=1); documents that
        reference one keep resolving it by id (rename-safe, amendment 6b).
      * id + snapshot: consumers snapshot the fields they print (rent
        contracts already copy client_* columns; offers keep their client
        header) -- the directory never rewrites issued documents.
      * names resolved at read time: nothing stores a contact's name as a
        key. display_name is THE master name for humans and orgs alike
        (amendment 6b: rename = editing one master row).
      * person OR organization in one table (user decision, P5-pre chat):
        kind='person' rows hold first/last name + JMBG and leave PIB/MB
        empty; kind='company' rows are the inverse. One party model instead
        of two parallel tables that would need a union view everywhere.
      * user_id links an employee role to the app login account
        (nullable: the directory may list employees who never log in, and
        a login account may exist without a directory entry).
    """
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL DEFAULT 'company',
            display_name TEXT NOT NULL,
            first_name TEXT, last_name TEXT,
            jmbg TEXT,
            pib TEXT, mb TEXT,
            account TEXT,
            billing_address TEXT, city TEXT,
            postal_code TEXT, country TEXT,
            email TEXT, phone TEXT,
            job_title TEXT,
            user_id INTEGER REFERENCES users(id),
            notes TEXT,
            created_at TEXT,
            archived INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contact_roles (
            contact_id INTEGER NOT NULL REFERENCES contacts(id),
            role TEXT NOT NULL,
            PRIMARY KEY (contact_id, role)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS contact_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL REFERENCES contacts(id),
            name TEXT,
            address TEXT, city TEXT,
            postal_code TEXT, country TEXT,
            contact_name TEXT, contact_phone TEXT,
            notes TEXT
        );
    """)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_name ON contacts(display_name);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contacts_user ON contacts(user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_contact_locations_contact ON contact_locations(contact_id);")


def migrate_contacts(cur):
    """Contacts-side idempotent migrations (P5-pre + unification).

    1. Link columns: consumers reference the directory by id; issued
       documents keep their field snapshots (amendment 6d -- the directory
       never rewrites them). offers/rent_contracts gain contact_id.
    2. Backfill: legacy rent_clients rows become directory contacts
       (kind=company, role=client) exactly once, tracked by
       rent_clients.migrated_contact_id. The legacy table survives as a
       read-only seed source -- /rent/clients redirects to the directory.
    """
    add_column_if_missing(cur, "offers", "contact_id INTEGER REFERENCES contacts(id)")
    add_column_if_missing(cur, "rent_contracts", "contact_id INTEGER REFERENCES contacts(id)")
    add_column_if_missing(cur, "rent_clients", "migrated_contact_id INTEGER REFERENCES contacts(id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_offers_contact_id ON offers(contact_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rent_contracts_contact ON rent_contracts(contact_id);")

    # 2026-09-24 (user request): locations gain postal code + country --
    # ALTERs for legacy DBs; the canonical CREATE already carries them.
    add_column_if_missing(cur, "contact_locations", "postal_code TEXT")
    add_column_if_missing(cur, "contact_locations", "country TEXT")
    add_column_if_missing(cur, "contacts", "postal_code TEXT")

    backfill_rent_clients_into_contacts(cur)

    # Musterija-first era (user request 2026-09-22): link legacy documents
    # to the directory so the imenik shows every client's history. Idem-
    # potent: only contact_id IS NULL rows are matched; ambiguous rows
    # (PIB/MB vs name conflicts) stay unlinked for manual review.
    from qp_crm.services.contact_service import link_documents_to_contacts
    link_documents_to_contacts(cur)


def backfill_rent_clients_into_contacts(cur):
    """Copy every not-yet-migrated rent_clients row into contacts.

    One-way, idempotent, name-merge aware:
      * map legacy fields -> directory fields (representative -> job_title,
        rent_address/guarantor -> notes so no legacy data is dropped);
      * a rent_client whose (PIB, MB) already exists on a directory contact
        links to it instead of duplicating (second occurrence of the same
        company is the same party);
      * migrated_contact_id records the copy so re-boots never duplicate;
      * role is always 'client' (these were renters -- the klijent base).
    """
    cur.execute("""
        SELECT id, name, mb, pib, account, address, representative, email,
               rent_address, guarantor, migrated_contact_id
        FROM rent_clients
        WHERE migrated_contact_id IS NULL;
    """)
    legacy_rows = cur.fetchall()
    for row in legacy_rows:
        match = None
        if (row["pib"] and row["pib"].strip()) or (row["mb"] and row["mb"].strip()):
            cur.execute(
                """
                SELECT id FROM contacts
                WHERE (pib IS NOT NULL AND pib = ?) OR (mb IS NOT NULL AND mb = ?)
                LIMIT 1;
                """,
                (row["pib"] or "\0", row["mb"] or "\0"),
            )
            match = cur.fetchone()
        if match is not None:
            contact_id = match["id"]
        else:
            notes_parts = []
            if row["rent_address"]:
                notes_parts.append(f"Adresa zakupa: {row['rent_address']}")
            if row["guarantor"]:
                notes_parts.append(f"Jemac: {row['guarantor']}")
            cur.execute(
                """
                INSERT INTO contacts (kind, display_name, pib, mb, account,
                                      billing_address, email, phone, job_title,
                                      notes, created_at, archived)
                VALUES ('company', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0);
                """,
                (
                    row["name"],
                    row["pib"], row["mb"], row["account"],
                    row["address"], row["email"], None,
                    row["representative"],
                    "\n".join(notes_parts) or None,
                    row["rent_address"] or None,
                ),
            )
            contact_id = cur.lastrowid
            cur.execute(
                "INSERT OR IGNORE INTO contact_roles (contact_id, role) VALUES (?, 'client');",
                (contact_id,),
            )
        cur.execute(
            "UPDATE rent_clients SET migrated_contact_id = ? WHERE id = ?;",
            (contact_id, row["id"]),
        )
