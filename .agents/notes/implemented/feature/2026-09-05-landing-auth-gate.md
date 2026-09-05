# Agent Note: landing-auth-gate

Status: implemented

## Problem

The landing page (main.py index) was static and public: anonymous LAN visitors saw the full app menu including the Admin Panel card, contradicting the unified-login model and the per-user app access feature.

## Decision

main.py index() redirects anonymous requests to auth.login (session.clear on a stale user_id) and renders landing.html with is_admin + granted (MODULE_CHOICES for admins, get_user_modules for staff). templates/landing.html wraps the pricing/offer/rent cards in is_admin-or-granted conditionals and the Admin Panel card in is_admin; sale/settings stay public so their cards render for every logged-in user. Smoke tests pin the anonymous 302 and both menu variants (tests/smoke/test_smoke_modules.py). Not covered: the change-password flow does not intercept '/' for must_change users (module gates still force it when they click any app).
## Alternatives considered

JS-only menu hiding rejected: the server must not render links the user cannot open. App-level before_request auth for '/' rejected: heavier than a one-line route guard and sale/settings must stay reachable.
## Consequences

Bought: no information leak to anonymous users and a menu consistent with grants (unchecking an app also removes its card on the next request). Cost: one smoke test changed contract (landing 200 -> 302) and the menu template now depends on the granted variable — any new app card must add its own conditional.

