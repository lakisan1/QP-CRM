"""TLS / reverse-proxy env config (user decision: nginx fronts the app).

QP_HTTPS_ONLY=1  -> Secure qp_session cookie, PREFERRED_URL_SCHEME=https,
                    werkzeug ProxyFix wrapping, HSTS on https responses.
QP_PUBLIC_DOMAIN -> stored as app.config['PUBLIC_DOMAIN'] (must match nginx
                    server_name).
Defaults (unset / 0 / empty) leave the app byte-for-byte unchanged —
wrap_wsgi returns the original callable and no cookie/HSTS flags are set.
"""

from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.test import Client

from qp_crm.shared.tls import (
    ENV_HTTPS_ONLY,
    ENV_PUBLIC_DOMAIN,
    configure_app,
    is_https_only,
    public_domain,
    wrap_wsgi,
)


def _fresh_app():
    from flask import Flask, session

    app = Flask(__name__)
    app.secret_key = "test-secret"

    @app.route("/")
    def ok():
        return "ok"

    @app.route("/touch-session")
    def touch():
        session["touched"] = True
        return "ok"

    return app


def test_defaults_leave_app_unchanged(monkeypatch):
    monkeypatch.delenv(ENV_HTTPS_ONLY, raising=False)
    monkeypatch.delenv(ENV_PUBLIC_DOMAIN, raising=False)
    assert is_https_only() is False
    assert public_domain() is None

    app = _fresh_app()
    configure_app(app)
    assert app.config.get("SESSION_COOKIE_SECURE") is not True
    assert app.config.get("PREFERRED_URL_SCHEME") != "https"
    assert "PUBLIC_DOMAIN" not in app.config
    assert wrap_wsgi(app) is app  # identity: no ProxyFix in default mode


def test_https_only_sets_secure_cookie_and_https_scheme(monkeypatch):
    monkeypatch.setenv(ENV_HTTPS_ONLY, "1")
    monkeypatch.delenv(ENV_PUBLIC_DOMAIN, raising=False)
    app = _fresh_app()
    configure_app(app)
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["PREFERRED_URL_SCHEME"] == "https"
    assert "PUBLIC_DOMAIN" not in app.config
    wrapped = wrap_wsgi(app)
    assert isinstance(wrapped, ProxyFix)  # x_for/x_proto trust enabled


def test_public_domain_is_stored(monkeypatch):
    monkeypatch.setenv(ENV_PUBLIC_DOMAIN, "crm.example.com")
    app = _fresh_app()
    configure_app(app)
    assert app.config["PUBLIC_DOMAIN"] == "crm.example.com"
    assert public_domain() == "crm.example.com"


def test_hsts_and_secure_cookie_serve_over_proxy_https(monkeypatch):
    monkeypatch.setenv(ENV_HTTPS_ONLY, "1")
    wrapped = wrap_wsgi(configure_app(_fresh_app()))

    client = Client(wrapped)
    resp = client.get("/touch-session", headers={"X-Forwarded-Proto": "https"})

    assert resp.headers.get("Strict-Transport-Security") == "max-age=31536000"
    cookies = resp.headers.getlist("Set-Cookie")
    assert cookies, "expected a session cookie"
    assert all("Secure" in c for c in cookies)


def test_no_hsts_over_plain_http_even_when_https_only(monkeypatch):
    monkeypatch.setenv(ENV_HTTPS_ONLY, "1")
    wrapped = wrap_wsgi(configure_app(_fresh_app()))

    client = Client(wrapped)
    # No X-Forwarded-Proto: ProxyFix has nothing to trust -> scheme stays
    # http -> HSTS must NOT be emitted (http responses must not promise HSTS).
    resp = client.get("/")
    assert resp.headers.get("Strict-Transport-Security") is None


def test_hsts_never_sent_when_https_only_off(monkeypatch):
    monkeypatch.delenv(ENV_HTTPS_ONLY, raising=False)
    wrapped = wrap_wsgi(configure_app(_fresh_app()))  # identity wrap

    client = Client(wrapped)
    resp = client.get("/", headers={"X-Forwarded-Proto": "https"})
    # ProxyFix is NOT active in default mode, so even a forged
    # X-Forwarded-Proto header cannot flip the scheme -> no HSTS.
    assert resp.headers.get("Strict-Transport-Security") is None
