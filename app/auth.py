"""Who is calling: one bearer key, one row in api_keys, one customer, one mode."""

import sqlite3
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db import get_conn
from app.errors import QuillonError
from app.ids import now_stamp

KEY_PREFIXES = ("qp_test_", "qp_live_")

scheme = HTTPBearer(auto_error=False, description="Your API key, as Bearer qp_live_...")


@dataclass(frozen=True)
class Caller:
    """The shop behind the key on this request."""

    customer_id: str
    name: str
    key: str
    mode: str
    dispatch_address: Optional[str] = None


def mode_of(key: str) -> Optional[str]:
    for prefix in KEY_PREFIXES:
        if key.startswith(prefix):
            return prefix.split("_")[1]
    return None


def lookup(conn: sqlite3.Connection, key: str) -> Optional[Caller]:
    """The caller behind a key. Raises when the key is fine but the account is shut."""
    row = conn.execute(
        "SELECT k.key, k.mode, k.customer_id, c.name, c.status, c.dispatch_address "
        "FROM api_keys k JOIN customers c ON c.id = k.customer_id WHERE k.key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    if row["status"] != "active":
        raise QuillonError(
            "account_closed",
            "This account is closed. Write to support@quillonpost.co.uk if that is a surprise.",
        )
    return Caller(
        customer_id=row["customer_id"],
        name=row["name"],
        key=row["key"],
        mode=row["mode"],
        dispatch_address=row["dispatch_address"],
    )


def touch(conn: sqlite3.Connection, key: str) -> None:
    """Last used, for the page in the back office that tells Ada which keys are dead."""
    conn.execute("UPDATE api_keys SET last_used_at = ? WHERE key = ?", (now_stamp(), key))


def caller(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(scheme),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Caller:
    if credentials is None or not (credentials.credentials or "").strip():
        raise QuillonError(
            "missing_credentials",
            "Send your API key as Authorization: Bearer qp_live_... on every call.",
        )
    key = credentials.credentials.strip()
    if mode_of(key) is None:
        raise QuillonError(
            "invalid_key",
            "Keys start with qp_test_ or qp_live_. Check you have sent the key and not the "
            "webhook secret.",
        )
    found = lookup(conn, key)
    if found is None:
        raise QuillonError(
            "invalid_key",
            "We do not recognise that key. It may have been rolled from the back office.",
        )
    touch(conn, key)
    request.state.caller = found
    return found
