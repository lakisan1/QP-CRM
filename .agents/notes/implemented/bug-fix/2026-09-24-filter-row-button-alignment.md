# Agent Note: filter-row-button-alignment

Status: implemented

## Problem

On list pages (/rent/contracts, /sale/pricelist, /offer/offers, /contacts/contacts, /pricing/products) the action buttons after the search bar rendered a few to sixteen pixels below the input line instead of level with it. The user flagged it in four screenshots and allowed dropping the fix if it proved complicated.

## Decision

main.css now defines a `.filter-row` convention: display:flex, wrap, 15px gap, align-items:flex-end, with `label`, `label>span`, `input`, `select`, `.btn`, `button` inside the row getting margin-bottom:0, and `.filter-row .btn/button` getting 13px vertical padding so button height (45.6px) matches the 46px native input. It also normalizes `.ts-wrapper .ts-control` to padding:10px 14px and font-size:15px (and the control's inner input to 15px), matching the app's native input metrics, so TomSelect wrappers are the same height as plain inputs. Five templates now carry the class: qp_crm/rent/templates/rent/rent_contracts.html (form), qp_crm/contacts/templates/contacts/list.html (form, gap:8px preserved), qp_crm/offer/templates/offer/offers.html (row div; margin-bottom:4px hack removed), qp_crm/sale/templates/sale/sale.html and qp_crm/pricing/templates/pricing/products.html (row div; hidden-span spacer divs removed, inline button paddings removed so CSS governs). Negative guarantees: pages WITHOUT the .filter-row class keep the old global behavior (inputs still get margin-bottom:16px in plain stacked forms — untouched); admin forms using flex-end with block labels keep their existing look; the TS padding rule applies app-wide, including offer_form pickers, which is intended for consistency but is a global visual change to TS controls. Deployed to the qp-crm container (commit 7d25b55), full test suite green (356 passed, 3 skipped).
## Alternatives considered

**Per-template inline patches (tweak margins on each page).** Lost: the four pages had three different failure mechanisms (16px margin, hidden-span spacers, TS wrapper height); patching each would leave the fourth cause and invite regressions on the next list page. **A shared Jinja macro for filter bars.** Lost: over-engineering a cosmetic fix; it would require rewriting every template's field markup (conditional fields, widths, onchange submits) with high regression risk for zero functional gain. **Heightening all .btn globally to match inputs.** Lost: .btn is used in banners, modals, table rows, PDF pages; a global height change would ripple everywhere for one row type. **Dropping the fix as "too complicated" (user allowed it).** Lost: once the margin-box mechanics were clear the fix was small and mechanical, so abandoning it wasn't warranted.
## Consequences

Bought: one convention for all current and future filter rows; TomSelect selects now visually match native inputs app-wide (they previously rendered ~4px shorter with different padding). Cost: .filter-row must be added to new list pages manually (inline flex styles won't pick it up); TS control padding change is global to every TomSelect on every page, so any page relying on the old 8px TS padding must be re-checked visually; buttons in filter rows are 45.6px vs input 46px — a sub-pixel difference accepted. Verification was static (rendered HTML + CSS math + container greps) because no headless browser is installed and login credentials are unknown; visual confirmation is still pending from the user.

