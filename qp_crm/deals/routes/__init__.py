"""Deals route groups (Phase 4 stage layout, mirrors offer/admin).

Importing this package registers every route group on deals.app's
blueprint. Split per domain, P2-stage-5 style: customers, locations,
deals (list/thread), pipeline.
"""
from . import customers, deals, pipeline  # noqa: F401
