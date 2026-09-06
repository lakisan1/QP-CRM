# pytest cache_dir warning root cause + money-path coverage gate

## Problem
Two pytest hygiene gaps: (a) the suite historically reported
"PytestConfigWarning: Unknown config option: cache_dir" from pytest.ini and
the root cause was undocumented, risking a future "fix" that deletes the
option and breaks container runs; (b) there was no CI gate on the modules
that own the money math, so a regression in recalc_totals / apply_rounding /
pmt / generate_schedule could ship unnoticed.

## Decision
(a) pytest.ini keeps `cache_dir = /tmp/.pytest_cache` (real isolation: the
image runs the suite as the non-root appuser with /app root-owned and
read-only, so the default .pytest_cache under the rootdir would be
unwritable) and now documents the mechanism: the key is REGISTERED by
pytest's built-in cacheprovider plugin (parser.addini in
_pytest/cacheprovider.py), and pytest validates ini keys post-collection
against loaded plugins — so the key is only "unknown" when the cacheprovider
plugin is not active in the process, which happens solely when an invocation
disables it (`-p no:cacheprovider` in addopts / PYTEST_ADDOPTS / CLI;
--strict-config would then turn the warning into an error). Canonical host
runs and the CI step (`docker compose run --rm app pytest`, pytest 8.4.2)
never disable the plugin: verified warning-free (251 passed, 3 skipped, no
warnings summary). The comment forbids both `-p no:cacheprovider` (drops
--lf/--ff/stepwise too) and deleting cache_dir. NOT changed: production code,
golden baselines, shared/utils.py.

(b) Coverage gate on the three money-path service modules only —
qp_crm.services.offer_service (recalc_totals), pricing_service
(apply_rounding), rent_service (pmt/_add_months/calculate_rent/
generate_schedule). Added pytest-cov==7.1.0 to dev-requirements.txt and a
repo-root .coveragerc whose `[run] source` lists exactly those three modules
(single source of truth; CI and docs run bare `pytest --cov`).
`[run] data_file = /tmp/.coverage` mirrors the cache_dir constraint: the
default .coverage in cwd is unwritable for appuser in the image. CI keeps the
plain full-suite step and adds a second step
`pytest --cov --cov-fail-under=95 --cov-report=term-missing`. Measured
full-suite coverage: 100% / 96% / 100% (125 stmts, 99.20% total); the one
missed statement (pricing_service.py line 34-35) is an UNREACHABLE legacy
`val <= 0: return 0` clamp left over from the removed clamp-to-0 bug fix, so
100% is impossible without a production edit. Threshold 95 = current rounded
down to the nearest 5, so the gate trips on real regression only. Negative
guarantees: this is NOT a full-suite gate; a new money-math module must be
added to .coveragerc [run] source or it is unmeasured; format_amount lives in
qp_crm/shared/utils.py (not in the gate — owned by another workstream).

## Alternatives
- Remove cache_dir from pytest.ini and rely on the default cache location —
  rejected: appuser cannot create .pytest_cache under root-owned /app in the
  image, every cache write would fail (PytestCacheWarning noise at best).
- Register cache_dir unconditionally from a conftest pytest_addoption —
  rejected: fights the plugin architecture and duplicates an ini key that the
  builtin cacheprovider already owns whenever it is loaded.
- Add --strict-config to addopts to hard-error on unknown options — rejected:
  the warning cannot occur under supported invocations (verified), and
  strict-config turns any future third-party ini key into a hard failure for
  marginal benefit.
- Gate on the whole suite (full-suite coverage %) — rejected by the task:
  vanity metric, would not specifically protect the money math.
- Per-run unique coverage data files (e.g. COVERAGE_FILE per QP_TEST_ROOT) —
  rejected: the gate is computed in-process at session end from collected
  data; the shared /tmp/.coverage artifact is last-writer-wins and harmless
  for gating (same shared-/tmp posture as cache_dir and QP_TEST_ROOT notes).

## Consequences
Bought: CI now fails when combined statement coverage of the three money
modules drops below 95%; every supported pytest invocation is documented
warning-free; the .coveragerc + .coveragerc data_file keeps coverage I/O in
/tmp so the gated step works unmodified in the read-only-/app image. Cost:
CI runs the ~30s suite twice (plain + gated) per push; pytest-cov and
coverage now ship in the image layer. Follow-up: parallel host runs of the
gated command share /tmp/.coverage (last writer wins — fine for per-process
fail-under, documented in .coveragerc); if the dead pricing_service clamp is
ever removed (production edit, other workstream), re-measure and raise the
threshold.
