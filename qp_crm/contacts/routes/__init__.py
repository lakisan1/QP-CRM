"""Contacts route groups (P5-pre layout, mirrors deals/routes).

Importing this package registers every route group on contacts.app's
blueprint. Split per domain, P2-stage-5 style: directory (list/detail/
form/archive), links (contact ↔ customer/location links).
"""
from . import directory, links  # noqa: F401
