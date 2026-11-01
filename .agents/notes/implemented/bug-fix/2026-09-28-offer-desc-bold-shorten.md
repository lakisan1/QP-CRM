# Agent Note: offer-desc-bold-shorten

Status: implemented

## Problem

The V4400 COMMANDER description (added earlier today) and the Geoliner 678 description rendered in offers as plain paragraphs without emphasis — no bold feature names — and both were far too long: V4400 ~2.4k chars of prose paragraphs and Geoliner 678 ~4.7k chars, spanning 2 PDF pages in an offer line cell. The user asked for feature names to stand out (bold/characteristics) and for the text to be shortened.

## Decision

`products.description` for 279 (V4400 COMMANDER) and 259 (Geoliner 678) now uses the same markdown idiom as the older catalog rows: bold lead line, `* **NAZIV** – opis` bullet lists, bold inline labels. V4400: 7 key-feature bullets + one bold "PODEŠAVANJA / MERENJA:" paragraph with `·`-separated spec names (19 items on one line, no table) + bold price line. 678: all 18 features kept as bullets with bold feature names, wording compressed. Offer lines snapshot `item_description` at creation (qp_crm/offer/routes/offers.py:632), so the two existing snapshots referencing these products were updated in the same transaction: offer_items 473 (offer 114 / P-1250) and 477 (offer 115 / P-1251). Rendered output verified with the same markdown pipeline the offer template uses (`| md | safe`, extensions `extra`+`nl2br`, fix_markdown_lists).
## Alternatives considered

**Two-column markdown table for PODEŠAVANJA/MERENJA** — rejected: the offer line cell is narrow (name/qty/price columns share the row); a wide table would overflow the PDF page width, and `pdf.css` styles table content inside `.markdown-content` poorly at `font-size: smaller`. **Compact single-line separator list (`·`) for the 678 feature bullets too** — rejected: the 18 feature names carry distinct explanations that the user still wants visible; only the V4400 spec list (bare names with no descriptions) was collapsed to a separator line. **Update only `products.description` and let the user re-pick the product in offers** — rejected: offers store `item_description` as a snapshot at line creation (P-1250/P-1251 were already created today); leaving stale 2-page text in existing offers would not fix the user's actual complaint without manual rework of both offers. **Also shorten the other long Geoliner/Monty descriptions (678 was the longest of 18 >2k rows)** — not asked; user named exactly 279 and 259.
## Consequences

Existing offers do NOT re-render automatically: only snapshots for P-1250 (item 473) and P-1251 (item 477) were synced because those are the only two offer lines referencing these products; any future offer picks up the new text from `products.description` automatically. The V4400 spec list lost its per-item bullet layout (now one separator line) — feature names remain, explanations for them never existed on the site. The 678 wording was compressed by hand (not verbatim site text), so some vendor phrasing was dropped; the full original text remains recoverable from backup `app_data/pricing.db.pre-desc-shorten.20260928-100935.bak`. The `URL:` suffix line is now the only unbolded plain paragraph left, kept deliberately as a source link.

