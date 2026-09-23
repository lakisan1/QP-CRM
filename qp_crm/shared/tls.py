"""TLS / reverse-proxy posture (user decision: nginx fronts the app).

The app itself always listens on its own port (5000). When it sits behind
an nginx TLS proxy on the public side, the container is started with two
optional env vars (see .env.example / docker-compose.yml):

* QP_HTTPS_ONLY=1 — the app is behind the TLS proxy:
    - the WSGI app is wrapped in werkzeug ProxyFix (x_for, x_proto), so
      request.scheme / request.remote_addr honor nginx's X-Forwarded-*;
    - the qp_session cookie is marked Secure (only sent over https);
    - PREFERRED_URL_SCHEME is "https", so any absolute URL the app builds
      (e.g. url_for(..., _external=True)) is https;
    - responses served over https carry Strict-Transport-Security
      (max-age=1y, no includeSubDomains — deliberately conservative).
  Default (0 / unset) keeps today's plain-HTTP LAN behavior exactly.
* QP_PUBLIC_DOMAIN — the public domain nginx fronts (e.g. crm.example.com).
  Stored as app.config["PUBLIC_DOMAIN"] for metadata/templates; it MUST
  match nginx `server_name`. Optional; no effect when empty.

Both are read at import/apply time, which keeps the default path
(no env vars) byte-for-byte identical to the pre-TLS behavior.
"""

import os

from flask import request

ENV_HTTPS_ONLY = "QP_HTTPS_ONLY"
ENV_PUBLIC_DOMAIN = "QP_PUBLIC_DOMAIN"


def is_https_only():
    return os.environ.get(ENV_HTTPS_ONLY, "0") == "1"


def public_domain():
    return os.environ.get(ENV_PUBLIC_DOMAIN, "").strip() or None


def configure_app(app):
    """Apply https-only / domain settings to the Flask app. Call once at
    import time (qp_crm/main.py) before the app is served."""
    https_only = is_https_only()
    domain = public_domain()

    if https_only:
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["PREFERRED_URL_SCHEME"] = "https"
    if domain:
        app.config["PUBLIC_DOMAIN"] = domain

    if https_only or domain:

        @app.after_request
        def _tls_headers(resp):
            # HSTS only over real https (request.scheme is https behind
            # ProxyFix when nginx sets X-Forwarded-Proto). No
            # includeSubDomains: the operator's domain may host other
            # services that are still plain http.
            if https_only and request.scheme == "https":
                resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
            return resp

    if domain:
        print(f"TLS: public domain '{domain}' (nginx server_name must match).", flush=True)
    if https_only:
        print("TLS: QP_HTTPS_ONLY=1 — Secure session cookie, https scheme, ProxyFix active.", flush=True)
    return app


def wrap_wsgi(application):
    """Wrap the WSGI application in ProxyFix when QP_HTTPS_ONLY=1.

    Returns the original callable unchanged otherwise, so the default
    deployment is untouched. ProxyFix is the OUTERMOST layer: nginx headers
    are consumed before Flask sees the request.
    """
    if is_https_only():
        from werkzeug.middleware.proxy_fix import ProxyFix

        return ProxyFix(application, x_for=1, x_proto=1)
    return application
