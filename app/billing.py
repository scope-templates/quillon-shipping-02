"""A shop's subscription, and what each event from the billing provider does to it.

The provider is where the card is and where the invoices are raised; we keep a copy of where each
shop stands so the API can answer without asking it.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.ids import read_stamp, stamp
from app.plans import TRIAL_DAYS, TRIAL_PLAN, fee_for, one_month_on

EVENT_TYPES = (
    "subscription.started",
    "subscription.plan_changed",
    "invoice.paid",
    "invoice.payment_failed",
    "subscription.cancelled",
)

# The two that say which plan the shop is on now, in data.plan.
NAMES_A_PLAN = ("subscription.started", "subscription.plan_changed")

STATUSES = ("trialling", "active", "past_due", "cancelled")

# subscription status -> the status on the customer row, which is what a key is checked against.
CUSTOMER_STATUS = {
    "trialling": "trialling",
    "active": "active",
    "past_due": "active",
    "cancelled": "closed",
}

FIELDS = (
    "customer_id",
    "plan",
    "status",
    "monthly_fee_pence",
    "current_period_start",
    "current_period_end",
    "trial_ends_at",
    "started_at",
    "cancelled_at",
)


def trial(customer_id: str, at: datetime) -> Dict[str, Any]:
    """The subscription a signup from the website starts on."""
    ends = stamp(at + timedelta(days=TRIAL_DAYS))
    return {
        "customer_id": customer_id,
        "plan": TRIAL_PLAN,
        "status": "trialling",
        "monthly_fee_pence": fee_for(TRIAL_PLAN),
        "current_period_start": stamp(at),
        "current_period_end": ends,
        "trial_ends_at": ends,
        "started_at": stamp(at),
        "cancelled_at": None,
    }


def apply(
    subscription: Optional[Dict[str, Any]],
    customer_id: str,
    event_type: str,
    occurred_at: str,
    data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """The subscription after one event, or None when there is still no subscription to move.

    A cancelled subscription is finished with and stays as it is. Every event but a start needs a
    subscription already there.
    """
    if subscription is None:
        if event_type != "subscription.started":
            return None
        subscription = {field: None for field in FIELDS}
        subscription["customer_id"] = customer_id
    after = dict(subscription)
    if after["status"] == "cancelled":
        return after

    if event_type == "subscription.started":
        after.update(
            plan=data["plan"],
            status="active",
            monthly_fee_pence=fee_for(data["plan"]),
            started_at=occurred_at,
            cancelled_at=None,
        )
        after.update(period_from(occurred_at))
    elif event_type == "subscription.plan_changed":
        after.update(plan=data["plan"], monthly_fee_pence=fee_for(data["plan"]))
    elif event_type == "invoice.paid":
        after["status"] = "active"
        after.update(period_from(occurred_at))
    elif event_type == "invoice.payment_failed":
        after["status"] = "past_due"
    elif event_type == "subscription.cancelled":
        after.update(status="cancelled", cancelled_at=occurred_at)
    return after


def period_from(occurred_at: str) -> Dict[str, str]:
    """A period runs a calendar month from the start, or from the invoice that paid for it."""
    return {
        "current_period_start": occurred_at,
        "current_period_end": stamp(one_month_on(read_stamp(occurred_at))),
    }


def save(conn: sqlite3.Connection, subscription: Dict[str, Any]) -> None:
    """Keep the subscription in place of the last one, with the customer status it goes with."""
    conn.execute(
        f"INSERT INTO subscriptions ({', '.join(FIELDS)}) "
        f"VALUES ({', '.join('?' for _ in FIELDS)}) "
        "ON CONFLICT(customer_id) DO UPDATE SET "
        + ", ".join(f"{field} = excluded.{field}" for field in FIELDS[1:]),
        tuple(subscription[field] for field in FIELDS),
    )
    conn.execute(
        "UPDATE customers SET status = ? WHERE id = ?",
        (CUSTOMER_STATUS[subscription["status"]], subscription["customer_id"]),
    )
