"""The feed the billing provider posts subscription and invoice events into. Not part of /v1."""

import hmac
import os
import sqlite3
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header

from app import billing
from app.db import get_conn
from app.errors import QuillonError
from app.ids import new_id, now_stamp, read_stamp, stamp
from app.plans import PLANS
from app.records import pack
from app.schemas import BillingEvent, BillingReceipt, problem_responses

router = APIRouter(tags=["Billing feed"])

SECRET_VARIABLE = "BILLING_SECRET"
SECRET_HEADER = "Billing-Secret"


def check_secret(given: Optional[str]) -> None:
    wanted = os.environ.get(SECRET_VARIABLE)
    if not wanted or not given or not hmac.compare_digest(
        given.strip().encode("utf-8", "replace"), wanted.encode("utf-8")
    ):
        raise QuillonError(
            "invalid_billing_secret",
            f"Send the secret we set up with the billing provider as {SECRET_HEADER}.",
        )


def occurred_in_utc(event: BillingEvent) -> str:
    """occurred_at in the one format we store, so two of them compare as text."""
    try:
        moment = read_stamp(event.occurred_at)
    except ValueError:
        moment = None
    if moment is None or moment.tzinfo is None:
        raise QuillonError(
            "validation_failed",
            f"occurred_at: {event.occurred_at} is not a UTC time like 2026-08-01T09:00:00Z.",
        )
    return stamp(moment)


def check_plan(event: BillingEvent) -> None:
    if event.type in billing.NAMES_A_PLAN and event.data.get("plan") not in PLANS:
        raise QuillonError(
            "validation_failed",
            f"data.plan: {event.type} needs the plan, one of {', '.join(PLANS)}.",
        )


@router.post(
    "/billing/events",
    response_model=BillingReceipt,
    summary="Record one event from the billing provider",
    operation_id="record_billing_event",
    responses=problem_responses(
        "invalid_billing_secret", "not_found", "validation_failed", authenticated=False
    ),
)
def record_billing_event(
    event: BillingEvent,
    billing_secret: Optional[str] = Header(default=None, alias=SECRET_HEADER),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """One event, matched to the shop by customer id, kept whatever it does.

    An event older than the latest one we hold for that shop is kept but moves nothing, and so is
    anything after a cancellation.
    """
    check_secret(billing_secret)
    occurred_at = occurred_in_utc(event)
    check_plan(event)

    customer = conn.execute(
        "SELECT id FROM customers WHERE id = ?", (event.customer_id,)
    ).fetchone()
    if customer is None:
        raise QuillonError("not_found", f"No shop of ours with the id {event.customer_id}.")

    latest = conn.execute(
        "SELECT MAX(occurred_at) FROM billing_events WHERE customer_id = ?",
        (event.customer_id,),
    ).fetchone()[0]
    event_id = new_id("billing_event")
    conn.execute(
        "INSERT INTO billing_events (id, customer_id, type, occurred_at, payload, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (event_id, event.customer_id, event.type, occurred_at, pack(event.data), now_stamp()),
    )

    row = conn.execute(
        "SELECT * FROM subscriptions WHERE customer_id = ?", (event.customer_id,)
    ).fetchone()
    before = dict(row) if row is not None else None
    after = before
    if latest is None or occurred_at >= latest:
        after = billing.apply(before, event.customer_id, event.type, occurred_at, event.data)
    moved = after is not None and after != before
    if moved:
        billing.save(conn, after)
    return {
        "id": event_id,
        "customer_id": event.customer_id,
        "plan": after["plan"] if after else None,
        "status": after["status"] if after else None,
        "moved": moved,
    }
