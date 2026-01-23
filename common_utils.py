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

def format_date(date_str, fmt):
    """
    Format YYYY-MM-DD string into user preference.
    fmt can be 'YYYY-MM-DD', 'DD/MM/YYYY', 'MM/DD/YYYY', 'DD.MM.YYYY'
    """
    if not date_str:
        return ""
    try:
        # Expected input is YYYY-MM-DD
        y, m, d = date_str.split('-')
        if fmt == 'DD/MM/YYYY':
            return f"{d}/{m}/{y}"
        elif fmt == 'MM/DD/YYYY':
            return f"{m}/{d}/{y}"
        elif fmt == 'DD.MM.YYYY':
            return f"{d}.{m}.{y}"
        else:
            return date_str # default to YYYY-MM-DD
    except:
        return date_str