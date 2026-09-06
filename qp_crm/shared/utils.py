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
        'Home': 'Početna strana',
        'PDF Templates': 'PDF Šabloni',
        'Rounding Rules': 'Pravila zaokruživanja',
        'Address': 'Adresa',
        'Phone': 'Telefon',
        'Tel': 'Tel',
        'products': 'proizvoda',
        'offers': 'ponuda',
        'PriceList': 'Cenovnik',
        'Search brands': 'Pretraži brendove',
        'Search by name': 'Pretraga po imenu',
        'Search categories': 'Pretraži kategorije',
        'Search contracts': 'Pretraga ugovora',
        'Search offers': 'Pretraga ponuda',
        '+ Add Row': '+ Dodaj red',
        'A product with this name already exists.': 'Proizvod sa ovim imenom već postoji.',
        'Add / Edit Category': 'Dodaj / izmeni kategoriju',
        'Add. Costs': 'Dodatni tr.',
        'Additional Costs': 'Dodatni troškovi',
        'Administrative Cost (€)': 'Administrativni trošak (€)',
        'All': 'Svi',
        'All brands': 'Svi brendovi',
        'All categories': 'Sve kategorije',
        'Annual Interest Rate (%)': 'Godišnja kamata (%)',
        'Another product with this name already exists.': 'Drugi proizvod sa ovim imenom već postoji.',
        'App theme': 'Tema aplikacije',
        'Back to Sale': 'Nazad na prodaju',
        'Brand Filter:': 'Filter Brend:',
        'Calculated Price': 'Izračunata cena',
        'Calculated Price after Discount:': 'Izračunata cena sa popustom:',
        'Calculated Price:': 'Izračunata cena:',
        'Cancel': 'Otkaži',
        'Category Filter:': 'Filter Kategorija:',
        'Category Name': 'Naziv kategorije',
        'Click to mark as signed': 'Klikni da označiš kao potpisan',
        'Click to mark as unsigned': 'Klikni da poništiš potpis',
        'Client': 'Klijent',
        'Clients': 'Klijenti',
        'Compare two different sets of items or discounts side by side.': 'Poredite dva različita seta artikala ili popusta side-by-side.',
        'Connection error.': 'Greška pri povezivanju.',
        'Contract Number': 'Broj Ugovora',
        'Contracts': 'Ugovori',
        'Cost to Us': 'Cena ka nama',
        'Costs': 'Troškovi',
        'Currency:': 'Valuta:',
        'Dark': 'Tamna (Dark)',
        'Data is not saved to the database.': 'Podaci se ne čuvaju u bazi podataka.',
        'Date format': 'Format datuma',
        'Default Number of Months': 'Podrazumevani broj meseci',
        'Delete Contract': 'Brisanje ugovora',
        'Discount': 'Popust',
        'Discount %': 'Popust %',
        'Discounted Price': 'Cena sa popustom',
        'Down Payment / Advance (%)': 'Učešće / Avans (%)',
        'Duplicate this product?': 'Duplirati ovaj proizvod?',
        'Equipment': 'Oprema',
        'Equipment Model': 'Model Opreme',
        'Error downloading image from URL: ': 'Greška pri preuzimanju slike sa URL-a: ',
        'Error fetching exchange rates.': 'Greška pri preuzimanju kurseva.',
        'Error processing image: ': 'Greška pri obradi slike: ',
        'Error:': 'Greška:',
        'Final Price': 'Konačna cena',
        'Final Price (rounded)': 'Konacna cena (lepa okrugla)',
        'Final Price and Profit': 'Konačna cena i zarada',
        'From date:': 'Od datuma:',
        'Guarantee Rate – annual (%)': 'Stopa garancije – god. (%)',
        'Image (JPG, PNG, WEBP):': 'Slika (JPG,PNG,WEBP):',
        'Image must be JPG, PNG or WEBP (.jpg, .jpeg, .png or .webp).': 'Slika mora biti JPG, PNG ili WEBP (.jpg, .jpeg, .png, ili .webp).',
        'Insurance Rate – annual (%)': 'Stopa osiguranja – god. (%)',
        'Light': 'Svetla (Light)',
        'Line Total': 'Red zbir',
        'Log in': 'Prijavi se',
        'Login': 'Prijava',
        'Margin %': 'Zarada %',
        'Monthly Gross Installment (€)': 'Mesečna rata bruto (€)',
        'Monthly Net Installment (€)': 'Mesečna rata neto (€)',
        'New Contract': 'Novi Ugovor',
        'Next »': 'Sledeća »',
        'No brands defined yet. Go to Brands first.': 'Nema definisanih brendova. Idite prvo na "Brendovi".',
        'No categories defined yet. Go to Category Defaults first.': 'Nema definisanih kategorija. Idite prvo na "Podrazumevane vrednosti kategorija".',
        'No contracts.': 'Nema ugovora.',
        'Not signed': 'Nije potpisan',
        'Offer Comparison': 'Poređenje ponuda',
        'Offer Comparison Tool': 'Alat za poređenje ponuda',
        'One login for all modules': 'Jedinstvena prijava za sve module',
        'Password': 'Lozinka',
        'Price (€)': 'Cena (€)',
        'Price per Unit': 'Cena kom',
        'Product Name': 'Naziv proizvoda',
        'Profit (Discounted Price)': 'Profit (Cena sa popustom)',
        'Profit (Final Price)': 'Profit (Konačna cena)',
        'Purchase Price': 'Nabavna cena',
        'Quick Price Update': 'Brzo Ažuriranje Cena',
        'RSD/USD price (EUR converter)': 'Cena RSD/USD (Konvertor u EUR)',
        'Rent': 'Zakup',
        'Rent Contracts': 'Ugovori – Zakup',
        'Rent Contracts Overview': 'Pregled Ugovora o Zakupu',
        'Rent Templates': 'Rent Šabloni',
        'Rent – Default Financial Parameters': 'Zakup – Podrazumevani finansijski parametri',
        'Reset search': 'Reset pretrage',
        'Residual Value (%)': 'Ostatak vrednosti (%)',
        'Save': 'Sačuvaj',
        'Save Changes': 'Sačuvaj izmene',
        'Save Price': 'Sačuvaj cenu',
        'Save Rent Parameters': 'Sačuvaj Rent Parametre',
        'Save and Add New Price': 'Sačuvaj i dodaj novu cenu',
        'Save and Add Price': 'Sačuvaj i dodaj cenu',
        'Search (number / client):': 'Pretraga (broj / klijent):',
        'Search brands...': 'Pretraži brendove...',
        'Search by name:': 'Pretraga po imenu:',
        'Search categories...': 'Pretraži kategorije...',
        'Settings are stored only on this device (cookies) and do not affect other devices.': 'Podešavanja se čuvaju samo na ovom uređaju (cookies). Ne utiču na druge uređaje.',
        'Signature status:': 'Status potpisa:',
        'Signed': 'Potpisan',
        'Sync Website': 'Sync Sajt',
        'These values load automatically when a new rent contract is created.': 'Ove vrednosti se automatski učitavaju pri kreiranju novog ugovora o zakupu.',
        'They can be edited per individual contract.': 'Mogu se izmeniti pojedinačno po ugovoru.',
        'To date:': 'Do datuma:',
        'Too many failed login attempts. Try again in {} min.': 'Previše neuspelih pokušaja. Pokušajte ponovo za {} min.',
        'Total Cost': 'Ukupno koštanje',
        'URL does not point to a JPG, PNG or WEBP image.': 'URL ne vodi do JPG, PNG ili WEBP slike.',
        'Unsigned': 'Nepotpisani',
        'Username': 'Korisničko ime',
        'VAT %': 'PDV %',
        'VAT (%)': 'PDV (%)',
        'With Disc.': 'Sa pop.',
        'Wrong username or password': 'Pogrešno korisničko ime ili lozinka',
        'Yes, delete': 'Da, obriši',
        'choose a brand': 'izaberite brend',
        'choose a category': 'izaberite kategoriju',
        'contracts': 'ugovora',
        'optional — leave empty to use the calculated price': 'optional, ako se ostavi prazno koristi Izracunatu cenu',
        'Sale': 'Prodaja'
    },
    'en': {
        # Defaults are mostly English in the code
    }
}

from qp_crm.shared.db import get_db

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
