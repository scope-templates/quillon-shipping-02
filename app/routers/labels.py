"""Serving the label PDF. No key on the link: warehouse printers cannot set a header."""

import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app import labels
from app.billing import subscription_for
from app.db import get_conn
from app.errors import QuillonError
from app.ids import now, read_stamp
from app.plans import PLANS
from app.schemas import problem_responses

router = APIRouter(tags=["Labels"])


@router.get(
    "/labels/{token}.pdf",
    summary="The label PDF behind the link",
    operation_id="get_label_pdf",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The label, ready to print."},
        **problem_responses("not_found", authenticated=False),
    },
)
def label_pdf(token: str, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = conn.execute(
        "SELECT s.*, c.name AS carrier_name, k.label_logo FROM shipments s "
        "JOIN carriers c ON c.code = s.carrier_code "
        "JOIN customers k ON k.id = s.customer_id WHERE s.label_token = ?",
        (token,),
    ).fetchone()
    if row is None or not row["label_expires_at"]:
        raise QuillonError("not_found", "That label link is not one of ours.")
    if read_stamp(row["label_expires_at"]) <= now():
        raise QuillonError(
            "not_found",
            "That label link has run out. Ask for the label again to get a fresh one.",
        )
    shipment = dict(row)
    plan = subscription_for(conn, shipment["customer_id"])["plan"]
    logo = shipment["label_logo"] if PLANS[plan]["logo_on_label"] else None
    return Response(
        content=labels.pdf_bytes(shipment, shipment["carrier_name"], logo),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{shipment["tracking_number"]}.pdf"'
        },
    )
