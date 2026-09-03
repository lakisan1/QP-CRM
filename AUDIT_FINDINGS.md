# QP-CRM — Code Audit Findings (2026-08-30)

Full-repo review of the Python apps (`main.py`, `shared/`, `pricing/`, `offer/`, `rent/`, `admin/`, `sale/`, `settings/`), templates, shell scripts, and root-level helper scripts. Excluded: `venv/`, `deps/`, vendored `custom_libs/markdown`, binary/data files.
Line numbers refer to the working tree on 2026-08-30 (with uncommitted changes applied).

**How to use:** each finding has an ID (e.g. `C1`), location, description, and a suggested fix. Work top-down; the "Suggested fix order" at the end is the pragmatic sequence.

---

## 🔴 CRITICAL

### C1. Werkzeug debugger exposed on all interfaces
- **Where:** `main.py:81` — `run_simple('0.0.0.0', 5000, application, use_reloader=True, use_debugger=True, threaded=True)`; same pattern in each app's `__main__` block (`pricing/app.py:1847`, `offer/app.py:1508`, `sale/app.py:219`, `settings/app.py:73`, `admin`, `rent`).
- **Problem:** Interactive debugger on 0.0.0.0 = anyone on the LAN (or worse) gets a Python console on any traceback → **remote code execution**. The debugger PIN is even logged into `main.log`.
- **Fix:** default `use_debugger=False` (opt-in via env var for dev), bind to `127.0.0.1` unless explicitly configured; run behind a production WSGI server ( waitress/gunicorn) for anything shared.

### C2. Hardcoded Flask secret keys in source
- **Where:** `pricing/app.py:45`, `offer/app.py:42`, `rent/app.py:28` (plain literals), `admin/app.py:28`, `sale/app.py:24` (env with hardcoded fallback).
- **Problem:** Anyone with repo access can forge signed session cookies (`authenticated=True`) → auth bypass for every app.
- **Fix:** single shared secret from env/`.env` (`QP_SECRET_KEY`), fail startup if missing; rotate the current ones.

### C3. Passwords: committed defaults, plaintext storage, timing-unsafe check
- **Where:** `shared/auth.py:4-9` (`DEFAULT_PASSWORDS = {admin: "Admin1", pricing: "Price1", offer: "Offer1", rent: "Rent1"}`), `get_password()` fallback (l. 88-92), `check_password()` uses `==` (l. 102). Also old rent password `Zakup1` and current `Rent1` hardcoded in root scripts `download_pdf*.py`.
- **Problem:** Default creds in repo; passwords stored plaintext in `global_settings`; no rate limiting/lockout on any login route; no hashing.
- **Fix:** store salted hashes (werkzeug `generate_password_hash`), remove defaults (force first-run password set), add simple per-IP throttle on login routes.

### C4. Server-Side Template Injection via stored PDF templates
- **Where:** `offer/app.py:1295-1297` — `render_template_string(custom_tpl["header_html"|"body_html"|"footer_html"], **ctx)` where the template text comes from the `pdf_templates` DB table, editable via `/admin/edit_pdf_template/` (`admin/app.py:673-709`, `pdf_template_edit.html`).
- **Problem:** Jinja2 template strings from the DB are executed. Attribute-access payloads (`{{ ...__globals__... }}`) escape the sandbox → code execution for anyone who can edit templates (and combined with C2/C3/CSRF, effectively anyone).
- **Fix:** render stored HTML with a non-executing sanitizer (e.g. bleach/misaka) or use a tiny placeholder syntax (`{{ name }}` replaced by string formatting on a whitelist) instead of Jinja; never `render_template_string` on user-editable content.

### C5. No CSRF protection on any state-changing route (except the settings app)
- **Where:** all POST routes in pricing/offer/rent/admin (delete product, edit prices, new/edit offers, contracts, presets, rounding rules, pdf templates, set-default buttons, etc.). Only `settings/app.py:25-42` implements a CSRF token.
- **Problem:** A logged-in operator visiting any external page can have state-changing requests fired against the CRM (e.g. `/admin/delete_preset`, `/pricing/products/1/delete`, `/admin/rounding_rules/add` — none require the re-typed admin password; factory reset and password change do, which is the only saving grace).
- **Fix:** promote the settings app's CSRF token pattern to a `shared` helper + global before-request check for non-GET, or adopt Flask-WTF globally.

---

## 🟠 HIGH — crashes / data integrity

### H1. NameError crash on duplicate offer number
- **Where:** `offer/app.py:653` — `current_language=current_language` in the "duplicate offer number" branch of `new_offer`. `current_language` is only defined in the `if errors:` branch (l. 575) and the GET path (l. ~772).
- **Problem:** With `allow_duplicate_names=false`, submitting a duplicate number → `NameError` → 500 instead of the intended error page.
- **Fix:** fetch language in that branch (same 3 lines as l. 573-575) — also add `presets_by_cat`/`mandatory_fields` for a complete re-render.

### H2. Payment presets dropdown empty on offer edit page
- **Where:** `offer/app.py:1130` — `presets_by_cat = {'delivery': [], 'note': [], 'extra': []}` (missing `'payment'`), while the other two builders (l. 561, 691) include it.
- **Fix:** include `'payment'` key; better: one shared helper that groups presets by category.

### H3. `cleanup_images` deletes files still referenced by offers
- **Where:** `admin/app.py:713-809`. Orphan check collects `products.photo_path` and queries `rent_equipment.photo_path` (a **column that doesn't exist** — the error is swallowed by `except sqlite3.OperationalError`), but never checks `offer_items.item_photo_path`.
- **Problem:** Saved offers snapshot only the filename; deleting a product (or renaming its photo) leaves `offer_items.item_photo_path` pointing at the file — cleanup then deletes it as "orphaned" → old offers lose images (permanent data loss).
- **Fix:** add `SELECT DISTINCT item_photo_path FROM offer_items` to the keep-set; same for the rename step. Longer term: copy the image into a snapshot per offer item (or store a content hash) instead of sharing one file.

### H4. Product delete/rename destroys shared photo files
- **Where:** `pricing/app.py:1235-1273` (delete removes the photo file), `pricing/app.py:1144-1171` (rename renames the file in place), `pricing/api_v1.py:454-489` (API delete). All ignore `offer_items.item_photo_path`.
- **Problem:** Same shared-file problem as H3 — historical offer snapshots break.
- **Fix:** reference-check before remove/rename, or per-offer-item file copies.

### H5. Full backup/restore bypasses SQLite safety → corruption / incomplete backups
- **Where:** `admin/app.py:941-1018` (`restore_full`: raw `open(DATABASE,'wb').write(data)` at l. 972-973 while the app runs in WAL mode; stale `-wal`/`-shm` sidecars remain) and `admin/app.py:890-939` (`backup_full`: `zf.write(DATABASE)` without flushing/including the WAL).
- **Problem:** Restore can leave a DB merged with a stale WAL (corruption); full backups can silently miss recent transactions. Contrast: `backup_db`/`restore_db` (l. 590-639, 841-888) already do this correctly with `sqlite3` backup API + `PRAGMA integrity_check`.
- **Fix:** `restore_full` — restore into a temp `sqlite3` connection and use `src.backup(dest_conn)` like `restore_db`; `backup_full` — write the DB into the zip via `sqlite3` backup (or `iterdump()`).
- **Also:** `restore_full` zip-slip check is `".." in member` (l. 947) — crude but acceptable; note `extractall` into `product_images` also honors stored paths.

### H6. Rent contract deletion orphans document rows; contract-number generator duplicates
- **Where:** `rent/app.py:543-549` (`delete_contract` doesn't delete `rent_contract_documents` rows; no FK declared in `init_db`, so nothing cascades); `rent/app.py:453-469` (`generate_next_contract_number` = `COUNT(*)+1`).
- **Problem:** Orphaned `rent_contract_documents` rows accumulate; deleting a contract makes the next auto-number **collide** with an existing one; concurrent creates also collide.
- **Fix:** delete documents with the contract (single transaction); generate numbers from `MAX` of the current counter or a dedicated sequence table; add FK `contract_id REFERENCES rent_contracts(id) ON DELETE CASCADE` for fresh DBs.

### H7. `duplicate_contract` crashes on NULL contract number
- **Where:** `rent/app.py:561` — `d.get("contract_number", "") + "-KOPIJA"` returns `None + str` when the column exists but is NULL.
- **Fix:** `(d.get("contract_number") or "") + "-KOPIJA"`.

### H8. Factory reset: wrong password set + `finally` NameError
- **Where:** `admin/app.py:1074-1080` — defaults dict resets admin/pricing/offer but **not** `rent_password` (inconsistent "reset"); admin is reset to weak `Admin1`; `finally: if conn:` (l. 1105-1106) raises `NameError` if `get_db()` itself failed. `DELETE FROM price_rounding_rules` runs before `init_db()`, which only **re-seeds if empty** — OK, but note the reset also wipes `site_products` + unlinking; `global_settings`/`api_key` untouched.
- **Fix:** include rent (or state intent in UI); `conn = None` before `try`; document/decide whether api_key and global settings should reset too.

### H9. SSRF + unbounded download in image-from-URL fetch
- **Where:** `pricing/app.py:474-498`, `pricing/api_v1.py:73-98` (`download_image_from_url`), used by UI and API incl. `/sync/add_product` (l. 1420-1423).
- **Problem:** Fetches **any user-supplied URL** server-side (internal-network probing: file metadata, `http://169.254...`, localhost services), reads whole body into memory with no size cap (DoS), validates only the `Content-Type` string.
- **Fix:** allowlist `http(s)` scheme + resolve host and reject private/loopback IPs; cap bytes (e.g. 10 MB via `iter_content`); validate magic bytes with PIL (`Image.open` already does — do it **before** saving).

### H10. Numeric form fields parsed with bare `float()/int()` → 500 on bad input
- **Where (representative, not exhaustive):**
  - `pricing/app.py:855-856` (quick_update_save), `1286-1295` (category-defaults), `1521-1549` (new_price), `1663-1688` (edit_price)
  - `offer/app.py:517-531` (new_offer), `840-854` (update_header), `948-953,976` (add_item: `float(unit_price)`, `int(product_id)`), `1019` (`int(request.form.get("item_id"))` → `TypeError` if missing), `1247,1252` (`int(preview_template_id)`)
  - `rent/app.py` `_contract_form` numeric parsing (`float` of price/period/etc.)
  - `admin/app.py:1172-1191` `add_rounding_rule` `int(step)/int(minimum)`
- **Problem:** Any non-numeric input (typos, comma decimals "1.234,56", malicious CSRF payloads) → unhandled `ValueError` → 500.
- **Fix:** a small `parse_num(raw, default, field, errors)` helper (put in `shared/utils.py`) + re-render with field errors; enforce `type=number`/`step` client-side too.
- **Related poison-pill:** admin saves `default_items_per_page`, `default_vat_percent`, `default_validity_days` as raw strings (`admin/app.py` update_settings), then `pricing/app.py:632`, `sale/app.py:89`, offer list parse them with `int()` — one bad admin save breaks three list pages. Validate on save.

---

## 🟡 MEDIUM

### M1. `md` filter + `| safe` = stored XSS path in offers
- **Where:** `offer/app.py:218-223` (`render_markdown`) used as `| md | safe` in `offer_view.html:86`, `offer_form.html:392`, `offer_body_inner.html:76`; same filter also in `pricing/app.py:559-564`.
- **Problem:** markdown passes raw HTML through (`extra` ext) → a product/item description containing `<script>` executes in anyone's browser viewing the offer (and in the PDF pipeline context). `sale/app.py:210` shows the correct pattern (`html.escape` **before** markdown).
- **Fix:** escape before conversion like sale does, or run output through a sanitizer; never combine user text with `| safe`.

### M2. Rent document editor renders stored HTML with `| safe`
- **Where:** `rent/templates/rent_document_editor.html:210` (contenteditable div), `rent_pdf_document.html:184`.
- **Problem:** Stored HTML/JS from `rent_templates`/`rent_contract_documents` runs in other operators' browsers. By-design rich text — but there is no sanitization and trust boundary is only the shared rent password.
- **Fix:** sanitize HTML on save (bleach allowlist: b/i/u/p/br/table/tbody/tr/td/h1-4/ul/ol/li/span+style).

### M3. Settings app: random secret fallback breaks sessions + CSRF after every reload
- **Where:** `settings/app.py:21` — `os.environ.get("SETTINGS_SECRET_KEY", secrets.token_hex(32))`.
- **Problem:** With the Werkzeug reloader/any restart, the secret changes → sessions and CSRF tokens invalidated → sporadic "CSRF token mismatch" 400s.
- **Fix:** same env-var secret strategy as C2 (or the app's own persisted key file).

### M4. Two sources of truth for `date_format` (cookie vs DB) — user setting silently ignored
- **Where:** `settings/app.py:58-63` writes `date_format` **cookie**; `pricing/app.py get_date_format()` and offer's equivalent prefer `global_settings.date_format` **DB**, which `init_db` always seeds (`pricing/app.py:109` INSERT OR IGNORE) → cookie never wins.
- **Fix:** pick one: per-user cookie should win (swap priority) or remove the settings-app control and keep the admin DB setting.

### M5. Offer list: product filter ignores the offers/templates view filter
- **Where:** `offer/app.py:382-423` — when `item_filter` is set, no `is_template` clause is applied (the non-filter branch applies it at l. 441-446).
- **Problem:** Templates appear in the offers list (and vice versa) when filtering by product; count query matches the same inconsistency (l. 451-467 only applies `view` in the else branch).
- **Fix:** apply the template clause in both branches.

### M6. Category percent heuristic silently rewrites API values
- **Where:** `pricing/api_v1.py:533-560` (`create_or_update_category`) — "if > 1.0 assume percent and divide by 100".
- **Problem:** A legitimate ≥100% value (e.g. margin 150%) becomes 1.5%; exactly `1.0` is ambiguous. Same ambiguity class exists between UI (percent numbers) vs DB (fractions).
- **Fix:** accept an explicit unit (`import_percent: 7` + `percent_units: true/false`) or always require fractions and document it; don't guess.

### M7. No uniqueness constraints → race-condition duplicates
- **Where:** `products.name` duplicate check is SELECT-then-INSERT (no UNIQUE index) — `pricing/app.py:979`, `offer/app.py:1002` (TEMP product), `api_v1` create endpoints; `offers.offer_number` duplicate check likewise. (`products.site_product_id` does have a UNIQUE index — good precedent.)
- **Fix:** add UNIQUE indexes (NOCASE for names) and convert the races to `INSERT ... ON CONFLICT DO NOTHING` + friendly error.

### M8. File/DB mutation ordering leaves orphans on failure
- **Where:** `api_v1.py:1420-1440` (`sync_add_product`: image downloaded+saved **before** the link check; rollback doesn't delete the file); `pricing/app.py:1144-1171` & `api_v1.py:403-435` (rename/delete happens before the UPDATE; a failed UPDATE leaves DB pointing at a missing file).
- **Fix:** DB commit first, then file ops; or re-apply file ops after commit with compensation on failure.

### M9. Dependency hygiene
- **Where:** `requirements.txt` (no pins; `markdown` missing — works only via vendored `custom_libs/markdown`, which is simultaneously **gitignored** yet 42 files are tracked in git; `PyMuPDF` used by `measure_pdf.py` missing; Werkzeug installed ad-hoc in `run_apps.sh:99`).
- **Problem:** Fresh `pip install -r requirements.txt` in a clean clone works only by accident of the vendored lib; unpinned versions → surprise breakage on upgrade (WeasyPrint API churn already visible in `rent/app.py` pypdf private-API use, see M10).
- **Fix:** pin versions (`pip freeze > requirements.txt` after testing), declare `markdown` (or drop custom_libs + sys.path hack), resolve the gitignore-vs-tracked inconsistency.

### M10. Private/unstable APIs: pypdf internals + WeasyPrint box traversal
- **Where:** `rent/app.py:690-830` (`writer._add_object`, `writer._root_object` — pypdf private API); `test_weasy.py` uses `page._page_box`.
- **Problem:** Breaks silently on library upgrades (and unpinned deps make that likely).
- **Fix:** pin pypdf; prefer public API (`add_page` + annotation dicts via `DictionaryObject` is fine, but object-number creation via `_add_object` should be wrapped + tested); keep the existing try/except fallbacks.

### M11. `run_apps.sh` broad `pkill` + restart scripts fragility
- **Where:** `run_apps.sh:106` `pkill -f "main.py"` matches **any** process with `main.py` in its command line (other projects, editors, agents); `restart_app.sh:4` hardcodes an absolute path; both rely on `nohup`/`setsid` + `main.log`.
- **Fix:** `pkill -f "QP-CRM/venv/bin/python main.py"` or a pidfile; derive paths from `SCRIPT_DIR`; consider a systemd unit.

### M12. Full product/site tables loaded per page render
- **Where:** `offer/app.py:1104` (dropdown loads every filtered product), `api_v1 sync_table` endpoint loads all products + all site_products each call, `sync_fetch` does one SELECT per product for change-detection (l. 1007-1033).
- **Problem:** Slow as catalog grows (already ~455 site products; comments mention 455-request slowness).
- **Fix:** server-side pagination/select2-style search endpoint; set-difference change detection with one query (e.g. hash map compare in Python).

### M13. Missing DB indexes
- **Where:** `init_db` in pricing/offer/rent defines no indexes; `prices.product_id`, `offer_items.offer_id/product_id`, `offers.date`, `rent_contracts.contract_date` are scanned repeatedly (MAX(id) subqueries per row, LIKE searches).
- **Fix:** add `CREATE INDEX IF NOT EXISTS` for those columns in init.

### M14. Admin `set_active_pdf_template` stores any string
- **Where:** `admin/app.py:830-839`; `offer_pdf` later does `int(row["value"])` (`offer/app.py:1252`) → 500 if a non-int got stored.
- **Fix:** validate int + existence before storing.

---

## 🟢 LOW / CLEANUP

- **L1. Scratch files with secrets committed in repo root:** `download_pdf.py`–`download_pdf6.py` (contain `Rent1` and old password `Zakup1`), `measure_pdf*.py` (`fitz`/PyMuPDF), `test_dests*.py`, `test_pdf_flask.py`, `test_weasy.py`, artifacts `success.pdf`, `test.pdf`, `test_fillable.pdf`. Move to `scripts/dev/` or delete; purge old password usage. `main.log` also logs the Werkzeug Debugger PIN.
- **L2. Root `pricing.db` (0 bytes) tracked in git** while `.gitignore` says DBs aren't tracked and the real DB is `app_data/pricing.db` — confusing leftover; delete it.
- **L3. Dead code:** `pricing/app.py:55` (`api_v1.` endpoint exemption — blueprint isn't registered on the sub-app under Dispatcher; harmless but misleading); POST-only route re-checking `request.method != "POST"` (`pricing/app.py:848`); `site_only = site_only` no-op assignments (`pricing/api_v1.py sync_table`); duplicated imports (`pricing/app.py` re-imports `os/sys/re/requests` at 15-16, 472, 539); unused `get_api_key, generate_api_key` import in `main.py:23`; `offer`/`pricing` template dirs each contain an orphan `settings.html`; `fix_markdown_lists` no-op branch (`offer/app.py:208-210`).
- **L4. Duplicated logic (drift risk):** `save_product_image`/`download_image_from_url` duplicated verbatim in `pricing/app.py` vs `pricing/api_v1.py`; the 3-branch product-list query duplicated in pricing/sale/offer-edit dropdown; rent placeholder-substitution block duplicated (`rent/app.py:367-389` vs `1171-1187`); `offers`/`offer_items`/`global_settings` schemas created by **both** pricing and offer init paths with slightly different definitions (lucky convergence via ALTERs — make one canonical schema module).
- **L5. LIKE search wildcards:** `%`/`_` in search terms not escaped (product/offer/rent searches) — odd results, not injection.
- **L6. `shared/countries.py`:** `"UK"` instead of ISO `GB`; `get_country_name` linear scan (fine at this size).
- **L7. Rent CSV/logo path details:** `CSV_DIR = ".../excell Rent calc"` (misspelled dir, silently no-ops if missing — ok by design but note it); `f"file://{logo_path}"` URIs (`rent/app.py:635,667,713`) break on Windows/backslashes where `offer/app.py` correctly uses `Path.as_uri()`; `_clean_num` strips `-` (negatives flip positive).
- **L8. `admin/backup_db` NamedTemporaryFile(delete=False) leaks the temp file on exception** (l. 608-617) — wrap remove in `finally`.
- **L9. `apply_rounding` opens a fresh DB connection per call** (`pricing/app.py:357-388`) — pass an open conn or cache rules per request.
- **L10. "Latest price" ordering inconsistency:** list views join on `MAX(prices.id)`, while `offer/app.py` latest-price subquery and quick_update use `ORDER BY date DESC` (no id tiebreak) — same-day rows can disagree. Standardize on `ORDER BY date DESC, id DESC` or MAX(id).
- **L11. Floats for money everywhere (REAL columns):** rounding artifacts accumulate; consider integer cents or `Decimal` at least in `recalc_totals`/`calculate_rent`.
- **L12. No session regeneration after login** (minor session-fixation surface with signed cookies).
- **L13. Error-flash inconsistency:** three mechanisms coexist — `flash()` (admin), `session["error_message"]` (offer), `?error=` query params (pricing) — standardize.
- **L14. `check_auth` exempt lists differ per app** (offer exempts its NBS-rate endpoint, pricing does not exempt `/api/nbs_rate`) — harmless today, confusing later. Also 404s (endpoint=None) redirect to login in pricing.
- **L15. PIL image handling:** no `Image.MAX_IMAGE_PIXELS` guard (decompression bombs) and admin `upload_logo` saves non-PNG uploads byte-for-byte after only an extension check (`admin/app.py:404-435`) — re-encode everything through PIL.
- **L16. `sync_table` filters:** `crm_only`/`site_only` self-assignments and the `'crm_missing'` filter silently including `linked_missing_site` pairs — intentional? clarify with comments.

---

## Suggested fix order (pragmatic)

1. **C1** (kill debugger exposure) + **C2** (move secrets) — 30 minutes, removes the scariest exposure.
2. **C3** password hashing + remove defaults; add login throttle.
3. **H1**, **H2**, **H7**, **M14** — trivial one-file fixes for live crashes/UX bugs.
4. **C5** global CSRF (reuse the settings-app pattern).
5. **H3/H4** shared-image reference check (stop the data loss; add `cleanup_images` dry-run mode first).
6. **H5** make backup/restore consistently use the SQLite backup API.
7. **C4 + M1 + M2** — replace stored-template Jinja execution and sanitize all `| safe` paths.
8. **H6**, **H9**, **H10**, then the Medium/Long tail (indexes, pins, dedup shared helpers).

*Generated by an automated read-through; every finding was verified against the code at the cited lines. Re-check line numbers after edits.*
