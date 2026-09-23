# Agent Note: product-website-manufacturer-links

Status: implemented

## Problem

The user asked for two optional link fields on a product — a link to the product's website page and a link to the manufacturer — explicitly OUTSIDE the offer flow: offers must never show them; they are only an optional attribute of the product itself. The products table had no place for such links, and the offer add_item path snapshots product data into offer_items, so the guarantee "never in offers" had to be structural, not cosmetic.

## Decision

products has two nullable TEXT columns, website_url and manufacturer_url, added in shared/schema.py both to CREATE TABLE products and as idempotent add_column_if_missing ALTERs in migrate_pricing() (step 3c). The pricing product form (product_form.html) carries two type=url inputs below Description; routes/products.py add_product/edit_product read, strip, and store empty-as-NULL, and re-render preserved values on image-processing errors. Visibility surfaces only product pages: the products list renders inline 'Website ↗ / Manufacturer ↗' links under the product name, and sale's view_product shows the URLs in the info card. api_v1 list/detail responses include both fields; create accepts them; update treats absent as keep and empty string as clear. Offer paths are untouched BY CONSTRUCTION: offer add_item snapshots only name/description/photo_path from the product row (offers.py add_item), so no offer form, item, or PDF can display the links — pinned by tests/smoke/test_product_links.py including the System-Default-DB-template regeneration path (admin init_pdf_templates_table reseeds body_html from offer_body_inner.html, which was not modified). Serbian labels are in the TRANSLATIONS sr dict; EN is the source string. Deployed: image rebuilt, container recreated, healthcheck green, live DB verified to carry both columns.
## Alternatives considered

**Offer-item snapshot columns (offer_items.website_url/manufacturer_url).** Would let offers optionally carry the links later, but the user asked for the opposite — never in offers; extra snapshot columns would also grow every item INSERT for zero current use. Rejected.

**Poping the links into the offer form as opt-in checkboxes.** Same objection: the requirement was "samo opcija koja može da se doda u proizvod", not an offer feature; a checkbox flow would put the fields on the offer UI the user explicitly excluded.

**Samofrontend-only (store links in description markdown).** Loses structure (no field, no API exposure, no sale-page rendering) and invites inconsistent free-text. A real column is the same pattern the DB already uses for site_product_id.
## Consequences

Bought: structured, API-accessible product links with one-line UI integration wherever a product is shown, plus a pinned test that the offer surface stays link-free. Cost: the System Default PDF template row is seeded from offer_body_inner.html at admin boot, so if someone later hand-edits a copied custom template expecting the links to appear, they won't — the fields must be added to a custom template's body explicitly AND would still need the route context to expose them (currently they don't). Also the products-list name cell now renders two more <a> per row when links are set — negligible, but the a11y/i18n pass owners should know the new link labels are dictionary-covered ('Website', 'Manufacturer').

