"""Pricing calculation services (Phase 2 stage 4).

apply_rounding moved verbatim from pricing/app.py (including its inline
import math); pricing/app.py imports it back so route call sites and the
existing test imports keep working.
"""

from qp_crm.shared.db import get_db


from decimal import Decimal, ROUND_HALF_UP


def apply_rounding(val, target='price'):
    """Apply the price_rounding_rules bracket for `target` to `val`.

    BUG-fix semantics (phase-2 bug-fix stage, card "pricing rounding
    semantics: banker's NEAREST + val<=0 clamp to 0 + bracket-boundary
    jump") -- two deliberate changes, one decision to keep:

    * NEAREST now rounds half AWAY FROM ZERO (Decimal ROUND_HALF_UP),
      matching Excel's ROUND and the rent calculator's money path --
      Python round()'s banker's rounding made 0.5 -> 0 while rent went
      0.5 -> 1, so the two money paths disagreed.
    * val <= 0 returns val UNCHANGED (sign preserved); it used to clamp
      to 0, silently zeroing a negative price/discount.
    * Bracket selection is UNCHANGED by decision: smallest limit_val >=
      val selects the bracket, so 1000.01 uses the 100-step bracket.
      Bracket tables are explicit admin config; changing selection would
      alter every seeded price. Revisit only with a product decision.
    """
    if val <= 0:
        return val
    if val <= 0:
        return 0
    
    conn = get_db()
    cur = conn.cursor()
    # Find the matching rule: smallest limit >= val
    cur.execute("""
        SELECT step_val, method 
        FROM price_rounding_rules 
        WHERE target = ? AND limit_val >= ? 
        ORDER BY limit_val ASC 
        LIMIT 1;
    """, (target, val))
    rule = cur.fetchone()
    
    if not rule:
        # Fallback to the largest limit rule for this target
        cur.execute("""
            SELECT step_val, method 
            FROM price_rounding_rules 
            WHERE target = ? 
            ORDER BY limit_val DESC 
            LIMIT 1;
        """, (target,))
        rule = cur.fetchone()
    
    conn.close()
    
    if not rule:
        return val # No rules defined
        
    step = rule["step_val"]
    method = rule["method"]
    
    import math
    if method == 'UP':
        return math.ceil(val / step) * step
    elif method == 'DOWN':
        return math.floor(val / step) * step
    elif method == 'NEAREST':
        quotient = (Decimal(str(val)) / Decimal(str(step))).quantize(
            Decimal('1'), rounding=ROUND_HALF_UP)
        return float(quotient * Decimal(str(step)))
    else:
        return math.ceil(val / step) * step
