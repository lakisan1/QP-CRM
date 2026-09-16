"""Pipeline route (Phase 4): the read-only board over derived statuses."""
from flask import render_template

from ..app import bp
from qp_crm.services import deal_service
from .deals import STATUS_LABELS


@bp.route("/pipeline")
def pipeline():
    board = deal_service.pipeline_board()
    return render_template(
        "deals/pipeline.html",
        board=board,
        status_labels=STATUS_LABELS,
    )
