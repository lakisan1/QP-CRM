"""QP-CRM service layer (Phase 2 stage 4).

Business logic lives here, route modules keep HTTP concerns. Functions are
moved verbatim from the route modules they serve (zero behavior change);
the route modules import them back so their own call sites stay untouched.
"""

from qp_crm.services import offer_service, pdf_service, pricing_service, rent_service  # noqa: F401
