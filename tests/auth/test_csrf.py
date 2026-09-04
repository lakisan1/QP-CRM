"""Phase 3 step 5: CSRF on ALL state-changing routes across all blueprints.

The settings app's per-session token pattern is generalized into
shared/web.py (csrf_token + check_csrf) and wired ONCE at the app level:
every POST/PUT/PATCH/DELETE on every blueprint must carry the session token
(form field or X-CSRF-Token header). api_v1 is exempt -- it authenticates
via the Authorization: Bearer header, not ambient cookies, so cross-site
form posts cannot ride an authenticated session there.

Pinned here:

* every server-rendered POST form in every template carries the hidden
  token (permanent inventory guard over all templates);
* POST without a token / with a bad token is rejected 400 on EVERY
  blueprint (anonymous: auth + settings; session-gated: pricing, offer,
  rent, admin);
* a valid token lets the request through (no CSRF-mismatch 400);
* api_v1 POSTs work WITHOUT any CSRF token when Bearer-authenticated.
"""

import pathlib
import re

import pytest

from conftest import login_client
from qp_crm.main import app
from qp_crm.shared.auth import generate_api_key


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    """These are the alphabetically FIRST DB-touching tests in the suite:
    guarantee the seeded schema (users table!) exists before any route runs."""
    yield

# A representative state-changing endpoint per blueprint.
STATE_CHANGING = {
    "auth": "/login",
    "settings": "/settings/",
    "pricing": "/pricing/products/add",
    "offer": "/offer/offers/new",
    "rent": "/rent/contracts/new",
    "admin": "/admin/update_settings",
}

FORM_RE = re.compile(r"<form\b[^>]*>", re.I | re.S)
METHOD_POST_RE = re.compile(r"method\s*=\s*[\"']post[\"']", re.I)


def _session_token(client):
    with client.session_transaction() as session:
        return session.get("_csrf_token")


def _client_for(path):
    client = app.test_client()
    if path == "/pricing/products/add":
        login_client(client, "pricing")
    elif path == "/offer/offers/new":
        login_client(client, "offer")
    elif path == "/rent/contracts/new":
        login_client(client, "rent")
    elif path == "/admin/update_settings":
        login_client(client, "admin")
    return client


# ---------------------------------------------------------------- inventory

def test_every_post_form_in_every_template_carries_the_token():
    """The card's inventory, turned into a permanent guard: any POST form
    added later without {{ csrf_token() }} fails the suite."""
    roots = [pathlib.Path("qp_crm"), pathlib.Path("templates")]
    checked = 0
    for root in roots:
        for p in root.rglob("*.html"):
            text = p.read_text(encoding="utf-8")
            for m in FORM_RE.finditer(text):
                if not METHOD_POST_RE.search(m.group(0)):
                    continue
                end = text.find("</form", m.end())
                segment = text[m.end():end if end != -1 else len(text)]
                assert "_csrf_token" in segment, (
                    f"{p}: POST form without CSRF token: {m.group(0)[:80]}"
                )
                checked += 1
    assert checked >= 50  # the Phase-3 baseline inventory (54 forms)


# ---------------------------------------------------------------- negatives

@pytest.mark.parametrize("path", STATE_CHANGING.values(), ids=list(STATE_CHANGING))
def test_post_without_token_rejected_everywhere(path):
    resp = _client_for(path).post(path, data={})
    assert resp.status_code == 400
    assert b"CSRF token mismatch" in resp.data


@pytest.mark.parametrize("path", STATE_CHANGING.values(), ids=list(STATE_CHANGING))
def test_post_with_bad_token_rejected_everywhere(path):
    resp = _client_for(path).post(path, data={"_csrf_token": "forged-token-000"})
    assert resp.status_code == 400
    assert b"CSRF token mismatch" in resp.data


# ----------------------------------------------------------------- positives

def test_post_with_valid_token_passes_auth_login():
    client = app.test_client()
    client.get("/login")
    token = _session_token(client)
    assert token
    resp = client.post(
        "/login",
        data={"username": "admin", "password": "Admin1", "_csrf_token": token},
    )
    assert resp.status_code == 302  # logged in -- CSRF did not block


def test_post_with_valid_token_passes_settings():
    client = app.test_client()
    client.get("/settings/")
    token = _session_token(client)
    resp = client.post(
        "/settings/",
        data={"theme": "dark", "date_format": "YYYY-MM-DD", "_csrf_token": token},
    )
    assert resp.status_code == 302  # settings saved, redirected to landing


def test_post_with_valid_token_passes_gated_blueprint():
    client = login_client(app.test_client(), "pricing")
    client.get("/pricing/products/add")
    token = _session_token(client)
    resp = client.post(
        "/pricing/products/add",
        data={"name": "CSRF Probe Product", "_csrf_token": token},
    )
    # The handler ran (created / redirected / validation) -- the important
    # pin is that the CSRF layer did NOT reject it.
    assert b"CSRF token mismatch" not in resp.data


def test_csrf_token_accepted_via_header():
    client = login_client(app.test_client(), "rent")
    client.get("/rent/contracts/new")
    token = _session_token(client)
    resp = client.post(
        "/rent/contracts/new",
        data={},
        headers={"X-CSRF-Token": token},
    )
    assert b"CSRF token mismatch" not in resp.data


def test_api_v1_exempt_from_csrf():
    # Bearer-authenticated POST without any CSRF token must reach the handler.
    key = generate_api_key()
    client = app.test_client()
    resp = client.post(
        "/api/v1/products",
        json={"name": "CSRF Exempt Probe"},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert resp.status_code == 201
    assert b"CSRF token mismatch" not in resp.data

    # Unauthenticated API POST is rejected by the KEY layer (401), not CSRF.
    resp = client.post("/api/v1/products", json={"name": "x"})
    assert resp.status_code == 401


def test_get_requests_unaffected():
    client = app.test_client()
    assert client.get("/login").status_code == 200
    assert client.get("/settings/").status_code == 200
