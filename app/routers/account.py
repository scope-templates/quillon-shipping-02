"""The account behind a key: its plan, where the subscription stands, and the month so far."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.auth import Caller, caller
from app.db import get_conn
from app.errors import QuillonError
from app.ids import now, stamp
from app.schemas import Account, problem_responses

router = APIRouter(prefix="/v1", tags=["Account"])


@router.get(
    "/account",
    response_model=Account,
    summary="Your plan and the month so far",
    operation_id="get_account",
    responses=problem_responses("not_found"),
)
def get_account(
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """The account the key belongs to and nothing else.

    The month is the calendar month in UTC, counted on the mode of the key: a test key sees its
    test parcels, which are never invoiced. A parcel cancelled before collection is not counted.
    """
    row = conn.execute(
        "SELECT c.id, c.name, c.platform, s.plan, s.status, s.current_period_start, "
        "s.current_period_end, s.trial_ends_at "
        "FROM customers c JOIN subscriptions s ON s.customer_id = c.id WHERE c.id = ?",
        (who.customer_id,),
    ).fetchone()
    if row is None:
        raise QuillonError(
            "not_found",
            "We have no plan on file for this account. Write to support@quillonpost.co.uk.",
        )

    today = now()
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month = conn.execute(
        "SELECT COUNT(*) AS parcels, COALESCE(SUM(price_pence), 0) AS spend_pence, "
        "MAX(created_at) AS last_booked_at FROM shipments "
        "WHERE customer_id = ? AND mode = ? AND created_at >= ? AND status != 'cancelled'",
        (who.customer_id, who.mode, stamp(month_start)),
    ).fetchone()
    return {
        **dict(row),
        "mode": who.mode,
        "this_month": {"month": today.strftime("%Y-%m"), **dict(month)},
    }
