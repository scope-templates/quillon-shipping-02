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

# On a plan: what changes plan, is invoiced and can fall behind.
RUNNING = ("active", "past_due")

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
    return {
        "customer_id": customer_id,
        "plan": TRIAL_PLAN,
        "status": "trialling",
        "monthly_fee_pence": fee_for(TRIAL_PLAN),
        **period_from(TRIAL_PLAN, stamp(at)),
        "trial_ends_at": stamp(at + timedelta(days=TRIAL_DAYS)),
        "started_at": stamp(at),
        "cancelled_at": None,
    }


def apply(
    subscription: Dict[str, Any], event_type: str, occurred_at: str, data: Dict[str, Any]
) -> Dict[str, Any]:
    """The subscription after one event, the same as before when the event does not move it.

    A trialling subscription starts or is cancelled. A running one changes plan, is invoiced or is
    cancelled, and does not start a second time: `started_at` is the first start, kept for good.
    A cancelled one starts again when the shop comes back.
    """
    after = dict(subscription)
    status = after["status"]

    if event_type == "subscription.started":
        if status in ("trialling", "cancelled"):
            after.update(
                plan=data["plan"],
                status="active",
                monthly_fee_pence=fee_for(data["plan"]),
                cancelled_at=None,
            )
            after.update(period_from(data["plan"], occurred_at))
            if status == "trialling":
                after["started_at"] = occurred_at
    elif event_type == "subscription.cancelled":
        if status != "cancelled":
            after.update(status="cancelled", cancelled_at=occurred_at)
    elif status in RUNNING:
        if event_type == "subscription.plan_changed":
            after.update(plan=data["plan"], monthly_fee_pence=fee_for(data["plan"]))
            if not fee_for(data["plan"]) or after["current_period_start"] is None:
                after.update(period_from(data["plan"], occurred_at))
        elif event_type == "invoice.paid":
            after["status"] = "active"
            if fee_for(after["plan"]):
                after.update(period_from(after["plan"], occurred_at))
        elif event_type == "invoice.payment_failed":
            after["status"] = "past_due"
    return after


def period_from(plan: str, occurred_at: str) -> Dict[str, Optional[str]]:
    """A month from the start, or from the invoice that paid for it. Pay as you go has none."""
    if not fee_for(plan):
        return {"current_period_start": None, "current_period_end": None}
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
