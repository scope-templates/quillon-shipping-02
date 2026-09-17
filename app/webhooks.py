"""Signing a delivery, queueing it, and writing down how it went.

Nothing is posted from inside a request: a shipment that changes writes a row into
webhook_deliveries and scripts/deliver_webhooks.py works through the queue.
"""

import hashlib
import hmac
import json
import sqlite3
from datetime import timedelta
from typing import Any, Dict, List, Optional

from app.ids import new_id, now, now_stamp, read_stamp, stamp

SIGNATURE_HEADER = "Quillon-Signature"
SIGNATURE_SCHEME = "v1"
# A delivery signed more than five minutes ago is stale; say so in the docs and hold to it.
TOLERANCE_SECONDS = 300

EVENT_TYPES = (
    "shipment.created",
    "shipment.cancelled",
    "shipment.delivered",
    "tracking.updated",
)

# How long we wait before each attempt. Nine attempts, then the endpoint is left alone.
BACKOFF_SECONDS = (0, 30, 120, 600, 1800, 7200, 21600, 43200, 86400)
MAX_ATTEMPTS = len(BACKOFF_SECONDS)


def signed_payload(timestamp: int, body: bytes) -> bytes:
    return str(timestamp).encode("ascii") + b"." + body


def sign(secret: str, body: bytes, timestamp: Optional[int] = None) -> str:
    """The whole header value, ready to put on the request."""
    when = int(timestamp if timestamp is not None else now().timestamp())
    digest = hmac.new(
        secret.encode("utf-8"), signed_payload(when, body), hashlib.sha256
    ).hexdigest()
    return f"t={when},{SIGNATURE_SCHEME}={digest}"


def parse_signature(header: str) -> Dict[str, str]:
    parts: Dict[str, str] = {}
    for piece in (header or "").split(","):
        name, found, value = piece.strip().partition("=")
        if found:
            parts[name] = value
    return parts


def verify(secret: str, body: bytes, header: str, now_seconds: Optional[int] = None) -> bool:
    """What a shop does at its end. Kept here so our docs and our tests agree on it."""
    parts = parse_signature(header)
    try:
        when = int(parts.get("t", ""))
    except ValueError:
        return False
    given = parts.get(SIGNATURE_SCHEME, "")
    current = int(now_seconds if now_seconds is not None else now().timestamp())
    if abs(current - when) > TOLERANCE_SECONDS:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), signed_payload(when, body), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, given)


def summary(shipment: Dict[str, Any]) -> Dict[str, Any]:
    """The parcel in short. Deliveries carry this and not the addresses."""
    return {
        field: shipment.get(field)
        for field in ("id", "status", "carrier_code", "service", "tracking_number", "reference")
    }


def body_bytes(payload: Dict[str, Any]) -> bytes:
    """One encoding of a payload, used to sign it and to post it."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def next_attempt_at(attempts: int, since: Optional[str] = None) -> Optional[str]:
    """When attempt number `attempts + 1` is due, or None once we have given up."""
    if attempts >= MAX_ATTEMPTS:
        return None
    moment = read_stamp(since) if since else now()
    return stamp(moment + timedelta(seconds=BACKOFF_SECONDS[attempts]))


def endpoints_for(
    conn: sqlite3.Connection, customer_id: str, event_type: str
) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM webhook_endpoints WHERE customer_id = ? AND status = 'active' "
        "ORDER BY created_at ASC, id ASC",
        (customer_id,),
    ).fetchall()
    out = []
    for row in rows:
        if event_type in json.loads(row["events"]):
            out.append(dict(row))
    return out


def queue(
    conn: sqlite3.Connection,
    customer_id: str,
    event_type: str,
    data: Dict[str, Any],
    shipment_id: Optional[str] = None,
) -> List[str]:
    """Write one row per listening endpoint. Returns the delivery ids, mostly for support."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"{event_type} is not an event we send")
    created = now_payload(event_type, data)
    made: List[str] = []
    for endpoint in endpoints_for(conn, customer_id, event_type):
        delivery_id = new_id("webhook_delivery")
        conn.execute(
            "INSERT INTO webhook_deliveries (id, endpoint_id, event_type, shipment_id, payload, "
            "status, attempts, created_at, next_attempt_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)",
            (
                delivery_id,
                endpoint["id"],
                event_type,
                shipment_id,
                json.dumps(created, separators=(",", ":"), sort_keys=True),
                created["created_at"],
                created["created_at"],
            ),
        )
        made.append(delivery_id)
    return made


def now_payload(event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": new_id("webhook_event"),
        "type": event_type,
        "created_at": now_stamp(),
        "data": data,
    }


def due(conn: sqlite3.Connection, at: Optional[str] = None) -> List[Dict[str, Any]]:
    """Deliveries waiting to go out, oldest first."""
    when = at or now_stamp()
    rows = conn.execute(
        "SELECT d.*, e.url, e.secret, e.status AS endpoint_status FROM webhook_deliveries d "
        "JOIN webhook_endpoints e ON e.id = d.endpoint_id "
        "WHERE d.status IN ('pending', 'failed') AND d.next_attempt_at IS NOT NULL "
        "AND d.next_attempt_at <= ? ORDER BY d.next_attempt_at ASC, d.id ASC",
        (when,),
    ).fetchall()
    return [dict(row) for row in rows]


def record_success(conn: sqlite3.Connection, delivery_id: str, attempts: int) -> None:
    moment = now_stamp()
    conn.execute(
        "UPDATE webhook_deliveries SET status = 'delivered', attempts = ?, last_error = NULL, "
        "last_attempt_at = ?, next_attempt_at = NULL, delivered_at = ? WHERE id = ?",
        (attempts, moment, moment, delivery_id),
    )


def record_failure(
    conn: sqlite3.Connection, delivery_id: str, attempts: int, error: str
) -> None:
    moment = now_stamp()
    following = next_attempt_at(attempts, moment)
    conn.execute(
        "UPDATE webhook_deliveries SET status = ?, attempts = ?, last_error = ?, "
        "last_attempt_at = ?, next_attempt_at = ? WHERE id = ?",
        (
            "failed" if following else "given_up",
            attempts,
            error[:400],
            moment,
            following,
            delivery_id,
        ),
    )


def public_endpoint(row: Dict[str, Any], with_secret: bool = False) -> Dict[str, Any]:
    """An endpoint as a shop sees it. The secret goes out once, when it is created."""
    out = {
        "id": row["id"],
        "url": row["url"],
        "events": json.loads(row["events"]) if isinstance(row["events"], str) else row["events"],
        "status": row["status"],
        "created_at": row["created_at"],
    }
    if with_secret:
        out["secret"] = row["secret"]
    return out
