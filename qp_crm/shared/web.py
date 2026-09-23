"""Shared web-tier helpers for the QP-CRM module blueprints (Phase 2 stage 2).

Deduplicates the helpers that used to be copy-pasted into each Flask app:
theme/date-format reads, the `md` and `format_date` template filters, the
per-module login hook, the product-image route, and a few cross-module
settings readers (mandatory fields, rent defaults, rent template order,
rent email preset text). The moved bodies are behaviorally identical to the
copies they replace; where copies differed cosmetically (a dead `pass`
branch in offer's fix_markdown_lists, "\\u2013" escape vs the literal en
dash in the rent email text) the deduplicated version is byte-equivalent.

Registered app-wide filters: main.py registers format_date_filter as
'format_date' and render_markdown as 'md' once for the single app
(previously pricing and offer each registered their own copies on their own
Jinja environments).
"""

import os
import re

import markdown
from flask import abort, redirect, request, send_from_directory, session, url_for

from qp_crm.shared.config import IMAGE_DIR
from qp_crm.shared.db import get_db
from qp_crm.shared.utils import format_date


# ---------- theme / date format ----------

def get_theme():
    """Fetch the theme setting from cookies (default 'dark')."""
    return request.cookies.get("theme", "dark")


def get_date_format():
    """Fetch the date_format setting. global_settings is the ONE source of
    truth (audit M4): the admin dashboard writes the 'date_format' row and
    every formatter (format_date filter, PDF contexts) reads it through
    here, so output -- golden/PDF included -- is company-consistent.

    Defaults to 'YYYY-MM-DD' when the row is missing or the read fails.
    The old per-browser 'date_format' cookie fallback is gone: a stale
    cookie must not change formatting for a single machine.
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM global_settings WHERE key = 'date_format';")
        row = cur.fetchone()
        conn.close()
        if row and row["value"]:
            return row["value"]
    except Exception:
        pass

    return "YYYY-MM-DD"


def format_date_filter(date_str, fmt=None):
    """Jinja 'format_date' filter body.

    Unified on offer's superset signature (optional explicit format);
    pricing's copy was the 1-argument-only variant. Without an explicit fmt
    the company-wide date format (global_settings.date_format) applies.
    """
    return format_date(date_str, fmt or get_date_format())


# ---------- markdown ----------

def fix_markdown_lists(text):
    """Insert a blank line before a list that directly follows a paragraph,
    so the markdown 'extra' extension recognizes it as a list.
    """
    if not text:
        return text
    lines = text.split('\n')
    fixed_lines = []
    in_list = False
    for line in lines:
        is_list_item = bool(re.match(r'^[ \t]*([*+-]|\d+\.)[ \t]+', line))
        is_empty = not line.strip()
        if is_list_item and not in_list and fixed_lines and fixed_lines[-1].strip():
            fixed_lines.append('')
        fixed_lines.append(line)
        if is_empty:
            in_list = False
        elif is_list_item:
            in_list = True
    return '\n'.join(fixed_lines)


def render_markdown(text):
    """Jinja 'md' filter body (pricing/offer copies were identical)."""
    if not text:
        return ""
    text = fix_markdown_lists(text)
    return markdown.markdown(text, extensions=['extra', 'nl2br'])


# ---------- per-module auth hook ----------

def make_auth_hook(session_flag, login_endpoint, exempt_endpoints=()):
    """Build a blueprint-level before_request hook enforcing module login.

    session_flag: per-module key inside the (now shared) session cookie --
    pricing_authenticated / offer_authenticated / rent_authenticated /
    admin_authenticated. Keeping per-module flags preserves the pre-
    consolidation semantics where each app had its own cookie and logging
    into one module never unlocked another.
    """
    exempt = frozenset(exempt_endpoints) | {login_endpoint}

    def check_auth():
        if request.endpoint in exempt:
            return None
        if not session.get(session_flag):
            return redirect(url_for(login_endpoint))

    return check_auth


# ---------- CSRF (Phase 3 step 5, generalized from the settings app) ----------

CSRF_FIELD = "_csrf_token"
CSRF_SESSION_KEY = "_csrf_token"
CSRF_METHODS = ("POST", "PUT", "PATCH", "DELETE")

# Endpoints exempt from CSRF checks. api_v1 authenticates via the
# Authorization: Bearer header (per-user API keys / global key) -- a request
# that authenticates WITHOUT ambient cookie credentials cannot be abused by
# cross-site form posts, so the token check does not apply there.
CSRF_EXEMPT_ENDPOINT_PREFIXES = ("api_v1.",)


def csrf_token():
    """Return (and create if needed) the per-session CSRF token.

    The settings app's token pattern, generalized: one token per SESSION,
    created lazily on first render and verified on every state-changing
    request across ALL blueprints.
    """
    import secrets

    if CSRF_SESSION_KEY not in session:
        session[CSRF_SESSION_KEY] = secrets.token_hex(16)
    return session[CSRF_SESSION_KEY]


def check_csrf():
    """App-level before_request hook: enforce the CSRF token on every
    state-changing request (POST/PUT/PATCH/DELETE) of every blueprint.

    Returns None when the request may proceed, else a 400 response (the
    settings app's exact 'CSRF token mismatch' body). The token is accepted
    from the form field (server-rendered forms) or the X-CSRF-Token header
    (AJAX fetch posts).
    """
    import secrets

    if request.method not in CSRF_METHODS:
        return None
    endpoint = request.endpoint or ""
    if any(endpoint.startswith(prefix) for prefix in CSRF_EXEMPT_ENDPOINT_PREFIXES):
        return None

    session_token = session.get(CSRF_SESSION_KEY)
    supplied = request.form.get(CSRF_FIELD) or request.headers.get("X-CSRF-Token") or ""
    if not session_token or not supplied or not secrets.compare_digest(supplied, session_token):
        return "CSRF token mismatch", 400
    return None


# ---------- unified auth (Phase 3) ----------

def safe_next_url():
    """The 'next' redirect target from the request, or None when unsafe.

    Only same-site absolute paths are allowed ('/x', not '//host' or
    'http://...'), so an open redirect cannot be smuggled through ?next=.
    """
    candidate = request.values.get("next") or ""
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return None


def require_role(*roles, exempt_endpoints=()):
    """Blueprint-level role gate (Phase 3 step 4).

    Replaces both the pre-Phase-3 per-module password flags and step 3's
    plain require_login: ONE unified login establishes the session identity,
    and each blueprint declares WHO may enter:

        admin blueprint      -> require_role("admin")
        pricing/offer/rent   -> require_role("staff", "admin")
                                ('admin' is the superset role: an admin may
                                open every business module)
        sale / settings      -> public, no hook
        /api/v1/health       -> public (API endpoints authenticate by key)

    The user row is re-read from the DB on EVERY gated request, so a
    deactivation or role change in the admin Users UI takes effect on the
    user's next request (not just on their next login). Anonymous users are
    redirected to the unified login with a safe ?next=; authenticated users
    without a permitted role get 403.
    exempt_endpoints: full endpoint names (e.g. 'offer.api_nbs_eur_rate')
    that stay reachable without a session, exactly as before Phase 3.
    """
    from qp_crm.shared.auth import get_user_by_id

    exempt = frozenset(exempt_endpoints)

    def check_auth():
        if request.endpoint in exempt:
            return None
        user_id = session.get("user_id")
        if not user_id:
            next_url = safe_next_url() or request.path
            if next_url and next_url != "/":
                return redirect(url_for("auth.login", next=next_url))
            return redirect(url_for("auth.login"))

        user = get_user_by_id(user_id)
        if user is None:
            # Deactivated or deleted while logged in: kill the session.
            session.clear()
            return redirect(url_for("auth.login"))

        if roles and user["role"] not in roles:
            abort(403, description="Nemate dozvolu za ovu stranicu. (Your account role does not permit this page.)")

        # A role changed while logged in takes effect immediately.
        if session.get("role") != user["role"]:
            session["role"] = user["role"]

    return check_auth


def require_module(module, exempt_endpoints=()):
    """Blueprint-level PER-USER APP-ACCESS gate (post-Phase-3 request).

    Replaces require_role("staff", "admin") on the business modules:
    which apps a STAFF user may open is now a per-user list managed in
    Admin -> Users (user_modules table, checkboxes). Behavior:

        no session          -> unified login with a safe ?next=
        inactive/deleted    -> session cleared, login
        role == 'admin'     -> always allowed (superset, bypasses grants)
        staff WITH the grant-> allowed
        staff WITHOUT it    -> 403 (message names the missing app)

    The grant is re-read from the DB on EVERY request (same freshness rule
    as require_role): revoking an app hits the user on their next click.
    `module` must be a name from shared.auth.MODULE_CHOICES.
    """
    from qp_crm.shared.auth import get_user_by_id, user_has_module

    exempt = frozenset(exempt_endpoints)

    def check_auth():
        if request.endpoint in exempt:
            return None
        user_id = session.get("user_id")
        if not user_id:
            next_url = safe_next_url() or request.path
            if next_url and next_url != "/":
                return redirect(url_for("auth.login", next=next_url))
            return redirect(url_for("auth.login"))

        user = get_user_by_id(user_id)
        if user is None:
            session.clear()
            return redirect(url_for("auth.login"))

        # A role changed while logged in takes effect immediately.
        if session.get("role") != user["role"]:
            session["role"] = user["role"]

        if user["role"] == "admin":
            return None  # admins open every app
        if user_has_module(user_id, module):
            return None
        abort(403, description=(
            f"Nemate pristup modulu '{module}'. (Your account does not have "
            f"access to the {module} app -- ask an admin to grant it in "
            "Admin -> Users.)"
        ))

    return check_auth


# ---------- product image route ----------

def register_product_image(bp):
    """Register the /product-image/<path:filename> route on a blueprint.

    pricing, offer and sale carried byte-identical copies; the endpoint name
    is 'product_image' inside each blueprint (pricing.product_image, ...).
    """
    @bp.route("/product-image/<path:filename>")
    def product_image(filename):
        return send_from_directory(IMAGE_DIR, filename)


# ---------- product photo processing (pricing UI + api_v1, EN/SR messages) ----------

def save_product_image(image_stream, orig_filename, product_name,
                       error_ext, error_process_prefix):
    """Process and save an image (from stream) to IMAGE_DIR, resized to max
    800x800. Returns the filename (e.g. 'my_product.jpg') or raises
    ValueError. Callers pass their own message texts (pricing UI: Serbian,
    api_v1: English) so the deduplication does not change any user-visible
    string.
    """
    from PIL import Image

    if not image_stream or not orig_filename:
        return None

    # Check extension
    ext = os.path.splitext(orig_filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise ValueError(error_ext)

    # Build base name from product_name
    base = (product_name or "").strip().lower()
    base = re.sub(r"\s+", "_", base)
    base = re.sub(r"[^a-z0-9_-]", "", base)
    if not base:
        base = "product"

    filename = base + ".jpg"

    os.makedirs(IMAGE_DIR, exist_ok=True)
    dest_path = os.path.join(IMAGE_DIR, filename)

    try:
        img = Image.open(image_stream)

        # PNG Transparency handling
        if 'A' in img.mode:
            img = img.convert("RGBA")
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img)
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")

        # Resize
        max_size = (800, 800)
        img.thumbnail(max_size)

        # Save as JPEG
        img.save(dest_path, format="JPEG", quality=85)

    except Exception as e:
        raise ValueError(error_process_prefix + str(e))

    return filename


def download_image_from_url(url, error_content_type, error_request_prefix):
    """Download image from URL, validate it's an image.
    Returns (BytesIO stream, filename) or raises ValueError. Message texts
    are caller-supplied (pricing UI: Serbian, api_v1: English).
    """
    import io

    import requests

    try:
        resp = requests.get(url, timeout=10, stream=True)
        resp.raise_for_status()

        content_type = resp.headers.get('Content-Type', '').lower()
        if 'image/jpeg' not in content_type and 'image/png' not in content_type and 'image/webp' not in content_type:
            raise ValueError(error_content_type)

        orig_filename = url.split("/")[-1].split("?")[0] or "url_image.jpg"
        if not any(orig_filename.lower().endswith(ex) for ex in ['.jpg', '.jpeg', '.png', '.webp']):
            if 'png' in content_type:
                orig_filename += '.png'
            elif 'webp' in content_type:
                orig_filename += '.webp'
            else:
                orig_filename += '.jpg'

        return io.BytesIO(resp.content), orig_filename

    except requests.exceptions.RequestException as e:
        raise ValueError(error_request_prefix + str(e))


# ---------- cross-module settings readers ----------

MANDATORY_FIELD_KEYS = [
    'req_client_address', 'req_client_email', 'req_client_phone',
    'req_client_pib', 'req_client_mb',
]


def fetch_mandatory_fields(cur):
    """Read the mandatory-field flags for an existing cursor.

    offer.get_mandatory_fields and admin's dashboard loop carried identical
    logic ('true' -> True, anything else/missing -> False).
    """
    settings = {}
    for field in MANDATORY_FIELD_KEYS:
        cur.execute("SELECT value FROM global_settings WHERE key = ?;", (field,))
        row = cur.fetchone()
        settings[field] = (row["value"] == "true") if row else False
    return settings


# Rent module defaults (global_settings keys and their fallback values).
# Values are the exact strings both copies produced (rent str()-ed float
# defaults into the same strings).
RENT_DEFAULT_KEYS = {
    'rent_default_interest_rate': '14.0',
    'rent_default_insurance_rate': '1.13',
    'rent_default_guarantee_rate': '5.0',
    'rent_default_admin_fee': '50.0',
    'rent_default_vat_percent': '20.0',
    'rent_default_salvage_value_percent': '20.0',
    'rent_default_downpayment_percent': '20.0',
    'rent_default_period_months': '48',
}


def fetch_rent_defaults(cur):
    """Read the rent default parameters for an existing cursor."""
    result = {}
    for key, default in RENT_DEFAULT_KEYS.items():
        cur.execute("SELECT value FROM global_settings WHERE key = ?;", (key,))
        row = cur.fetchone()
        result[key] = row["value"] if row else default
    return result


# Preferred display order for rent templates (slugs not listed go to the
# end). rent._sort_templates and admin._sort_rent_templates were identical.
RENT_TEMPLATE_SORT_ORDER = [
    "ugovor-zakup",
    "prilog-1-zapisnik",
    "prilog-2-protokol",
    "menicno-ovlascenje",
    "instrukcija-avans",
    "info-osiguranje",
    "ugovor-zakup-jemac",
    "zapisnik-preuzimanje",
]


def sort_rent_templates(templates):
    """Sort template rows by the preferred display order."""
    order_map = {slug: i for i, slug in enumerate(RENT_TEMPLATE_SORT_ORDER)}
    return sorted(templates, key=lambda t: order_map.get(t["slug"], 999))


# Default rent email preset/subject shown when global_settings carries no
# override. Four/five copies existed across rent and admin (the "\u2013"
# escape vs the literal en dash were the same character).
DEFAULT_RENT_EMAIL = (
    "Poštovani,\n\n"
    "U prilogu Vam dostavljamo sva dokumenta vezana za zakup opreme.\n\n"
    "Ukoliko ste saglasni, molimo Vas da to potvrdite emailom, kako bismo Vam "
    "poštom poslali potpisane primerke ugovora koje nam na dan ugradnje opreme "
    "vraćate sa Vašim potpisom. Svaki prilog ide u 4 primerka – 2 za Vas i 2 za nas.\n\n"
    "Molimo Vas da popunite i meničko ovlašćenje.\n\n"
    "Uplatu avansa izvršite na osnovu Instrukcija za uplatu avansa, "
    "a nakon toga pratite Plan plaćanja.\n\n"
    "Srdačan pozdrav,\nMarinković-Hofmann d.o.o."
)

DEFAULT_RENT_EMAIL_SUBJECT = "Ugovor i prilozi za zakup opreme - {{ contract_number }} - {{ client_name }}"
