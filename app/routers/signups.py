"""Signing up from the website: a shop, a trial, and one test key to build against."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app import billing
from app.db import get_conn
from app.errors import QuillonError
from app.ids import api_key, new_id, now, stamp
from app.schemas import Signup, SignupRequest, problem_responses

router = APIRouter(tags=["Signups"])

# The label the key goes under in the back office, the same as the keys Ada sets up by hand.
KEY_LABEL = "Integration"


@router.post(
    "/signups",
    response_model=Signup,
    status_code=201,
    summary="Sign a shop up for a trial",
    operation_id="create_signup",
    responses=problem_responses("validation_failed", "email_in_use", authenticated=False),
)
def create_signup(
    body: SignupRequest,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """No key needed: this is what the form on the website posts.

    The shop starts trialling on pay as you go, with one test key that comes back once, here.
    Live keys are set up by hand when the shop signs.
    """
    email = str(body.contact_email).lower()
    taken = conn.execute(
        "SELECT 1 FROM customers WHERE lower(contact_email) = ?", (email,)
    ).fetchone()
    if taken is not None:
        raise QuillonError(
            "email_in_use",
            f"There is already an account for {email}. Write to support@quillonpost.co.uk "
            "and we will find it for you.",
        )

    at = now()
    customer = {
        "id": new_id("customer"),
        "name": body.shop_name.strip(),
        "platform": body.platform.strip(),
        "city": body.city.strip(),
        "contact_email": email,
        "status": "trialling",
        "created_at": stamp(at),
    }
    subscription = billing.trial(customer["id"], at)
    key = api_key("test")

    conn.execute("BEGIN")
    try:
        conn.execute(
            f"INSERT INTO customers ({', '.join(customer)}) "
            f"VALUES ({', '.join('?' for _ in customer)})",
            tuple(customer.values()),
        )
        billing.save(conn, subscription)
        conn.execute(
            "INSERT INTO api_keys (key, customer_id, mode, label, created_at) "
            "VALUES (?, ?, 'test', ?, ?)",
            (key, customer["id"], KEY_LABEL, customer["created_at"]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"customer": customer, "subscription": subscription, "key": key}
