"""Shipments: booking one, reading it back, the label, the cancel and the tracking."""

import json
import os
import sqlite3
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from app import idempotency, labels, tracking, webhooks
from app.auth import Caller, caller
from app.db import get_conn
from app.errors import QuillonError
from app.ids import new_id, now_stamp, read_stamp, tracking_number
from app.pagination import after_clause, check_limit, page
from app.rates import quote_lines, tidy_postcode
from app.records import event_out, find_shipment, pack, shipment_out
from app.schemas import (
    Address,
    Label,
    Shipment,
    ShipmentPage,
    ShipmentRequest,
    TrackingEvents,
    problem_responses,
)

router = APIRouter(prefix="/v1", tags=["Shipments"])


def public_base(request: Request) -> str:
    """Where a shop can reach us. Behind the load balancer the host header is the truth."""
    return (os.environ.get("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")


def sender_for(who: Caller, body: ShipmentRequest) -> Dict[str, Any]:
    """The address on the top left of the label: the one sent, or the one on the account."""
    if body.sender is not None:
        return body.sender.model_dump()
    if who.dispatch_address:
        return Address(**json.loads(who.dispatch_address)).model_dump()
    raise QuillonError(
        "validation_failed",
        "Send a sender, or ask us to put a dispatch address on your account.",
    )


def carrier_of(conn: sqlite3.Connection, code: str) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM carriers WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise QuillonError(
            "validation_failed", f"{code} is not one of our carriers. See GET /v1/carriers."
        )
    return dict(row)


def price_from_quote(
    conn: sqlite3.Connection, who: Caller, quote_id: str
) -> Dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM quotes WHERE id = ? AND customer_id = ? AND mode = ?",
        (quote_id, who.customer_id, who.mode),
    ).fetchone()
    if row is None:
        raise QuillonError("quote_not_found", f"We have no quote {quote_id} for this account.")
    if read_stamp(row["expires_at"]) <= read_stamp(now_stamp()):
        raise QuillonError(
            "quote_expired",
            f"Quote {quote_id} ran out at {row['expires_at']}. Ask for the rates again.",
        )
    return dict(row)


def price_from_card(
    conn: sqlite3.Connection, body: ShipmentRequest, sender: Dict[str, Any]
) -> Dict[str, Any]:
    if not body.carrier_code or not body.service:
        raise QuillonError(
            "validation_failed",
            "Send a quote_id, or carrier_code and service together.",
        )
    carrier_of(conn, body.carrier_code)
    dimensions = body.parcel.dimensions_cm.as_tuple()
    lines = quote_lines(
        conn,
        tidy_postcode(sender["postcode"]),
        tidy_postcode(body.recipient.postcode),
        body.parcel.weight_grams,
        dimensions,
        body.service,
    )
    for line in lines:
        if line["carrier_code"] == body.carrier_code:
            return line
    raise QuillonError(
        "rate_unavailable",
        f"{body.carrier_code} will not take that parcel to "
        f"{tidy_postcode(body.recipient.postcode)} on {body.service}.",
    )


@router.post(
    "/shipments",
    response_model=Shipment,
    status_code=201,
    summary="Book a parcel on to a carrier",
    operation_id="create_shipment",
    responses=problem_responses(
        "validation_failed",
        "rate_unavailable",
        "quote_expired",
        "quote_not_found",
        "idempotency_conflict",
        "reference_in_use",
    ),
)
def create_shipment(
    request: Request,
    body: ShipmentRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Any:
    """Books the parcel, reserves a tracking number and puts the label in the queue to print.

    Either send a quote_id from /v1/rates/quotes, or name a carrier_code and a service and we
    will price it off the card as it stands now.
    """
    sent = body.model_dump()
    key = idempotency.check_key(idempotency_key)
    already = idempotency.look_back(
        conn, who.customer_id, key, "POST", "/v1/shipments", sent
    )
    if already is not None:
        status_code, stored = already
        return JSONResponse(
            stored, status_code=status_code, headers={idempotency.REPLAY_HEADER: "true"}
        )

    sender = sender_for(who, body)
    if body.quote_id:
        quote = price_from_quote(conn, who, body.quote_id)
        carrier_code, service = quote["carrier_code"], quote["service"]
        price_pence = quote["price_pence"]
    else:
        line = price_from_card(conn, body, sender)
        carrier_code, service = line["carrier_code"], line["service"]
        price_pence = line["price_pence"]

    if body.reference:
        clash = conn.execute(
            "SELECT id FROM shipments WHERE customer_id = ? AND mode = ? AND reference = ?",
            (who.customer_id, who.mode, body.reference),
        ).fetchone()
        if clash is not None:
            raise QuillonError(
                "reference_in_use",
                f"Reference {body.reference} is already on shipment {clash['id']}.",
            )

    carrier = carrier_of(conn, carrier_code)
    shipment_id = new_id("shipment")
    created_at = now_stamp()
    recipient = body.recipient.model_dump()
    sender["postcode"] = tidy_postcode(sender["postcode"])
    recipient["postcode"] = tidy_postcode(recipient["postcode"])
    parcel = body.parcel.model_dump()

    conn.execute(
        "INSERT INTO shipments (id, customer_id, mode, carrier_code, service, status, "
        "tracking_number, reference, quote_id, price_pence, sender, recipient, parcel, "
        "created_at) VALUES (?, ?, ?, ?, ?, 'created', ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            shipment_id,
            who.customer_id,
            who.mode,
            carrier_code,
            service,
            tracking_number(carrier["tracking_prefix"]),
            body.reference,
            body.quote_id,
            price_pence,
            pack(sender),
            pack(recipient),
            pack(parcel),
            created_at,
        ),
    )
    conn.execute(
        "INSERT INTO tracking_events (id, shipment_id, code, description, location, occurred_at) "
        "VALUES (?, ?, 'label_created', ?, ?, ?)",
        (
            new_id("tracking_event"),
            shipment_id,
            tracking.description_for("label_created"),
            sender["city"],
            created_at,
        ),
    )

    row = find_shipment(conn, who.customer_id, who.mode, shipment_id)
    out = shipment_out(row)
    webhooks.queue(conn, who.customer_id, "shipment.created", webhooks.summary(out), shipment_id)
    idempotency.remember(
        conn, who.customer_id, key, "POST", "/v1/shipments", sent, 201, out
    )
    return JSONResponse(out, status_code=201)


@router.get(
    "/shipments",
    response_model=ShipmentPage,
    summary="List the account's shipments, newest first",
    operation_id="list_shipments",
    responses=problem_responses("validation_failed", "invalid_cursor"),
)
def list_shipments(
    status: Optional[str] = Query(default=None, description="Narrow to one status."),
    cursor: Optional[str] = Query(default=None, description="The next_cursor off the last page."),
    limit: Optional[int] = Query(default=None, ge=1, le=100),
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    wanted = check_limit(limit)
    if status is not None and status not in tracking.STATUSES:
        raise QuillonError(
            "validation_failed",
            f"{status} is not a status. Ours are: {', '.join(tracking.STATUSES)}.",
        )
    sql = "SELECT * FROM shipments WHERE customer_id = ? AND mode = ?"
    params: list = [who.customer_id, who.mode]
    if status:
        sql += " AND status = ?"
        params.append(status)
    clause, extra = after_clause(cursor)
    sql += clause + " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.extend(extra)
    params.append(wanted + 1)
    rows = [shipment_out(row) for row in conn.execute(sql, params).fetchall()]
    kept, next_cursor = page(rows, wanted)
    return {"data": kept, "next_cursor": next_cursor}


@router.get(
    "/shipments/{shipment_id}",
    response_model=Shipment,
    summary="One shipment",
    operation_id="get_shipment",
    responses=problem_responses("not_found"),
)
def get_shipment(
    shipment_id: str,
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    row = find_shipment(conn, who.customer_id, who.mode, shipment_id)
    if row is None:
        raise QuillonError("not_found", f"No shipment {shipment_id} on this account.")
    return shipment_out(row)


@router.post(
    "/shipments/{shipment_id}/label",
    response_model=Label,
    summary="The label to print and stick on the parcel",
    operation_id="create_label",
    responses=problem_responses("not_found", "label_unavailable"),
)
def create_label(
    request: Request,
    shipment_id: str,
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """A link to a PDF, good for a day. Ask again after that and you get a fresh link.

    A test key gets a sample label with the tracking number on it; no depot will take one.
    """
    row = find_shipment(conn, who.customer_id, who.mode, shipment_id)
    if row is None:
        raise QuillonError("not_found", f"No shipment {shipment_id} on this account.")
    if row["status"] == "cancelled":
        raise QuillonError(
            "label_unavailable",
            f"Shipment {shipment_id} was cancelled on {row['cancelled_at']}.",
        )
    issued = labels.issue(conn, row)
    return {
        "url": f"{public_base(request)}/labels/{issued['token']}.pdf",
        "format": labels.FORMAT,
        "expires_at": issued["expires_at"],
        "tracking_number": row["tracking_number"],
    }


@router.post(
    "/shipments/{shipment_id}/cancel",
    response_model=Shipment,
    summary="Stop a parcel before the driver has it",
    operation_id="cancel_shipment",
    responses=problem_responses("not_found", "not_cancellable", "idempotency_conflict"),
)
def cancel_shipment(
    shipment_id: str,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Any:
    """Only while the shipment is still `created`. Once it is collected it is the carrier's."""
    path = f"/v1/shipments/{shipment_id}/cancel"
    key = idempotency.check_key(idempotency_key)
    already = idempotency.look_back(conn, who.customer_id, key, "POST", path, {})
    if already is not None:
        status_code, stored = already
        return JSONResponse(
            stored, status_code=status_code, headers={idempotency.REPLAY_HEADER: "true"}
        )

    row = find_shipment(conn, who.customer_id, who.mode, shipment_id)
    if row is None:
        raise QuillonError("not_found", f"No shipment {shipment_id} on this account.")
    if not tracking.can_cancel(row["status"]):
        raise QuillonError("not_cancellable", tracking.refusal_for(row["status"]))

    stopped_at = now_stamp()
    conn.execute(
        "UPDATE shipments SET status = 'cancelled', cancelled_at = ?, label_token = NULL, "
        "label_expires_at = NULL WHERE id = ?",
        (stopped_at, shipment_id),
    )
    conn.execute(
        "INSERT INTO tracking_events (id, shipment_id, code, description, location, occurred_at) "
        "VALUES (?, ?, 'cancelled', ?, ?, ?)",
        (
            new_id("tracking_event"),
            shipment_id,
            tracking.description_for("cancelled"),
            "Bristol",
            stopped_at,
        ),
    )
    out = shipment_out(find_shipment(conn, who.customer_id, who.mode, shipment_id))
    webhooks.queue(
        conn, who.customer_id, "shipment.cancelled", webhooks.summary(out), shipment_id
    )
    idempotency.remember(conn, who.customer_id, key, "POST", path, {}, 200, out)
    return JSONResponse(out, status_code=200)


@router.get(
    "/shipments/{shipment_id}/events",
    response_model=TrackingEvents,
    summary="Every scan on a parcel, oldest first",
    operation_id="list_tracking_events",
    responses=problem_responses("not_found"),
)
def list_events(
    shipment_id: str,
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """What the carrier has told us, in the order it happened."""
    row = find_shipment(conn, who.customer_id, who.mode, shipment_id)
    if row is None:
        raise QuillonError("not_found", f"No shipment {shipment_id} on this account.")
    events = conn.execute(
        "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY occurred_at ASC, id ASC",
        (shipment_id,),
    ).fetchall()
    return {"data": [event_out(event) for event in events], "status": row["status"]}
