# Agent Note: directory-typo-fallback

Status: implemented

## Problem

User asked how complex typo tolerance would be ('Cacck' should find 'Čačak'); after measuring (~120 ms full scan on 2156 contacts) they approved adding it as a fallback layer behind the existing diacritics/punctuation fuzzy search.

## Decision

contact_service.list_contacts gained a second layer: when the LIKE/norm() layer returns zero rows for a non-empty search, _typo_fallback scans active contacts and matches each query word by Damerau-Levenshtein distance <= 2 (_damerau_levenshtein_within with early exit) against words of display_name, first/last name, pib, mb, jmbg, email, phone, city, billing_address, postal_code and account — same field set as the LIKE haystack minus notes. Words shorter than 4 characters are skipped entirely. All structural filters (archived/kind/country/roles) apply to fallback candidates; pagination contract holds ((rows, total) with total = fallback hit count).
## Alternatives considered

["**Trigram similarity (Jaccard over character trigrams)**: rejected after prototyping on the real directory — 'cacck' vs 'cacak' scores only 0.333 (short words make trigram sets tiny and the metric too sharp); it missed the very typo class the user asked for.", "**Levenshtein without transpositions**: rejected — Damerau extension costs one extra min() branch and catches the common 'teh'/'the' swap; plain Levenshtein would miss transposition typos for free code.", "**Always-on fuzzy (merge into the LIKE layer)**: rejected — every search would pay the full-table DL scan (~120 ms at 2156 rows) even when exact matching already has hits; fallback-only keeps normal searches at ~85 ms.", "**FTS5 spellfix auxiliary table**: rejected — needs SQLite compiled with FTS5 + spellfix1 (not guaranteed in the python:3.12-slim build), a shadow vocabulary table to maintain, and is tuned for large corpora; overkill for a 2k-row directory."]
## Consequences

Bought: 'Cacck', 'Toyta', 'Zrenjaniniski' style queries now return results — distance ≤2 per word covers single-char insert/delete/substitute and adjacent transpositions, which are virtually all human typos; normal searches pay zero overhead (fallback fires only on an empty LIKE result). Cost: an empty-result search now takes ~100-200 ms extra (full scan x 12 fields x DL with early exit) — acceptable at thousands of rows, would need an index strategy (e.g. precomputed word table) if the directory grows 10x+. Negative guarantees: words shorter than 4 characters are NEVER fuzzy-matched (a 1-char change in a 3-letter word is noise, not a typo) — short queries fall back to nothing rather than to garbage; notes are NOT typo-matched (free text too noisy); typo fallback returns matches ranked alphabetically not by distance score, so ordering within hits is not relevance-ranked; pickers (no per_page) get fallback results as a plain list — fine, they never paginate. The route passes ?search= through unchanged; no UI changes were needed.

