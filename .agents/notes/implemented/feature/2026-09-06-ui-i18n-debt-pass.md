# UI/i18n debt pass — shared banner include, hardcoded-string i18n, a11y basics

## Problem

The Phase-2/3 UI work had already extracted shared nav includes (templates/nav_home.html,
admin/_nav.html), but the four module base templates (pricing/offer/rent/sale) still
copy-pasted the same <nav> shell (nav-right + Home pill + logo), the settings page and
admin/_nav.html carried their own private copies of that shell, and hundreds of
user-facing Serbian literals sat in templates and route messages next to the
TRANSLATIONS dictionary (sr UI was Serbian because strings bypassed i18n, so en-mode
rendered Serbian too). No accessibility pass existed (login inputs unlabeled, search
inputs placeholder-only, table headers without scope).

## Decision

Shipped reality on branch wave1-ui-i18n (4 commits, 255 passed / 3 skipped):

1. templates/_banner.html is now the ONE nav shell for every app header. It is a Jinja
   macro (`banner(nav_extra=None, hr=true)`) whose caller supplies the per-module
   .nav-links; it renders nav-right (include of templates/nav_home.html + logo) and the
   <hr> divider. All callers import it `with context` (macros do NOT see the template
   context otherwise — `_`, `request`, `url_for` inside the macro would be Undefined).
   Admin pages pass hr=false (they never drew the divider). nav_home.html now has exactly
   one consumer. Tom Select init scripts stayed per-base (not byte-identical — do-not-churn
   rule). PDF templates and their inner includes are untouched.

2. Screen-only Serbian UI strings now render through `_('English source')` with 123 new
   TRANSLATIONS['sr'] entries whose values keep the sr wording the app showed (obvious
   typos normalized in the dictionary: Konacna→Konačna, troskovi→troškovi,
   kostanje→koštanje, Sacuvaj→Sačuvaj, Briši→Obriši). Converted: unified login (template +
   auth/app.py wrong-password + lockout messages, lockout test assertion updated to the EN
   source that the no-language test DB renders), settings page, pricing products/product
   form/price form/quick update/category defaults/brands/price history + pricing nav
   'Sync Sajt', pricing/routes/products.py duplicate-name + image error messages (translated
   at request time via get_current_language()), offer compare tool, rent base nav + title +
   rent contracts list chrome, admin _nav label + dashboard rent-defaults block.

3. A11y basics (no redesign): login form got explicit <label for> + ids + role="alert" on
   the error box; placeholder-only search inputs got aria-labels; <th> cells on the main
   data tables got scope="col"; <html lang> on bases/settings/login follows current_lang.

4. Four smoke pins in tests/smoke/test_smoke_modules.py assert the label/for pairs on
   /login, the products search aria-label + th scope, the absence of known Serbian literals
   on rendered EN pages ('Sync Sajt', 'Brzo Ažuriranje Cena'), and sr-mode rendering
   (global_settings.language='sr' → 'Korisničko ime', 'Format datuma', ...; the DB row is
   removed afterwards).

Negative guarantees / boundaries: NOT translated (deliberately): inline JS prompt/confirm
bodies on the products/offers delete flows, JS status/alert strings on the contracts list
and price form, the big product_sync and offer_form pages, rent client/equipment/contract-form
pages, offers list page, PDF-shared templates (offer *_inner, rent *_pdf_*), bilingual admin
labels like 'Delivery Terms (Uslovi isporuke)', and image-error prefixes that concatenate
exception text (reported in the branch commit). shared/web.py date-format logic and
templates/landing.html untouched. Interactive <span> status toggles on the rent contracts
list still lack role/tabindex on purpose (adding them without a keydown handler would be a
focus trap).

## Alternatives

- Extracting a full Jinja base-skeleton (`{% extends %}`) shared by every module:
  rejected — blocks do not override across include boundaries and converting every page
  to a new inheritance tree is exactly the churn the card forbids.
- Moving the Tom Select init <script> into static/js: rejected — the four copies differ
  (instance storage, formatting); do-not-churn rule says leave non-byte-identical copies.
- Keeping the lockout message Serbian in en-mode and only adding an sr entry:
  rejected — that would leave en-mode untranslated; the test assertion was updated to the
  EN source instead (sr phrase is now pinned by the new sr-mode smoke test).

## Consequences

Cost: ~120 precise string replacements across 18 template/route files + 123 dictionary
rows (big diff, needs the smoke pins to guard); a handful of visible sr-mode words were
normalized to canonical spelling (typos fixed); one existing test assertion changed.
Bought: every header banner renders through ONE macro; nav_home cannot drift; the moved
strings are bilingual (en finally renders English under the default en language row);
main-flow controls are label/aria/tablescope clean; the residual hardcoded-string surface
is now explicit (see commit message) instead of implicit.
