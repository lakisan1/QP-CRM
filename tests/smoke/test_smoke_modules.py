"""P1-T7 smoke tests: login -> main page -> 200 through the REAL stack.

These run against main.application -- the single Flask app exactly as
gunicorn serves it (pre-Phase-2: the DispatcherMiddleware stack) -- with the
throwaway fixture DB from conftest (fresh
schemas, seeded defaults, NO password rows in global_settings, so
shared.auth.DEFAULT_PASSWORDS are active; that fallback itself is pinned
behavior from shared/auth.py:69-92).

Pinned current behavior (Phase 1 discipline -- do not fix here):
* pricing/offer/rent/admin gate EVERY page behind a login redirect;
* sale and settings have NO authentication at all (audit C5/H territory);
* a wrong password re-renders the login page (200) and stays locked out.
"""

import pytest
from werkzeug.test import Client

import main
from shared.auth import DEFAULT_PASSWORDS

GATED_MODULES = ("pricing", "offer", "rent", "admin")


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    """Guarantee the init sequence ran, even in a smoke-only run.

    Without this, DB-touching pages 500 on the empty schema (discovered the
    hard way: sale.list_sale SELECTs global_settings unguarded). The full
    suite masks it because characterization tests trigger temp_db first.
    """
    yield


def fresh_client():
    """A clean cookie jar -- no session."""
    return Client(main.application)


def test_landing_page_serves_200():
    response = fresh_client().get("/")
    assert response.status_code == 200


@pytest.mark.parametrize("module", GATED_MODULES)
def test_gated_module_redirects_to_login(module):
    response = fresh_client().get(f"/{module}/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/{module}/login")


@pytest.mark.parametrize("module", GATED_MODULES)
def test_login_page_renders(module):
    response = fresh_client().get(f"/{module}/login")
    assert response.status_code == 200


@pytest.mark.parametrize("module", GATED_MODULES)
def test_wrong_password_stays_locked_out(module):
    client = fresh_client()
    response = client.post(f"/{module}/login", data={"password": "definitely-wrong-42"})
    assert response.status_code == 200                   # login page re-rendered
    assert client.get(f"/{module}/").status_code == 302  # still locked out


@pytest.mark.parametrize("module", GATED_MODULES)
def test_login_reaches_main_page(module):
    # POST followed through the redirect lands on the module root: 200
    client = fresh_client()
    response = client.post(
        f"/{module}/login",
        data={"password": DEFAULT_PASSWORDS[module]},
        follow_redirects=True,
    )
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/pricing/products", "/offer/offers", "/rent/contracts", "/admin/"])
def test_main_pages_200_after_module_login(path):
    module = path.split("/")[1]
    client = fresh_client()
    login = client.post(f"/{module}/login", data={"password": DEFAULT_PASSWORDS[module]})
    assert login.status_code == 302              # redirect to the module root
    assert client.get(path).status_code == 200


def test_sale_needs_no_login():
    # sale is completely open: / is a plain redirect to the pricelist
    client = fresh_client()
    root = client.get("/sale/")
    assert root.status_code == 302
    assert root.headers["Location"].endswith("/sale/pricelist")
    assert client.get("/sale/pricelist").status_code == 200


def test_settings_needs_no_login():
    assert fresh_client().get("/settings/").status_code == 200


def test_unknown_module_prefix_404s():
    # the Dispatcher only mounts the six known prefixes
    assert fresh_client().get("/nope/").status_code == 404
