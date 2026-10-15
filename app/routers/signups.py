"""Signing up from the website: a shop, a trial, and one test key to build against."""

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app import billing
from app.db import get_conn
from app.errors import QuillonError
from app.auth import issue_key
from app.ids import new_id, now, stamp
from app.schemas import Signup, SignupRequest, problem_responses

router = APIRouter(tags=["Signups"])

# The label the key is filed under, the same as keys set up by hand.
KEY_LABEL = "Integration"


def email_in_use(conn: sqlite3.Connection, folded: str) -> bool:
    """Compared casefolded in Python, because sqlite's lower() stops at the ASCII letters."""
    return any(
        row[0].casefold() == folded
        for row in conn.execute("SELECT contact_email FROM customers")
    )


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
    at = now()
    customer = {
        "id": new_id("customer"),
        "name": body.shop_name,
        "platform": body.platform,
        "city": body.city,
        "contact_email": email,
        "status": "trialling",
        "created_at": stamp(at),
    }
    subscription = billing.trial(customer["id"], at)

    conn.execute("BEGIN IMMEDIATE")
    try:
        if email_in_use(conn, email.casefold()):
            raise QuillonError(
                "email_in_use",
                f"There is already an account for {email}. Write to support@quillonpost.co.uk "
                "and we will find it for you.",
            )
        conn.execute(
            f"INSERT INTO customers ({', '.join(customer)}) "
            f"VALUES ({', '.join('?' for _ in customer)})",
            tuple(customer.values()),
        )
        billing.save(conn, subscription)
        key = issue_key(conn, customer["id"], "test", KEY_LABEL, customer["created_at"])
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"customer": customer, "subscription": subscription, "key": key}
