"""Contacts route groups (P5-pre layout).

Importing this package registers every route group on contacts.app's
blueprint. Split per domain, P2-stage-5 style: directory (list/detail/
form/archive/locations).
"""
from . import directory  # noqa: F401
