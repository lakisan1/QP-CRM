# Agent Note: no-price-in-device-description

Status: implemented

## Problem

The user corrected a convention: a device's price must never be part of its catalog description (`products.description`, which flows into offer lines via snapshot). I had included "Cena: **27.300,00 €** bez PDV-a" in the V4400 COMMANDER description earlier today following the older description style that mentioned values (e.g. an insurance spec letter in rent templates quoted machine values). The user says they will remove it themselves this time and wants the rule remembered.

## Decision

Convention (user instruction, applies to all future catalog work): `products.description` NEVER contains the device's price — no "Cena:", "27.300,00 €", "bez PDV-a", "VREDNOST MAŠINE" lines, in bold or otherwise. Price is owned exclusively by the `prices` table (per-product price documents with margin/import/discount calculations); offer lines display the quoted unit price themselves, so any price text inside the description would also risk contradicting the actual offer price. The `URL:` source-link suffix stays. When adding devices for the user (e.g. earlier today's V4400 COMMANDER, id 279), the description is written price-free by default. Existing product 279 still carries the price line in both `products.description` and the offer_items 477 snapshot (P-1251) — the user explicitly takes that removal on themselves this time, so no write was made.
## Alternatives considered

**Leaving the price line in product 279 since the user said they'd remove it themselves** — actually done: no DB write this turn; the user edits via the pricing UI so the description is exactly what they type. **Auto-stripping price lines from all descriptions going forward (script)** — rejected: this is a one-line policy, not a code change; `products.description` is free markdown text edited by the user, and no other row currently contains price text (verified). **Changing the app to reject price-like patterns on save** — rejected: overkill validation for a habit-rule, false positives likely (e.g. "bez PDV-a" inside a legitimate feature note).
## Consequences

The rule lives in this note (and the user's own practice), not in code — nothing enforces it mechanically. The pending edit is the user's own (they said "ja ću ovog puta da je izbacim"); if they don't get to it, product 279's description still shows "Cena: 27.300,00 € bez PDV-a" and the P-1251 offer snapshot mirrors it. Future catalog additions done by the agent must default to price-free descriptions: the price belongs to `prices` rows, and the offer line shows the unit price anyway, so a price inside the description also risks contradicting the actual quoted price in the same offer.

