# Agent Note: directory-fuzzy-search

Status: implemented

## Problem

User request: the directory search must find contacts by PIB, MB, phone number, email and every other field; must ignore trailing junk like extra spaces or dots at the end of the query; and should be fuzzy — 'Carka' style exactness not required (diacritics, punctuation in phone numbers).

## Decision

qp_crm/shared/db.py registers a SQLite scalar function norm(1) on EVERY connection from get_db(): casefold + NFD-diacritic-strip + punctuation-drop (@/+ kept for emails/phones) + whitespace squeeze. contact_service.list_contacts builds its search haystack over norm(c.display_name), norm(c.first_name), norm(c.last_name), norm(c.pib), norm(c.mb), norm(c.jmbg), norm(c.email), c.account via norm(), c.notes via norm() — each whitespace-separated query term (normalized by the Python twin _search_norm in contact_service) must hit at least one field (AND across terms, OR across fields); all values ride ? parameters. Trailing junk ('Beograd...', extra spaces) disappears in normalization on both sides. The directory list route passes ?search= through unchanged — pagination and filters compose as before.
## Alternatives considered

["**FTS5 virtual table (SQLite full-text)**: rejected — a second index structure to keep in sync on every contact write (triggers or dual-write), for a corpus of thousands of rows where LIKE-over-norm() is already sub-millisecond; FTS also does not fold diacritics the way norm() does without custom tokenizers.", "**LIKE with LOWER() only (no diacritic fold)**: rejected — Serbian names are full of č/ć/š/ž/đ; 'Cacak' would still miss 'Čačak', which was the user's core complaint.", "**Python-side filtering (fetch all, filter in list_contacts)**: rejected — breaks the SQL LIMIT/OFFSET pagination contract and would ship 2156 rows per search; the norm() UDF keeps filtering inside SQLite.", "**Trigram similarity (LIKE3 / sqlite trigram tokenizer)**: rejected — needs SQLite >= 3.34 with the trigram extension compiled in; the deployed python:3.12-slim sqlite build cannot be assumed to have it, and character-level trigrams are overkill for typo tolerance here."]
## Consequences

Bought: one search box now finds a party by PIB, MB, JMBG, phone (any punctuation), email, city, account number, or a note fragment — with diacritic-insensitive and punctuation-insensitive matching and trailing-junk tolerance; multi-word queries AND across fields so 'toyota zrenjanin' narrows. Cost: norm() is a Python UDF called per-row-per-field on every search — at 2156 rows x 11 fields it is still ~tens of milliseconds, but it does NOT scale like an index; if a future corpus grows 10x+, revisit FTS5. The UDF is registered in get_db(), so EVERY connection has it — but raw sqlite3.connect() callers (scripts, tests opening their own connections) do NOT have norm() and will error if they run norm()-using SQL. Negative guarantees: no user text is interpolated into SQL (terms ride ? params; only fixed norm(column) expressions are string-built); junk-only queries ('....') normalize to zero terms and return the unfiltered page rather than erroring; the search does NOT do typo-tolerant edit-distance matching ('Cacck' will not hit 'Cacak') — fuzziness here means case/diacritics/punctuation/whitespace insensitivity plus substring hits, which is what was asked.

