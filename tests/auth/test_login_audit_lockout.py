"""Phase 3 step 8: login audit log, in-process lockout, session timeout.

Pinned behavior:

* every login attempt writes one login_audit row (ts, username, ip,
  success, detail) -- successes AND failures;
* after LOGIN_MAX_FAILURES (5) bad passwords within the sliding window for
  the same (ip, username), further attempts are REFUSED without checking
  the password (lockout message, no user-enumeration leak);
* a successful login clears the failure counter for that pair;
* the failure state is in-process (no Redis, no extra service) and does
  not leak across (ip, username) pairs;
* login marks the session permanent and the app config carries an 8h
  PERMANENT_SESSION_LIFETIME with SESSION_REFRESH_EACH_REQUEST.
"""

import pytest

from conftest import csrf_token_for
from qp_crm.main import app
from qp_crm.shared import auth as shared_auth


@pytest.fixture(scope="module", autouse=True)
def _initialized_db(temp_db):
    yield


@pytest.fixture()
def client():
    c = app.test_client()
    c.get("/login")  # establish the session CSRF token
    with c.session_transaction() as session:
        session["_csrf_token"] = session.get("_csrf_token") or "tok"
    return c


def _post_login(client, username, password):
    return client.post("/login", data={
        "username": username,
        "password": password,
        "_csrf_token": csrf_token_for(client),
    })


def _last_audit():
    conn = shared_auth.get_db()
    row = conn.execute("SELECT * FROM login_audit ORDER BY id DESC LIMIT 1;").fetchone()
    conn.close()
    return row


@pytest.fixture(autouse=True)
def _isolate_lockout_state():
    """Fresh failure counters per test (shared module dict!)."""
    shared_auth._login_failures.clear()
    yield
    shared_auth._login_failures.clear()


def test_successful_login_audited(client):
    resp = _post_login(client, "pricing", shared_auth.DEFAULT_PASSWORDS["pricing"])
    assert resp.status_code == 302
    row = _last_audit()
    assert row["username"] == "pricing"
    assert row["success"] == 1
    assert row["detail"] == "ok"
    assert row["ip"]  # werkzeug test client sends 127.0.0.1


def test_failed_login_audited(client):
    resp = _post_login(client, "pricing", "definitely-wrong-1")
    assert resp.status_code == 200
    row = _last_audit()
    assert row["username"] == "pricing"
    assert row["success"] == 0
    assert "bad credentials" in row["detail"]


def test_lockout_after_max_failures(client):
    for _ in range(shared_auth.LOGIN_MAX_FAILURES):
        resp = _post_login(client, "offer", "wrong-password-1")
        assert resp.status_code == 200

    # next attempt: locked out BEFORE password checking -- even the CORRECT
    # password is refused while locked
    resp = _post_login(client, "offer", shared_auth.DEFAULT_PASSWORDS["offer"])
    assert resp.status_code == 200
    # the lockout message is translated at request time: the test DB has no
    # language row, so it renders in the en default (sr mode is pinned by the
    # smoke suite's i18n checks, where the same phrase appears in Serbian)
    assert "Too many failed login attempts" in resp.data.decode()
    row = _last_audit()
    assert row["success"] == 0 and "lockout" in row["detail"]

    # ...and the correct password did NOT log the user in
    with client.session_transaction() as session:
        assert not session.get("user_id")


def test_lockout_resets_on_success_and_is_pair_scoped(client):
    for _ in range(shared_auth.LOGIN_MAX_FAILURES - 1):
        _post_login(client, "rent", "wrong-password-1")
    # a DIFFERENT pair (same user, other IP / other user, same IP) is free
    assert shared_auth.is_login_locked("rent", "1.2.3.4")[0] is False
    assert shared_auth.is_login_locked("pricing", "127.0.0.1")[0] is False

    # successful login clears the counter
    resp = _post_login(client, "rent", shared_auth.DEFAULT_PASSWORDS["rent"])
    assert resp.status_code == 302
    assert shared_auth.is_login_locked("rent", "127.0.0.1") == (False, 0)


def test_lockout_service_layer_window_expiry():
    shared_auth._login_failures.clear()
    key = ("10.0.0.9", "locktest")
    # simulate failures that are JUST inside the window
    import time
    now = time.time()
    shared_auth._login_failures[key] = [
        now - shared_auth.LOGIN_WINDOW_SECONDS + 5
    ] * shared_auth.LOGIN_MAX_FAILURES
    locked, remaining = shared_auth.is_login_locked("locktest", "10.0.0.9")
    assert locked is True and 0 < remaining <= 5

    # after the window passes, the stale entries are pruned -> unlocked
    shared_auth._login_failures[key] = [
        now - shared_auth.LOGIN_WINDOW_SECONDS - 1
    ] * shared_auth.LOGIN_MAX_FAILURES
    locked, _ = shared_auth.is_login_locked("locktest", "10.0.0.9")
    assert locked is False
    shared_auth._login_failures.clear()


def test_session_timeout_configuration():
    from datetime import timedelta
    assert app.config["PERMANENT_SESSION_LIFETIME"] == timedelta(hours=8)
    assert app.config["SESSION_REFRESH_EACH_REQUEST"] is True


def test_login_marks_session_permanent(client):
    resp = _post_login(client, "pricing", shared_auth.DEFAULT_PASSWORDS["pricing"])
    assert resp.status_code == 302
    with client.session_transaction() as session:
        assert session.permanent is True
        assert session.get("user_id")
