"""P1-T2 characterization: pricing.app.apply_rounding -- behavior AS IS.

All expected values below were captured from the unmodified app in the
pinned Docker image (tests/_capture.py) and hand-checked against
pricing/app.py:357-400. They pin quirks, they do not judge them:

* val <= 0 is clamped to 0 (never rounded, sign lost for negatives).
* Rule selection takes the rule with the SMALLEST limit_val >= val -- a
  value a hair above a bracket limit jumps to the next bracket's step
  (1000.01 rounds by step 100, not 50).
* No limit >= val -> falls back to the LARGEST-limit rule of that target.
* Target with no rules at all -> value returned unchanged.
* NEAREST uses Python round() = banker's rounding (half to EVEN:
  0.5 -> 0, 2.5 -> 2, 3.5 -> 4).
* Unknown method string is treated as UP (ceil).
* Seeded defaults (admin/app.py:101-132) use method UP for both targets
  with limits 1000/10000/30000/999999999 and steps 50/100/500/1000, so
  "rounding UP" is the production behavior for every price/discount.
"""

import pytest

from qp_crm.pricing.app import apply_rounding


@pytest.fixture(scope="module", autouse=True)
def _custom_rule_targets(temp_db):
    """Insert dedicated targets for method-specific pins (run once)."""
    from qp_crm.shared.db import get_db

    conn = get_db()
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR IGNORE INTO price_rounding_rules (target, limit_val, step_val, method)"
        " VALUES (?, ?, ?, ?);",
        [
            ("p1t2_up", 999999999, 7, "UP"),
            ("p1t2_down", 999999999, 7, "DOWN"),
            ("p1t2_nearest", 999999999, 1, "NEAREST"),
            ("p1t2_weird", 999999999, 7, "WEIRD"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.mark.parametrize(
    "val, expected",
    [
        # seeded brackets for target 'price': captured exactly
        (0, 0),                    # zero returned as int 0 (sign-preserving path)
        (-5, -5),                  # re-baselined (BUG card): sign preserved, no clamp to 0
        (0.01, 50.0),              # tiny value still rounds UP a full first step
        (12.5, 50.0),
        (499.99, 500.0),
        (500, 500.0),
        (999.99, 1000.0),
        (1000, 1000.0),            # exactly at the limit -> still the 50-step bracket
        (1000.01, 1100.0),         # one cent above -> jumps to the 100-step bracket
        (9999.99, 10000.0),
        (10000, 10000.0),
        (10000.01, 10500.0),       # jumps to the 500-step bracket
        (29999.99, 30000.0),
        (30000, 30000.0),
        (30000.01, 31000.0),       # jumps to the 1000-step bracket
        (12345.67, 12500.0),
        (999999999, 1000000000.0),
        (1000000000.0, 1000000000.0),  # above the largest limit -> largest-rule fallback
    ],
)
def test_seeded_price_brackets(val, expected):
    # Bracket selection kept AS IS by decision (BUG card, item 3): smallest
    # limit_val >= val selects the bracket -- 1000.01 jumps to the 100-step
    # bracket. Tables are explicit admin config; see apply_rounding docstring.
    assert apply_rounding(val, "price") == expected


@pytest.mark.parametrize(
    "val, expected",
    [
        (0, 0),
        (-5, -5),  # re-baselined (BUG card): sign preserved, no silent clamp to 0
        (999.99, 1000.0),
        (12345.67, 12500.0),
        (1000000000.0, 1000000000.0),
    ],
)
def test_seeded_discount_brackets_match_price(val, expected):
    # admin seeds identical rules for both targets (admin/app.py:118-127)
    assert apply_rounding(val, "discount") == expected


def test_up_method():
    assert apply_rounding(100, "p1t2_up") == 105.0  # ceil(100/7)*7


def test_down_method():
    assert apply_rounding(100, "p1t2_down") == 98.0  # floor(100/7)*7


def test_unknown_method_falls_back_to_up():
    # else-branch at pricing/app.py:399-400
    assert apply_rounding(100, "p1t2_weird") == 105.0


@pytest.mark.parametrize(
    "val, expected",
    [
        (0.5, 1.0),   # half away from zero (Excel ROUND)
        (1.5, 2.0),
        (2.5, 3.0),   # was 2.0 under banker's rounding
        (3.5, 4.0),
        (4.5, 5.0),   # was 4.0 under banker's rounding
        (2.675, 3.0),
    ],
)
def test_nearest_is_half_away_from_zero(val, expected):
    # Re-baselined deliberately in the phase-2 bug-fix stage (board card
    # "BUG - pricing rounding semantics"): NEAREST now rounds half AWAY
    # FROM ZERO via Decimal ROUND_HALF_UP, matching Excel's ROUND and the
    # rent calculator's money path (was Python round()'s banker's
    # rounding: 0.5 -> 0, 2.5 -> 2).
    assert apply_rounding(val, "p1t2_nearest") == expected


def test_target_without_rules_returns_value_unchanged():
    assert apply_rounding(100.55, "p1t2_no_rules_anywhere") == 100.55
