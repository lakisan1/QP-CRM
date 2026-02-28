# shared/utils.py

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

# SIMPLE i18n MANAGER
TRANSLATIONS = {
    'sr': {
        'Customer': 'Kupac',
        'OFFER No.': 'PONUDA br.',
        'Date': 'Datum',
        'Offer Items': 'Stavke ponude',
        'No.': 'R.b.',
        'Image': 'Slika',
        'Description': 'Opis',
        'Qty': 'Kol.',
        'Unit Price': 'Jed. cena',
        'Disc %': 'Popust %',
        'Total': 'Ukupno',
        'SUBTOTAL': 'MEĐUZBIR',
        'DISCOUNT': 'POPUST',
        'VAT': 'PDV',
        'AMOUNT DUE': 'UKUPNO ZA UPLATU',
        'NOTE': 'NAPOMENA',
        'PAYMENT TERMS': 'USLOVI PLAĆANJA',
        'DELIVERY TERMS': 'USLOVI ISPORUKE',
        'OFFER VALIDITY': 'VAŽNOST PONUDE',
        'days': 'dana',
        'THE OFFER IS VALID WITHOUT STAMP AND SIGNATURE': 'PONUDA JE VAŽEĆA BEZ PEČATA I POTPISA',
        'Product': 'Proizvod',
        'Products': 'Proizvodi',
        'Add Product': 'Dodaj proizvod',
        'Brand': 'Brend',
        'Brands': 'Brendovi',
        'Category': 'Kategorija',
        'Categories': 'Kategorije',
        'Search': 'Pretraga',
        'Clear': 'Očisti',
        'Actions': 'Akcije',
        'Edit Product': 'Izmeni proizvod',
        'Delete': 'Obriši',
        'Price History': 'Istorija cena',
        'Current Price': 'Trenutna cena',
        'Discount Price': 'Akcijska cena',
        'Settings': 'Podešavanja',
        'Product List': 'Spisak proizvoda',
        'Category List': 'Spisak kategorija',
        'Quick Update': 'Brzo Ažuriranje',
        'Offers': 'Ponude',
        'Compare Offers': 'Uporedi ponude',
        'Logout': 'Odjavi se',
        'View Landing Page': 'Početna strana',
        'PDF Templates': 'PDF Šabloni',
        'Rounding Rules': 'Pravila zaokruživanja',
        'Landing Page': 'Početna strana',
        'Address': 'Adresa',
        'Phone': 'Telefon',
        'Tel': 'Tel',
        'products': 'proizvoda',
        'offers': 'ponuda',
        'PriceList': 'Cenovnik',
        'Sale': 'Prodaja'
    },
    'en': {
        # Defaults are mostly English in the code
    }
}

from shared.db import get_db

def get_current_language():
    """Fetch the current language from global_settings."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM global_settings WHERE key = 'language';")
        row = cur.fetchone()
        conn.close()
        return row["value"] if row else "en"
    except Exception:
        return "en"

def translate(text, lang='en'):
    if lang == 'en':
        return text
    return TRANSLATIONS.get(lang, {}).get(text, text)

# Shorthand for templates
def _(text, lang='en'):
    return translate(text, lang)

import requests

def get_nbs_rate(currency="eur"):
    """
    Get today's middle rate for a currency from Kurs API (uses NBS data).
    Returns float or None on error.
    """
    url = f"https://kurs.resenje.org/api/v1/currencies/{currency.lower()}/rates/today"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        rate = data.get("exchange_middle")
        if rate is None:
            return None
        return float(rate)
    except Exception as e:
        print(f"Error fetching {currency} rate:", e)
        return None
