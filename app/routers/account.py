"""The account behind a key: its plan, where the subscription stands, and the month so far."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app import billing
from app.auth import Caller, caller
from app.db import get_conn
from app.ids import now, stamp
from app.schemas import Account, problem_responses

router = APIRouter(prefix="/v1", tags=["Account"])

# What the account shows of its subscription.
SUBSCRIPTION_FIELDS = (
    "plan", "status", "current_period_start", "current_period_end", "trial_ends_at"
)


@router.get(
    "/account",
    response_model=Account,
    summary="Your plan and the month so far",
    operation_id="get_account",
    responses=problem_responses(),
)
def get_account(
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """The account the key belongs to and nothing else.

    The month is the calendar month in UTC, counted on the mode of the key: a test key sees its
    test parcels, which are never invoiced. A parcel cancelled before collection is not counted.
    """
    shop = conn.execute(
        "SELECT id, name, platform FROM customers WHERE id = ?", (who.customer_id,)
    ).fetchone()
    subscription = billing.subscription_for(conn, who.customer_id)

    today = now()
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = conn.execute(
        "SELECT COUNT(*) AS parcels, COALESCE(SUM(price_pence), 0) AS spend_pence, "
        "MAX(created_at) AS last_booked_at FROM shipments "
        "WHERE customer_id = ? AND mode = ? AND created_at >= ? AND status != 'cancelled'",
        (who.customer_id, who.mode, stamp(month_start)),
    ).fetchone()
    return {
        **dict(shop),
        **{field: subscription[field] for field in SUBSCRIPTION_FIELDS},
        "mode": who.mode,
        "this_month": {"month": today.strftime("%Y-%m"), **dict(month)},
    }
