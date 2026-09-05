"""Phase 3 step 4: role gates per module.

Pinned behavior:

* admin blueprint (including the sandboxed PDF-template editor) is
  'admin'-only -- staff get 403;
* pricing / offer / rent accept 'staff' AND 'admin' (admin is the superset
  role and may open every business module);
* sale, settings and /api/v1/health stay public;
* anonymous users are redirected to the unified login on all gated modules;
* a user deactivated or demoted while logged in loses/restricts access on
  their next request (require_role re-reads the user row every request).
"""

import pytest

from conftest import login_client
from qp_crm.main import app
from qp_crm.shared.auth import get_db

GATED_MODULES = ("pricing", "offer", "rent", "sale", "admin")
BUSINESS_PAGES = {
    "pricing": "/pricing/products",
    "offer": "/offer/offers",
    "rent": "/rent/contracts",
    "sale": "/sale/pricelist",
}


def test_admin_reaches_admin_panel(admin_client):
    assert admin_client.get("/admin/").status_code == 200


@pytest.mark.parametrize("path", BUSINESS_PAGES.values())
def test_admin_is_superset_role(admin_client, path):
    # 'admin' may open every business module.
    assert admin_client.get(path).status_code == 200


@pytest.mark.parametrize("path", BUSINESS_PAGES.values())
def test_staff_reaches_business_modules(offer_client, path):
    # offer_client logs in as the seeded 'offer' staff account.
    assert offer_client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/admin/", "/admin/pdf_templates", "/admin/edit_pdf_template/1"])
def test_staff_blocked_from_admin_blueprint(admin_client, offer_client, path):
    # The SAME request path: 200 for admin, 403 for staff -- this is what
    # makes the sandboxed PDF-template editor admin-only (audit C4 surface).
    assert admin_client.get(path).status_code == 200
    assert offer_client.get(path).status_code == 403


@pytest.mark.parametrize("module", GATED_MODULES)
def test_anonymous_redirects_to_unified_login(module):
    client = app.test_client()
    resp = client.get(f"/{module}/")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login")


@pytest.mark.parametrize("path", ["/settings/", "/api/v1/health"])
def test_public_routes_stay_public(path):
    # sale left the public list in the v2 module rollout: it is now a
    # per-user grant (test_anonymous_redirects_to_unified_login covers its
    # login redirect; test_staff_reaches_business_modules the granted 200).
    client = app.test_client()
    assert client.get(path).status_code == 200


def test_deactivated_user_loses_access_immediately():
    client = login_client(app.test_client(), "pricing")
    assert client.get("/pricing/products").status_code == 200

    conn = get_db()
    conn.execute("UPDATE users SET is_active = 0 WHERE username = 'pricing';")
    conn.commit()
    conn.close()

    # Next request: session killed, back to the login page.
    resp = client.get("/pricing/products")
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/login")

    # Restore for the rest of the suite.
    conn = get_db()
    conn.execute("UPDATE users SET is_active = 1 WHERE username = 'pricing';")
    conn.commit()
    conn.close()


def test_role_change_takes_effect_while_logged_in():
    """Since per-user app access, the role gate is binary: 'admin' opens
    everything, ANY other role falls through to the module grants. A role
    change therefore hits the admin panel immediately, while business-module
    access follows the grants, not the role name."""
    client = login_client(app.test_client(), "pricing")
    conn = get_db()
    conn.execute("UPDATE users SET role = 'staff' WHERE username = 'pricing';")
    conn.commit()
    conn.close()
    assert client.get("/pricing/products").status_code == 200  # granted staff
    assert client.get("/admin/").status_code == 403

    # role renamed to something else while logged in: business access is
    # unchanged (grants decide), admin panel still closed
    conn = get_db()
    conn.execute("UPDATE users SET role = 'viewer' WHERE username = 'pricing';")
    conn.commit()
    conn.close()
    assert client.get("/pricing/products").status_code == 200
    assert client.get("/admin/").status_code == 403

    # promote to admin while logged in: admin panel opens on the next request
    conn = get_db()
    conn.execute("UPDATE users SET role = 'admin' WHERE username = 'pricing';")
    conn.commit()
    conn.close()
    assert client.get("/admin/").status_code == 200

    # restore the seeded role
    conn = get_db()
    conn.execute("UPDATE users SET role = 'staff' WHERE username = 'pricing';")
    conn.commit()
    conn.close()
