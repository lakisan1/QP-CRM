# Agent Note: description-standard-v2

Status: implemented

## Problem

Lazar reviewed my rules audit and set the definitive product-description standard for QP-CRM going forward: character limit raised to 2000, URLs moved out of description text into dedicated product fields, "O proizvođaču" permanently banned from descriptions, "OBIM ISPORUKE" required in description when the source has it — plus a general writing style requirement (short, concise, informative). The prior rules doc (pravila-tekst-proizvoda.md) contradicted this on two points: it mandated `URL:` as the last description line and capped length at 1000 chars.

## Decision

Standard (Lazar, 2026-09-28) for all product descriptions I write or rewrite in QP-CRM from now on: LIMIT — max 2000 characters, target shorter whenever the source allows (kratko, koncizno, informativno); FORMAT — standard markdown structure: bold lead line naming device + model, `PROIZVODJAC:` line, bolded section headers (`**TEHNIČKE KARAKTERISTIKE:**`, `**OBIM ISPORUKE:**`), bold feature-name bullets (`* **NAZIV** – opis`), spec tables only for real label:value pairs; URL — NEVER inside description text: shop page goes into `products.website_url`, manufacturer page into `products.manufacturer_url` (both columns already exist); O PROIZVOĐAČU — never in description (existing rule confirmed); OBIM ISPORUKE — included as a section whenever the source has it. Writing style: kratko, koncizno, informativno — short sentences, feature name bold then one-line explanation, no marketing fluff, no invented specs, everything from the source.
## Alternatives considered

**Keeping `URL:` as the last description line (old rule §3)** — overruled by Lazar: URLs belong in structured fields (`website_url` / `manufacturer_url`), not inside description text; the old convention came from a period when those columns were unused (only 2 of 256 products had them set before today). **1000-char hard max (old rule)** — raised to 2000 by Lazar: the 600-target proposal was rejected as too aggressive for machines; the real fix for offer bloat is picking which features to include, not a tighter cap. **Table as the default spec format (Format A)** — kept as optional; Lazar's confirmed preference from the V4400/678 work is bold-lead bullet lists (`* **NAZIV** – opis`), tables only when the source has clean label:value pairs. **Migrating all 150 legacy descriptions (strip URL lines, reformat) now** — deferred: this note defines the standard going forward; a one-off cleanup batch over existing rows is separate work Lazar can request.
## Consequences

Existing data does NOT yet match this standard: ~103 descriptions still carry a `URL:` line inside the text (they predate the rule), 19 SMARTSAFE rows still carry "O PROIZVOĐAČU", and only 4 products have URL fields populated. The standard binds when I write or rewrite descriptions (new imports, cleanup batches, offer prep); legacy rows get conformed only when Lazar asks for a batch or when a product is touched individually. `website_url` semantics shift slightly: it holds the shop-page URL when known, else manufacturer URL; `manufacturer_url` holds the OEM page only when it differs. Offers keep rendering description markdown as before — no code change involved in this note.

