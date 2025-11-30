# format for money
def format_amount(value):
    """Format number as 12.312,00 (European style)."""
    if value is None:
        value = 0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    # 12,312.00
    s = f"{v:,.2f}"
    # convert to 12.312,00
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s