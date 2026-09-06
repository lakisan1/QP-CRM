"""PWA smoke tests: web app manifest + static-only service worker.

Board card: make the FEATURES.md PWA claim real. These tests pin the
contract, all served from the REAL repo static/ directory (conftest patches
APP_ASSETS_DIR/APP_DATA_DIR but NOT STATIC_DIR):

* /static/manifest.webmanifest is served with the standard
  application/manifest+json content type and carries the installability
  fields (name, start_url, standalone display, 192/512 icons that resolve).
* /static/sw.js is served as JavaScript and encodes the static-only rule
  (versioned qp-crm-static-* cache, no interception of non-GET requests).
* The logged-in landing page links the manifest and embeds the
  secure-context-gated service worker registration snippet.
"""

import json

import pytest

import qp_crm.main
from conftest import login_client


@pytest.fixture(scope="module", autouse=True)
def _db_ready(temp_db):
    """Guarantee the init sequence ran, even in a smoke-only run (see
    test_smoke_modules._initialized_db for the discovery behind this)."""
    yield


def fresh_client():
    """A clean cookie jar -- no session (same helper as the other smokes)."""
    return qp_crm.main.app.test_client()


def test_manifest_served_with_manifest_content_type():
    response = fresh_client().get("/static/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/manifest+json"
    manifest = json.loads(response.data.decode())
    assert manifest["name"] == "QP-CRM"
    assert manifest["short_name"] == "QP-CRM"
    assert manifest["start_url"] == "/"
    assert manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["background_color"] and manifest["theme_color"]
    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}
    assert all(icon["type"] == "image/png" for icon in manifest["icons"])


def test_manifest_icons_resolve_to_pngs():
    manifest = json.loads(fresh_client().get("/static/manifest.webmanifest").data.decode())
    for icon in manifest["icons"]:
        response = fresh_client().get(icon["src"])
        assert response.status_code == 200, icon["src"]
        assert response.headers["Content-Type"] == "image/png", icon["src"]
        assert len(response.data) > 0


def test_service_worker_served_as_javascript_with_static_only_contract():
    response = fresh_client().get("/static/sw.js")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/javascript")
    body = response.data.decode()
    # the static-only caching contract is encoded in the worker itself:
    assert "qp-crm-static-" in body                    # versioned cache name
    assert "request.method !== 'GET'" in body          # writes never intercepted
    assert "indexOf('/static/') === 0" in body         # only /static is cached
    assert "self.clients.claim" in body or "clients.claim" in body


def test_landing_page_links_manifest_and_registers_sw_after_login():
    # anonymous "/" redirects to the unified login; assert on the real
    # post-login landing page instead
    client = login_client(fresh_client(), "pricing")
    page = client.get("/").data.decode()
    assert '<link rel="manifest" href="/static/manifest.webmanifest">' in page
    assert 'name="theme-color" content="#2d2d2d"' in page
    assert "'serviceWorker' in navigator" in page
    assert "window.isSecureContext" in page
    assert "navigator.serviceWorker.register('/static/sw.js', { scope: '/' })" in page
