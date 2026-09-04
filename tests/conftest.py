"""Phase-1 test isolation + shared fixtures (P1-T1).

Every test run gets a throwaway app_data tree. shared/config.py computes
APP_DATA_DIR / DATABASE / IMAGE_DIR from BASE_DIR at import time, and every
sub-app binds those names into its own namespace at import time
(``from qp_crm.shared.config import ... DATABASE ...``). The patch below therefore
MUST run before any app module is imported: pytest imports conftest.py
before collecting test modules, so doing it at conftest top level is the one
guaranteed-early moment. After this, shared.db.get_db() (which reads
shared.db.DATABASE -- itself bound from qp_crm.shared.config) opens connections
against the temp DB, and the real app_data/pricing.db bind-mount is never
touched by the suite.

Run the whole suite with ONE command from the repo root:

    docker compose build app           # only when code/tests/deps changed
    docker compose run --rm app pytest

Characterization discipline (Phase 1 card): these tests pin CURRENT behavior
of the unmodified app, quirks included. Failures mean "behavior changed",
never "fix the app in this phase" -- log discoveries as bug cards instead.
"""

import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# FIXED test root -- deliberately NOT tempfile.mkdtemp(): WeasyPrint names
# image XObjects 'i' + md5(their URL), so a random path would change the
# golden PDF bytes on every run. /tmp is wiped with the container, so this
# is fresh per `docker compose run` anyway. Consequence: do not run two
# suites against the same image in parallel (they would share the path).
TEST_ROOT = "/tmp/qp-crm-tests"
if os.path.exists(TEST_ROOT):
    shutil.rmtree(TEST_ROOT)
TEST_APP_DATA_DIR = os.path.join(TEST_ROOT, "app_data")
TEST_IMAGE_DIR = os.path.join(TEST_APP_DATA_DIR, "product_images")
TEST_ASSETS_DIR = os.path.join(TEST_ROOT, "app_assets")
TEST_DATABASE = os.path.join(TEST_APP_DATA_DIR, "pricing.db")

for _directory in (TEST_APP_DATA_DIR, TEST_IMAGE_DIR, TEST_ASSETS_DIR):
    os.makedirs(_directory, exist_ok=True)

# --- patch shared.config BEFORE any app module imports it --------------------
# BASE_DIR stays real on purpose: template folders, static/ (incl. the offer
# PDF css) are code, not state, and rent's document renderer
# uses BASE_DIR as the WeasyPrint base_url.
import qp_crm.shared.config as _config  # noqa: E402

_config.APP_DATA_DIR = TEST_APP_DATA_DIR
_config.DATABASE = TEST_DATABASE
_config.IMAGE_DIR = TEST_IMAGE_DIR
_config.APP_ASSETS_DIR = TEST_ASSETS_DIR

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def temp_db():
    """The throwaway DB path, after the production init sequence ran on it.

    Same order as main.py's __main__ block and wsgi.py. All five inits are
    idempotent and seed deterministic defaults (rounding rules, "System
    Default" PDF template, rent templates from rent_templates_defaults.json).
    """
    from qp_crm.pricing.app import init_db as pricing_init_db, migrate_schema as pricing_migrate_schema
    from qp_crm.offer.app import init_db as offer_init_db
    from qp_crm.admin.app import init_db as admin_init_db
    from qp_crm.rent.app import init_db as rent_init_db

    pricing_init_db()
    pricing_migrate_schema()
    offer_init_db()
    admin_init_db()
    rent_init_db()
    return TEST_DATABASE


@pytest.fixture(scope="session")
def conn_factory(temp_db):
    """Context-manager factory for connections against the throwaway DB."""
    import contextlib
    from qp_crm.shared.db import get_db

    @contextlib.contextmanager
    def _conn():
        conn = get_db()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    return _conn


def login_client(client, username, password=None):
    """Log a test client in through the REAL unified login (Phase 3 step 3).

    POSTs /login with the seeded default password of that account, then
    simulates the completed first-login change: require_role (step 4)
    re-reads must_change_password from the users row on every request, so
    the seeded staff flag is cleared IN THE DB -- not just in the session --
    while the password hashes stay at the seeded defaults (other tests keep
    authenticating with shared.auth.DEFAULT_PASSWORDS).
    """
    from qp_crm.main import app  # noqa: F401  (app must be importable)
    from qp_crm.shared.auth import DEFAULT_PASSWORDS, get_db

    # Establish the session CSRF token via the login page render (Phase 3
    # step 5: the unified login POST is CSRF-protected like every other).
    client.get("/login")
    with client.session_transaction() as session:
        token = session.get("_csrf_token")
    resp = client.post(
        "/login",
        data={
            "username": username,
            "password": password or DEFAULT_PASSWORDS[username],
            "_csrf_token": token,
        },
    )
    assert resp.status_code == 302, f"login for {username} failed: {resp.status_code}"
    conn = get_db()
    conn.execute(
        "UPDATE users SET must_change_password = 0 WHERE username = ?;", (username,)
    )
    conn.commit()
    conn.close()
    with client.session_transaction() as session:
        session.pop("must_change_password", None)
        # The login handler's session.clear() (step 3 session cycling) also
        # wiped the CSRF token; a real browser re-mints it on the next page
        # render (csrf_token() in the template). Tests that POST directly
        # after login mint one here instead.
        if not session.get("_csrf_token"):
            import secrets as _secrets
            session["_csrf_token"] = _secrets.token_hex(16)
    return client


def csrf_token_for(client):
    """The session CSRF token of a Flask test client (Phase 3 step 5).

    Tests that POST forms directly through an authenticated fixture client
    include this in their form data (the app-level check_csrf enforces it).
    """
    with client.session_transaction() as session:
        return session.get("_csrf_token")


@pytest.fixture(scope="session")
def offer_client(temp_db):
    """Flask test client for the offer module, pre-authenticated through the
    unified login as the seeded 'offer' (staff) account."""
    from qp_crm.main import app

    return login_client(app.test_client(), "offer")


@pytest.fixture(scope="session")
def rent_client(temp_db):
    """Flask test client for the rent module, pre-authenticated through the
    unified login as the seeded 'rent' (staff) account."""
    from qp_crm.main import app

    return login_client(app.test_client(), "rent")


@pytest.fixture(scope="session")
def admin_client(temp_db):
    """Flask test client pre-authenticated as the seeded 'admin' account."""
    from qp_crm.main import app

    return login_client(app.test_client(), "admin")


@pytest.fixture(scope="session")
def stack_client(temp_db):
    """Werkzeug client over qp_crm.main.application -- the real WSGI stack exactly as
    gunicorn serves it (single Flask app with real URL prefixes; pre-Phase-2
    this was the DispatcherMiddleware merge of six sub-apps).
    """
    from werkzeug.test import Client
    import qp_crm.main

    return Client(qp_crm.main.application)


@pytest.fixture(scope="session")
def assets_dir(temp_db):
    """Copy the fixed golden-fixture assets into the throwaway APP_ASSETS_DIR.

    The offer PDF renders logo_company.jpg / pdf_footer_image.png from
    APP_ASSETS_DIR and the rent document embeds the logo as a base64 data
    URI. Using small checked-in fixture images keeps the golden bytes
    independent of whatever logo happens to sit in the host app_assets/.
    """
    import shutil

    src = os.path.join(PROJECT_ROOT, "tests", "golden", "assets")
    for name in os.listdir(src):
        shutil.copy2(os.path.join(src, name), os.path.join(TEST_ASSETS_DIR, name))
    return TEST_ASSETS_DIR
