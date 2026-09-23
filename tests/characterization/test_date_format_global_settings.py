"""M4 characterization: the GLOBAL date format has ONE source of truth.

audit M4 found date_format split between the global_settings DB row
(written by the admin dashboard) and a per-browser 'date_format' cookie
(settings app), so one browser could silently render dates differently
from the rest of the company -- golden/PDF output must be
company-consistent. Fix: the cookie path is gone; get_date_format() reads
ONLY global_settings (default 'YYYY-MM-DD' when the row is missing, empty
or unreadable).

Pinned precedence (post-fix contract):

* global_settings.date_format row set  -> that format wins; a stale
  per-browser 'date_format' cookie is IGNORED;
* row missing or empty                 -> 'YYYY-MM-DD'; the cookie is STILL
  ignored (no per-browser fallback exists anymore).

The suite DB is session-scoped and shared, so each test snapshots and
restores the row it mutates (schema.py seeds 'YYYY-MM-DD').
"""

import pytest

from qp_crm.main import app
from qp_crm.shared.web import get_date_format


def _read_date_format(conn_factory):
    with conn_factory() as conn:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'date_format';"
        ).fetchone()
        return row["value"] if row else None


def _write_date_format(conn_factory, value):
    """value None deletes the row (no global setting); else INSERT OR REPLACE."""
    with conn_factory() as conn:
        if value is None:
            conn.execute("DELETE FROM global_settings WHERE key = 'date_format';")
        else:
            conn.execute(
                "INSERT OR REPLACE INTO global_settings (key, value) VALUES ('date_format', ?);",
                (value,),
            )


@pytest.fixture(autouse=True)
def _restore_date_format_row(conn_factory):
    """Keep the shared suite DB deterministic: snapshot the row before each
    test and restore it after, whatever the test does to it."""
    original = _read_date_format(conn_factory)
    yield
    _write_date_format(conn_factory, original)


def _get_format_with_stale_cookie():
    """get_date_format() as seen by a request whose browser still carries a
    stale 'date_format' cookie (MM/DD/YYYY). Before M4 that cookie was the
    fallback source; now it must never influence the result."""
    with app.test_request_context(
        "/", environ_overrides={"HTTP_COOKIE": "theme=dark; date_format=MM/DD/YYYY"}
    ):
        return get_date_format()


def test_global_setting_wins_over_stale_cookie(conn_factory):
    _write_date_format(conn_factory, "DD/MM/YYYY")
    assert _get_format_with_stale_cookie() == "DD/MM/YYYY"


def test_default_when_no_db_row_cookie_ignored(conn_factory):
    _write_date_format(conn_factory, None)
    assert _get_format_with_stale_cookie() == "YYYY-MM-DD"


def test_default_when_db_row_empty_cookie_ignored(conn_factory):
    _write_date_format(conn_factory, "")
    assert _get_format_with_stale_cookie() == "YYYY-MM-DD"
