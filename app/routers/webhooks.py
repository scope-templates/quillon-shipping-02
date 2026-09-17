"""Webhook endpoints: register one, list them, take one off."""

import json
import sqlite3
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, Response
from fastapi.responses import JSONResponse

from app import idempotency, webhooks
from app.auth import Caller, caller
from app.db import get_conn
from app.errors import QuillonError
from app.ids import new_id, now_stamp, webhook_secret
from app.schemas import WebhookEndpoint, WebhookEndpoints, WebhookRequest, problem_responses

router = APIRouter(prefix="/v1", tags=["Webhooks"])

MAX_ENDPOINTS = 10


def check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise QuillonError(
            "validation_failed", "Webhook URLs have to be https. We will not post to http."
        )
    if not parsed.netloc:
        raise QuillonError("validation_failed", f"{url} is not a URL we can post to.")
    return url


@router.post(
    "/webhooks",
    response_model=WebhookEndpoint,
    status_code=201,
    summary="Register a URL to be told about parcels",
    operation_id="create_webhook_endpoint",
    responses=problem_responses("validation_failed", "idempotency_conflict"),
)
def create_endpoint(
    body: WebhookRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Any:
    """The secret comes back once, here. Store it: we cannot show it to you again.

    Sign-checking is described in docs/tracking-and-webhooks.md, with a snippet to copy.
    """
    sent = body.model_dump()
    key = idempotency.check_key(idempotency_key)
    already = idempotency.look_back(conn, who.customer_id, key, "POST", "/v1/webhooks", sent)
    if already is not None:
        status_code, stored = already
        return JSONResponse(
            stored, status_code=status_code, headers={idempotency.REPLAY_HEADER: "true"}
        )

    check_url(body.url)
    standing = conn.execute(
        "SELECT COUNT(*) FROM webhook_endpoints WHERE customer_id = ? AND status = 'active'",
        (who.customer_id,),
    ).fetchone()[0]
    if standing >= MAX_ENDPOINTS:
        raise QuillonError(
            "validation_failed",
            f"This account already has {MAX_ENDPOINTS} endpoints. Delete one first.",
        )

    endpoint_id = new_id("webhook_endpoint")
    created_at = now_stamp()
    conn.execute(
        "INSERT INTO webhook_endpoints (id, customer_id, url, events, secret, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?)",
        (
            endpoint_id,
            who.customer_id,
            body.url,
            json.dumps(list(body.events)),
            webhook_secret(),
            created_at,
        ),
    )
    row = dict(
        conn.execute(
            "SELECT * FROM webhook_endpoints WHERE id = ?", (endpoint_id,)
        ).fetchone()
    )
    out = webhooks.public_endpoint(row, with_secret=True)
    idempotency.remember(
        conn, who.customer_id, key, "POST", "/v1/webhooks", sent, 201, out
    )
    return JSONResponse(out, status_code=201)


@router.get(
    "/webhooks",
    response_model=WebhookEndpoints,
    summary="The endpoints on this account",
    operation_id="list_webhook_endpoints",
    responses=problem_responses(),
)
def list_endpoints(
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM webhook_endpoints WHERE customer_id = ? AND status = 'active' "
        "ORDER BY created_at DESC, id DESC",
        (who.customer_id,),
    ).fetchall()
    return {"data": [webhooks.public_endpoint(dict(row)) for row in rows]}


@router.delete(
    "/webhooks/{endpoint_id}",
    status_code=204,
    summary="Stop posting to an endpoint",
    operation_id="delete_webhook_endpoint",
    responses=problem_responses("not_found"),
)
def delete_endpoint(
    endpoint_id: str,
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    """Deliveries already queued for it stop with it."""
    row = conn.execute(
        "SELECT * FROM webhook_endpoints WHERE id = ? AND customer_id = ? AND status = 'active'",
        (endpoint_id, who.customer_id),
    ).fetchone()
    if row is None:
        raise QuillonError("not_found", f"No endpoint {endpoint_id} on this account.")
    stopped_at = now_stamp()
    conn.execute(
        "UPDATE webhook_endpoints SET status = 'deleted', disabled_at = ? WHERE id = ?",
        (stopped_at, endpoint_id),
    )
    conn.execute(
        "UPDATE webhook_deliveries SET status = 'given_up', next_attempt_at = NULL, "
        "last_error = 'endpoint deleted' WHERE endpoint_id = ? AND status IN ('pending', 'failed')",
        (endpoint_id,),
    )
    return Response(status_code=204)
