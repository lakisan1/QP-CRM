# QP-CRM test suite (Phase 1)

The suite runs **inside the Docker image** with one command — the host venv
has no pytest and the host cannot import WeasyPrint (no libpango), so Docker
is the supported runner.

## Running

    docker compose build app           # only when code/tests/deps changed
    docker compose run --rm app pytest

Run one file / one test:

    docker compose run --rm app pytest tests/characterization/test_pricing_rounding.py
    docker compose run --rm app pytest -k recalc_totals

## Coverage gate (money-path services)

CI runs the suite a second time with pytest-cov
(`pytest-cov==7.1.0` in dev-requirements.txt) scoped to ONLY the three service
modules that own the money math — deliberately NOT a full-suite gate. The
module list lives in one place, the repo-root .coveragerc (`[run] source`), so
the invocation is the bare `--cov`:

    docker compose run --rm app pytest --cov --cov-fail-under=95 --cov-report=term-missing

Measured against the full suite these modules sit at 100% / 96% / 100%
(99% total — pricing_service's single missed line is an *unreachable* legacy
`val <= 0` clamp, so 100% needs a production edit, not a test). The
`--cov-fail-under=95` threshold was rounded down to the nearest 5 from that
measurement so the gate trips on real regression only. Adding a new
money-math module → add it to .coveragerc `[run] source` (nothing else). The
.coveragerc also keeps coverage data in `/tmp/.coverage` because /app is
root-owned read-only for the image's appuser (same reason pytest.ini puts the
pytest cache in /tmp).

## What is covered

| Area | File | Pins |
|---|---|---|
| Pricing rounding | `tests/characterization/test_pricing_rounding.py` | `apply_rounding` UP/DOWN/NEAREST against the seeded `price_rounding_rules`, bracket selection, 0-clamp, fallback, banker's-rounding quirk |
| Offer totals | `tests/characterization/test_offer_recalc.py` | `recalc_totals` 3-level discount cascade → VAT → gross, exact float readbacks, NULL/0 coercion + write-back |
| Rent math | `tests/characterization/test_rent_calc.py` | `pmt`, `calculate_rent`, `_add_months`, `generate_schedule` (incl. end-of-month rule and bad-date fallback) |
| Formatting | `tests/characterization/test_formatting.py` | `qp_crm.shared.utils.format_amount` / `format_date` |
| Rent placeholders | `tests/characterization/test_rent_placeholders.py` | `_build_doc_context`, `format_document_html` |
| Golden PDFs | `tests/golden/test_golden_pdf.py` | byte comparison (after timestamp/ID normalization) of one fixed offer + one fixed rent document against `tests/golden/baselines/*.pdf` |
| Smoke | `tests/smoke/test_smoke_modules.py` | login → main page → 200 for pricing/offer/rent/admin, open access for sale/settings, landing page, unauthenticated redirects |

## Isolation (read this before adding tests)

`tests/conftest.py` patches `qp_crm.shared.config` (`APP_DATA_DIR`, `DATABASE`,
`IMAGE_DIR`, `APP_ASSETS_DIR`) into the fixed throwaway tree
`/tmp/qp-crm-tests` **before any app module is imported** — every sub-app
binds those names at import time, so this is the only safe moment. The suite
therefore never touches the bind-mounted `app_data/pricing.db`.
`tests/test_infra_isolation.py` guards this contract; if it fails, stop and
fix the isolation, do not run the suite.

The path is FIXED (not `tempfile.mkdtemp`) on purpose: WeasyPrint names image
XObjects `i + md5(image URL)`, so a random path would change golden PDF bytes
on every run. `/tmp` dies with the container, so each `docker compose run`
still starts from a clean tree — but **do not run two suites against the same
image in parallel** (they would share `/tmp/qp-crm-tests`).

The session fixture replays the production init sequence
(pricing init + migrate → offer → admin → rent) into the temp DB — seeded
defaults (rounding rules, PDF templates, rent document templates) are part of
the pinned behavior.

## Golden PDFs

Baselines live in `tests/golden/baselines/`. PDF bytes contain volatile
metadata (creation/modification timestamps, trailer `/ID`); the test
normalizes exactly those regions and requires **everything else** to be
byte-identical. Fonts are pinned in the image (`fonts-dejavu-core`).
Because of that pinning, the golden tests SKIP on a host run (no
`/.dockerenv`, cwd != `/app`) — they are only meaningful inside the image,
and `QP_UPDATE_GOLDEN=1` is inert outside it. Never re-baseline on the
host.

Re-baselining is a deliberate act — run

    docker compose run -v "$PWD/tests:/app/tests" --rm -e QP_UPDATE_GOLDEN=1 app         pytest tests/golden

then `git diff tests/golden/baselines/` and explain the intended change in
the commit message. Fixture inputs (offer/contract rows, template state,
logo/footer images in `tests/golden/assets/`) are fixed; if you change them,
the baseline changes with them and must say so in the commit.

## Discipline (Phase 1)

These are **characterization tests**: they pin current behavior of the
unmodified app, quirks included. A failure means "behavior changed" — never
fix production code in this phase. Log every discovered quirk as a kanban
bug card (referencing `AUDIT_FINDINGS.md` codes where they match); fixes
belong to Phase 2+.
