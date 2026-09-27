"""Warehouse route groups (P5 layout).

Importing this package registers every route group on warehouse.app's
blueprint. Split per domain, P2-stage-5 style.
"""
from . import coverage, equipment, movements, shortfalls  # noqa: F401
