"""Admin -> About tab: software version + runtime info.

Pins the About contract (user request, board card):

* GET /admin/about renders (200, admin-gated like every admin page) and
  shows the software version from APP_VERSION (shared/config.py — the
  single source of truth, bumped with every release tag);
* the build commit comes from QP_BUILD_COMMIT (injected by CI as a
  Dockerfile build arg); when absent (bare-metal/dev run) the page says
  "dev build" instead of showing an empty value;
* the running image tag is read from backups/last-deployed-tag — the
  record deploy.sh writes at deploy time; absent on dev runs;
* the nav has the About link on every admin page (eight links now);
* data-at-a-glance counts render without crashing on a fresh DB.
"""

import os

import pytest

from qp_crm.shared import config
from qp_crm.shared.config import BACKUP_DIR


@pytest.fixture()
def clean_backup_dir():
    """Empty BACKUP_DIR for the deploy-record tests (same pattern as
    test_backup_tab.py)."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for n in os.listdir(BACKUP_DIR):
        os.remove(os.path.join(BACKUP_DIR, n))
    yield BACKUP_DIR
    for n in os.listdir(BACKUP_DIR):
        try:
            os.remove(os.path.join(BACKUP_DIR, n))
        except OSError:
            pass


def test_about_page_shows_version(admin_client):
    page = admin_client.get("/admin/about")
    assert page.status_code == 200
    html = page.data.decode()
    # version from the single source of truth
    assert f"v{config.APP_VERSION}" in html


def test_about_page_dev_build_without_commit_env(admin_client, monkeypatch):
    """No QP_BUILD_COMMIT (bare-metal/dev) -> honest 'dev build' label."""
    monkeypatch.setattr(config, "APP_BUILD_COMMIT", "")
    page = admin_client.get("/admin/about")
    html = page.data.decode()
    assert "dev build" in html


def test_about_page_shows_build_commit_and_image_tag(admin_client, monkeypatch,
                                                     clean_backup_dir):
    """CI-injected commit + deploy.sh's last-deployed-tag are both shown."""
    monkeypatch.setattr(config, "APP_BUILD_COMMIT", "abcdef1234567890")
    with open(f"{clean_backup_dir}/last-deployed-tag", "w") as f:
        f.write("ghcr.io/lakisan1/qp-crm:sha-abcdef1234567890\n")

    page = admin_client.get("/admin/about")
    assert page.status_code == 200
    html = page.data.decode()
    assert "abcdef1234567890"[:12] in html          # short commit shown
    assert "ghcr.io/lakisan1/qp-crm:sha-abcdef1234567890" in html


def test_about_page_tolerates_missing_deploy_record(admin_client,
                                                    clean_backup_dir):
    """No last-deployed-tag file -> muted note, not a crash."""
    page = admin_client.get("/admin/about")
    assert page.status_code == 200
    assert "bare-metal / local run" in page.data.decode()


def test_about_counts_render_on_fresh_db(admin_client):
    """Data-at-a-glance numbers render even when a table is missing."""
    page = admin_client.get("/admin/about")
    assert page.status_code == 200
    html = page.data.decode()
    for label in ("Users", "Products", "Offers", "Rent contracts", "Contacts"):
        assert label in html


def test_nav_has_about_link_on_admin_pages(admin_client):
    """The shared header now carries eight links, About last."""
    for url in ("/admin/", "/admin/backup", "/admin/users"):
        html = admin_client.get(url).data.decode()
        assert ">About</a>" in html


def test_about_requires_admin(temp_db):
    """Like every admin page: unauthenticated -> redirect to login."""
    from qp_crm.main import app
    resp = app.test_client().get("/admin/about", follow_redirects=False)
    assert resp.status_code == 302
