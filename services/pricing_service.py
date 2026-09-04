"""Pricing calculation services (Phase 2 stage 4).

apply_rounding moved verbatim from pricing/app.py (including its inline
import math); pricing/app.py imports it back so route call sites and the
existing test imports keep working.
"""

from shared.db import get_db


def apply_rounding(val, target='price'):
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
        return round(val / step) * step
    else:
        return math.ceil(val / step) * step
