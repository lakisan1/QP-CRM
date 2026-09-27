# Agent Note: pricing-tracking-regime-ui

Status: implemented

## Problem

P5-T1 (cff7aed) added products.tracking_regime / min_stock / unit_base / pack_size and the warehouse module gates all stock math on tracking_regime != 'untracked', but no pricing surface read or wrote the columns: tracking could only be enabled by SQL, so the entire P5 stock feature was unreachable from the UI and the 254-row catalog had no way to opt products in.

## Decision

The pricing product form (add + edit) now carries `<select name="tracking_regime">` with the closed set from `qp_crm.shared.schema.TRACKING_REGIMES` ("untracked"/"qty"/"serialized", Serbian option labels Ne prati / Količinski / Serijski) plus `min_stock`, `unit_base`, `pack_size` inputs. The three qty-only fields live in `<div id="tracking-qty-fields">` and an inline DOMContentLoaded handler toggles `style.display` on the select's change event; the inputs are NOT `disabled`, so hidden values still submit and a regime flip back to `qty` keeps what the user typed. `add_product` / `edit_product` whitelist and persist all four columns in the same block as `item_type`/`website_url`, via module-level helpers `_tracking_regime` (unknown/empty/garbage -> "untracked", never an error or 500), `_optional_float` (empty -> NULL, decimal comma accepted, unparsable -> NULL), `_optional_text` (empty -> NULL). Missing regime on edit behaves like add: it lands on 'untracked'; no partial-update semantics exist for the HTML form (the form always posts the field). The products list shows a badge per tracked row (Količinski teal #16a085, Serijski blue #2980b9) and a `tracking_regime` filter in `.filter-row` mirroring the existing `item_type` filter, including its session persistence under `products_filter_tracking` and the `clear=1` reset. Tracking values are never nulled when the regime is not `qty` — the warehouse coverage view already ignores them outside qty, and keeping them avoids silent data loss on an accidental flip. `qp_crm/shared/schema.py` and `qp_crm/warehouse/**` were not touched.
## Alternatives considered

**Reuse `warehouse_service.set_tracking_regime()` instead of raw UPDATE in the route:** rejected because it takes product_id and does its own connection + get_product round-trip inside the already-open route transaction, and the task called for the existing item_type/website_url whitelist style; the route also persists name/category/etc. in one statement, so a second writer would split the update across connections.

**Null out min_stock/unit_base/pack_size whenever regime != 'qty':** rejected as silent data loss on an accidental regime change, and the warehouse service explicitly stores whatever it is given rather than clearing.

**`disabled` on the hidden qty inputs:** rejected because a disabled input is not submitted, so every save with the regime not on `qty` would clear stored values.

**Reject a garbage regime with the form error path (item_type style) or 400:** rejected per explicit task requirement — bad input must fall back to 'untracked' and never 500, because 'untracked' is the safe catalog default.

**Reuse the `item_type` filter variable name / a generic `tracking` query param:** rejected for a `tracking_regime` param that names the column, so the filter and the form field stay one vocabulary.
## Consequences

The default untracked path is unchanged: a POST without any tracking field lands on the column default and a NULL min_stock/unit_base/pack_size, preserving the 254-row behaviour and keeping every existing pricing/offer test green. Cost: the route now owns a small parsing layer duplicated nowhere else (helpers are private to `qp_crm/pricing/routes/products.py`; the warehouse service keeps its own validation), so the two entry points can drift — the shared gate remains `TRACKING_REGIMES` in `qp_crm/shared/schema.py`. `api_v1` product create/update still does NOT accept or expose the tracking fields (out of P5-T5 scope), so API-created products can only ever be 'untracked'; that is the named coverage gap. The aliases/merge work (P5-T6) repoints `products` references and must not assume the tracking columns are absent. New tests: `tests/smoke/test_product_tracking_regime.py` (15) covering add/edit round-trips, garbage-regime fallback, empty-vs-zero, comma decimals, form preselection, and the list filter/badges.

