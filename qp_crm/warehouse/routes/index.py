"""Warehouse index route: /warehouse/ -> the equipment registry.

Every module on the single app exposes a module-root redirect so the
landing page's app-card href (<prefix>/) works (pricing, contacts, offer
all do this via their own index()). Warehouse was built without one, so
hitting /warehouse/ directly (the landing card, or a typed URL) 404'd.
"""
from flask import redirect, url_for

from ..app import bp


@bp.route("/")
def index():
    return redirect(url_for("warehouse.equipment_list"))
