# Agent Note: user-save-combined-sale-module

Status: implemented

## Problem

Admin -> Users had grown four independent password-confirmed actions per row (deactivate, role change, password reset, app access), each with its own 'Your password' field and button — cluttered and error-prone. Meanwhile the sale app remained public read-only, inconsistent with the per-user access model.

## Decision

One combined save route POST /admin/users/<id>/save applies, in order: active checkbox, role select, module checkboxes, and — only when filled — a password reset, each through its existing service guard; errors flash while remaining changes still apply. The row UI is ONE <form id=user-form-<id>> in the first cell with all inputs in other cells joined via the HTML5 form= attribute (a form cannot span table cells). Checkbox semantics are the contract: an absent 'active'/'modules' field means unchecked — callers that don't mirror the form will deactivate/wipe, which the test suite now mirrors explicitly. get_user_by_id grew include_inactive=False (default keeps the Phase-3 contract for session guards); the save route passes True so deactivated users can be re-saved. Sale became MODULE_CHOICES' fourth entry with a versioned rollout: MODULE_INTRODUCED maps module -> introducing seed version, users.modules_set now stores the LAST SEED VERSION seen (0=never, 1=v1, 2=v2), and seed_default_user_modules grants only modules with MODULE_INTRODUCED[m] > row version — so sale reached existing staff exactly once while deliberately revoked older grants stay revoked. Sale blueprint runs require_module('sale') and gained legacy /sale/login + /sale/logout redirects mirroring pricing/offer/rent.
## Alternatives considered

One giant form per row via table-restructuring (single <td> card layout) — lost to the form= attribute, which keeps the table layout; re-running the full all-modules seed on version bump — rejected because it would resurrect explicitly revoked grants; leaving sale public and only adding a checkbox — rejected as incoherent (a checkbox that changes nothing).
## Consequences

Bought: a single confirmation per user, sale under the same least-privilege model, and a repeatable pattern for future module rollouts (append to MODULE_CHOICES + MODULE_INTRODUCED, bump CURRENT_MODULE_VERSION). Cost: tests that POST the save route must mirror the real form's checkboxes or they wipe grants/deactivate (pinned in test_user_management/test_module_access); the bare-schema characterization test now expects the login redirect for anonymous /sale/pricelist (the gate runs before route logic); anonymous access to sale is gone — bookmarks to /sale/pricelist land on /login.

