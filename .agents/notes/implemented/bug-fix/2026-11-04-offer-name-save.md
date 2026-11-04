# Agent Note: offer-name-save

Status: implemented

## Problem

User report 2026-11-04: "bug koji sprečava čuvanje imena kako treba u ponudama — ime same ponude". The offer name is `offers.offer_number`. The save path was broken in three independent ways: (1) POST /offer/offers/new with an already-used name raised UnboundLocalError (`current_language` is bound only in the mandatory-field branch and the GET path) → HTTP 500, no offer created; (2) both failed-save re-renders pass `offer=preserved_offer`, a dict without `id`, while the template's edit-only blocks build `url_for('offer.offer_pdf', offer_id=offer.id)` → UndefinedError → 500 even after (1) — proven on the mandatory-field branch; the duplicate branch also omitted presets_by_cat/mandatory_fields entirely, so it could not render at all; (3) the form's background header save (fetch before "Dodaj u ponudu" / filter change) treated the 302+re-render rejection as success (fetch follows redirects → 200), so a rejected or blank name was silently dropped while the item was still added; `offers.offer_number` is nullable and had no server-side check, and the programmatic `form.submit()` bypasses HTML `required`. Separately, the musterija gate set pointer-events:none on the whole #offer-main-card whenever contact_id was empty, locking the offer name AND the Save button on legacy free-typed offers (contact_id NULL) and on a fresh /offers/new.

## Decision

Shipped (qp_crm/offer/routes/offers.py, offer_form.html, app.py):

1. `_offer_form_settings(cur)` is the ONE context builder for the offer form: presets_by_cat + defaults, email templates, current_language, default vat/validity/country, mandatory_fields, countries, party_choices. GET, mandatory-error re-render and duplicate-name re-render all use it, so `current_language` can never be unbound again and no branch renders with a partial context.

2. The value dict for a failed new-offer save is built ONCE (`preserved_offer`) and deliberately carries NO `id`; it now also carries is_template. The template's edit-only blocks are guarded with `{% if offer and offer.id %}` (h1, Print PDF/Send, items section, scroll key, reorder URL). A failed new save therefore renders as "New offer" with the typed values and the error, and never builds a URL from an unsaved row. `selected_contact_id=contact_id` keeps the picked party so the gate reopens.

3. `_is_ajax_header_save()` (header `X-Requested-With: XMLHttpRequest`) splits the update_header write path: normal browser submit keeps the 302 + `session["error_message"]` flow; the background save gets `200 {"ok": true}` after commit + recalc + contact link, or `409 {"ok": false, "error": <message>}` for validation/duplicate rejection with NO DB write. offer_form.html's `saveHeaderQuietly()` sends that header, parses the JSON and shows the server message, and only submits the clicked form (add/delete item, filter) when the header save was accepted.

4. The offer name is required server-side on BOTH paths ("Offer name is required."); a blank name is never written. Duplicate rejection uses one message on both paths ("Offer name already exists. Duplicate offer names are disabled in Admin -> Settings.") — new_offer renders it inline, edit sets it in the session.

5. Gating is a NEW-offer wizard step only: `#offer-main-card` carries `data-existing-offer`, and `applyGate()` treats `existingOffer` as picked. An existing offer is never dimmed/pointer-events:none and `musterija-rest` is never hidden, so a contact_id-NULL legacy offer's header (name included) stays editable; the hint explains the free-typed-customer state.

6. qp_crm/offer/app.py: the module carried TWO functions named inject_helpers — the older (theme + enable_product_discount) had lost its @bp.context_processor during the package split. One registered processor now injects format_amount, format_date, theme, enable_product_discount (the per-item discount column honours Admin -> Settings again; live DB has enable_product_discount=false, so no visible change today).

Negative guarantees: no schema change and no UNIQUE constraint (offers.offer_number still legally duplicates when Admin -> Settings allows it); no auto-repair of already-saved rows; duplicate detection stays exact-match (case-sensitive), unchanged; the new-offer POST is not AJAX-aware (no other form exists there); the non-AJAX edit flow still communicates via the session redirect; golden PDF/test baseline untouched.

Tests: tests/characterization/test_offer_name_save.py (11 tests) pins the 500→200 duplicate re-render with preserved name/party, the mandatory-field re-render, empty-name rejection on both paths, JSON 200/409 contract, and the header-save-then-add-item sequence. Full suite 548 passed, 3 golden skipped on host (CI runs them in the image). APP_VERSION bumped to 1.1.2.
## Alternatives considered

**Separate JSON endpoint for the background save** (e.g. POST /offer/offers/<id>/header.json) — rejected: it would duplicate the entire update_header field parsing/validation/write logic or force a shared helper with its own request-shape contract; the X-Requested-With branch keeps one write path and one validation source.

**Keep the 302 and detect the error client-side** (scan response.url for `?error=` or parse the rendered HTML for the alert div) — rejected: fragile string matching against a full page render, and the session error message is popped by the re-render (so the user would still see nothing on the next load).

**Block blank names only with HTML `required`** — rejected: the background save uses fetch (no browser validation) and `this.submit()` bypasses it; a blank name could still be persisted and the list would fall back to the numeric id.

**Unlock just the name field inside the gated card** (CSS pointer-events exception) — rejected: on a legacy offer the date/notes/save button are equally unusable, and the same offer would keep its customer fields hidden behind `musterija-rest`; gating existing documents contradicts the "issuance-time snapshot, always editable" rule the directory unification set.

**Case-insensitive duplicate detection** — rejected: changes which names are legal, and no user request pins it; exact match keeps today's semantics.
## Consequences

Bought: the offer name can be saved on every path (create, edit, background save) and every rejection is visible instead of a 500 or a silent drop; legacy contact_id-NULL offers are editable again; the enabled/disabled per-item discount column actually follows the admin setting. Cost: the header save now has two response contracts (302+session for browser submits, JSON+409 for the background save) — any future caller of update_header must pick one and send/omit X-Requested-With deliberately; the template re-render for a failed NEW save is a value dict without id, so every new edit-only block in offer_form.html must keep the `offer and offer.id` guard (the failure mode is a 500); the duplicate/validation messages are English inside a Serbian UI, matching the pre-existing message style (i18n debt, not made worse). Deploy: templates and routes are baked into the GHCR image, so the live instance only changes after a main push → CI image build → `./deploy.sh` (git pull + docker compose pull + pre-deploy backup). No data migration and no rollback hazard: the DB schema is untouched.

