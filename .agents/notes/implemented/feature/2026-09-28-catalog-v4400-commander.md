# Agent Note: catalog-v4400-commander

Status: implemented

## Problem

The user asked to add a new device to the QP-CRM catalog: the Hofmann V4400 Commander wireless drive-through wheel-alignment system from https://autoservisnaoprema.com/katalog/reglaza-trapa/v4400-commander/, categorized under brand Hofmann / category Geoliner, following the same pattern as previously added devices (e.g. the EAE lifts, Geoliner series). The catalog lives in `app_data/pricing.db` (`products` table) with images in `app_data/product_images/`.

## Decision

Product id 279 in `app_data/pricing.db`: name "V4400 COMMANDER", category "Geoliner", brand "Hofmann", item_type "proizvod", tracking_regime "untracked" (same as every Geoliner row). Description carries the site's full short-description paragraphs plus the PODEŠAVANJA/MERENJA spec table as bullet list and the catalog price line (27.300,00 € bez PDV-a), ending with the established "URL: https://autoservisnaoprema.com/katalog/reglaza-trapa/v4400-commander/" suffix; `website_url` holds the same URL (convention of the newest batch, products #272+). Photo downloaded from the site gallery (VA-4400-COMMANDER.jpg) and stored as `app_data/product_images/v4400_commander.jpg`, matching the slug-derived `photo_path` naming of prior rows. NOT done: no `prices` row (prices are user-entered documents in this app — 110 of 256 products have none), no `product_code`, no `manufacturer_url` (the site is Hofmann-Srbija's shop, not the manufacturer), no `site_product_id` (the `site_products` table is empty and unused). "Hofmann" already exists in `brands` and "Geoliner" in `category_pricing_defaults`, so no lookup rows were added.
## Alternatives considered

**Insert only a name + category stub and let the user fill the rest in the UI** — rejected: the user asked for the device to be added based on how prior devices were added; prior rows carry full descriptions, photos and (since ~#272) the site URL in `website_url`, so a stub would not match the established pattern and would leave the catalog incomplete. **Also seed a `prices` row with the catalog price (27.300 €)** — rejected: price rows are user-created documents with margin/import/discount calculations (only 153 rows for 256 products; even recent Hofmann site-imported products have none); fabricating pricing parameters would put a wrong sellable price into offers. **Scrape via the app's own `add_product` POST route** — rejected: requires a running server + session auth for a one-off insert; direct SQL against the same schema with the same duplicate check (`name = ? COLLATE NOCASE`) reproduces the route's constraints with less moving parts. **Dedupe via `site_product_id`/`site_products` (WP REST sync)** — rejected: the table is empty and `site_product_id` is unused on all 256 products; the live convention is `website_url` + description suffix.
## Consequences

The product has NO `prices` row — it shows no price until the user creates one in the UI (category defaults for Geoliner: import 7%, margin 40%, transport 100 apply as form defaults when they do). The description embeds the catalog price as plain text; if the site price changes, the text must be edited manually like every other row. The photo (1000×1500, 367 KB) was stored at the original WordPress resolution, not the app's `save_product_image` processing pipeline, so minor differences in normalization (EXIF/progressive JPEG) are possible versus UI-uploaded images. Backup `app_data/pricing.db.pre-v4400-commander.20260928-095112.bak` should be cleaned up with the other stale .bak files later.

