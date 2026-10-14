"""Loading data/seed.json into an empty store, which is what a fresh checkout gets."""

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.billing import FIELDS as SUBSCRIPTION_FIELDS
from app.ids import now, read_stamp, stamp
from app.records import pack
from app.tracking import description_for

SEED_FILE = Path(__file__).resolve().parent.parent / "data" / "seed.json"

# The file is a snapshot taken at six in the morning UTC on the day after its last day. A store
# gets it moved forward by whole days, to the latest of those mornings that is not after the
# moment the store is first opened, so the history ends the day before.
SNAPSHOT = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)

# Every column that holds a time, and the packed columns with times inside them.
DATED = {
    "customers": ("created_at",),
    "api_keys": ("created_at", "last_used_at"),
    "subscriptions": (
        "current_period_start",
        "current_period_end",
        "trial_ends_at",
        "started_at",
        "cancelled_at",
    ),
    "shipments": ("created_at", "collected_at", "delivered_at", "cancelled_at"),
    "tracking_events": ("occurred_at",),
    "webhook_endpoints": ("created_at", "disabled_at"),
    "webhook_deliveries": ("created_at", "last_attempt_at", "next_attempt_at", "delivered_at"),
    "billing_events": ("occurred_at", "received_at"),
}
PACKED = {"webhook_deliveries": "payload", "billing_events": "payload"}
A_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Two things the file does not repeat on every parcel: the words in front of a tracking code,
# which come from app.tracking, and the sender, which is the shop's dispatch address unless the
# parcel carries one of its own.


def read_seed(path: Optional[Path] = None) -> Dict[str, Any]:
    with open(path or SEED_FILE, encoding="utf-8") as handle:
        return json.load(handle)


def columns(rows: Iterable[Dict[str, Any]], fields: Iterable[str]) -> List[tuple]:
    fields = tuple(fields)
    return [tuple(row.get(field) for field in fields) for row in rows]


def insert(conn: sqlite3.Connection, table: str, fields: Iterable[str], rows: List[tuple]) -> int:
    fields = tuple(fields)
    if not rows:
        return 0
    marks = ", ".join("?" for _ in fields)
    conn.executemany(
        f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({marks})",
        rows,
    )
    return len(rows)


def days_forward(opened: datetime) -> int:
    """Whole days from the snapshot to the latest morning of it that is not after `opened`."""
    return (opened - SNAPSHOT).days


def moved(value: Any, days: int) -> Any:
    """A time moved forward by whole days, and the times inside a payload with it."""
    if isinstance(value, str) and A_TIME.match(value):
        return stamp(read_stamp(value) + timedelta(days=days))
    if isinstance(value, dict):
        return {key: moved(inner, days) for key, inner in value.items()}
    if isinstance(value, list):
        return [moved(inner, days) for inner in value]
    return value


def dated_from(history: Dict[str, Any], days: int) -> Dict[str, Any]:
    """The history with every column in DATED, and every time in a PACKED one, moved forward."""
    out = dict(history)
    for table, fields in DATED.items():
        rows = []
        for row in history[table]:
            row = dict(row)
            for field in fields:
                if field in row:
                    row[field] = moved(row[field], days)
            if table in PACKED:
                row[PACKED[table]] = moved(row[PACKED[table]], days)
            rows.append(row)
        out[table] = rows
    return out


def load_seed(
    conn: sqlite3.Connection, path: Optional[Path] = None, opened: Optional[datetime] = None
) -> Dict[str, int]:
    """Load the history, dated to end the day before `opened`, which is now unless it is given.

    Does nothing to a table that already has rows in it.
    """
    history = read_seed(path)
    history = dated_from(history, days_forward(opened or now()))
    written: Dict[str, int] = {}

    def put(table: str, fields: Iterable[str], rows: List[tuple]) -> None:
        standing = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        written[table] = 0 if standing else insert(conn, table, fields, rows)

    conn.execute("BEGIN")
    try:
        put("customers", CUSTOMER_FIELDS, customer_rows(history["customers"]))
        put(
            "api_keys",
            ("key", "customer_id", "mode", "label", "created_at", "last_used_at"),
            columns(
                history["api_keys"],
                ("key", "customer_id", "mode", "label", "created_at", "last_used_at"),
            ),
        )
        put(
            "subscriptions",
            SUBSCRIPTION_FIELDS,
            columns(history["subscriptions"], SUBSCRIPTION_FIELDS),
        )
        put(
            "carriers",
            ("code", "name", "collection_cutoff", "tracking_prefix"),
            columns(
                history["carriers"], ("code", "name", "collection_cutoff", "tracking_prefix")
            ),
        )
        put(
            "carrier_services",
            ("carrier_code", "service", "name", "description", "max_grams"),
            columns(
                history["carrier_services"],
                ("carrier_code", "service", "name", "description", "max_grams"),
            ),
        )
        put(
            "rate_cards",
            ("carrier_code", "service", "zone", "max_grams", "price_pence", "estimated_days"),
            columns(
                history["rate_cards"],
                ("carrier_code", "service", "zone", "max_grams", "price_pence", "estimated_days"),
            ),
        )
        put(
            "shipments",
            SHIPMENT_FIELDS,
            shipment_rows(history["shipments"], history["customers"]),
        )
        put(
            "tracking_events",
            ("id", "shipment_id", "code", "description", "location", "occurred_at"),
            event_rows(history["tracking_events"]),
        )
        put(
            "webhook_endpoints",
            ("id", "customer_id", "url", "events", "secret", "status", "created_at",
             "disabled_at"),
            endpoint_rows(history["webhook_endpoints"]),
        )
        put(
            "webhook_deliveries",
            ("id", "endpoint_id", "event_type", "shipment_id", "payload", "status", "attempts",
             "last_error", "created_at", "last_attempt_at", "next_attempt_at", "delivered_at"),
            delivery_rows(history["webhook_deliveries"]),
        )
        put(
            "billing_events",
            ("id", "customer_id", "type", "occurred_at", "payload", "received_at"),
            billing_event_rows(history["billing_events"]),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return written


CUSTOMER_FIELDS = (
    "id",
    "name",
    "platform",
    "city",
    "contact_email",
    "status",
    "created_at",
    "dispatch_address",
)


def customer_rows(rows: Iterable[Dict[str, Any]]) -> List[tuple]:
    out = []
    for row in rows:
        packed = dict(row)
        packed["dispatch_address"] = pack(row["dispatch_address"])
        out.append(tuple(packed.get(field) for field in CUSTOMER_FIELDS))
    return out


SHIPMENT_FIELDS = (
    "id",
    "customer_id",
    "mode",
    "carrier_code",
    "service",
    "status",
    "tracking_number",
    "reference",
    "quote_id",
    "price_pence",
    "sender",
    "recipient",
    "parcel",
    "created_at",
    "collected_at",
    "delivered_at",
    "cancelled_at",
)


def shipment_rows(
    rows: Iterable[Dict[str, Any]], customers: Iterable[Dict[str, Any]]
) -> List[tuple]:
    """Sender: the one on the parcel if it has one, otherwise the shop's dispatch address."""
    senders = {row["id"]: row["dispatch_address"] for row in customers}
    out = []
    for row in rows:
        packed = dict(row)
        packed["sender"] = pack(row.get("sender") or senders[row["customer_id"]])
        for field in ("recipient", "parcel"):
            packed[field] = pack(packed[field])
        out.append(tuple(packed.get(field) for field in SHIPMENT_FIELDS))
    return out


def event_rows(rows: Iterable[Dict[str, Any]]) -> List[tuple]:
    return [
        (
            row["id"],
            row["shipment_id"],
            row["code"],
            description_for(row["code"]),
            row["location"],
            row["occurred_at"],
        )
        for row in rows
    ]


def endpoint_rows(rows: Iterable[Dict[str, Any]]) -> List[tuple]:
    return [
        (
            row["id"],
            row["customer_id"],
            row["url"],
            json.dumps(row["events"]),
            row["secret"],
            row["status"],
            row["created_at"],
            row.get("disabled_at"),
        )
        for row in rows
    ]


def delivery_rows(rows: Iterable[Dict[str, Any]]) -> List[tuple]:
    return [
        (
            row["id"],
            row["endpoint_id"],
            row["event_type"],
            row.get("shipment_id"),
            json.dumps(row["payload"], separators=(",", ":"), sort_keys=True),
            row["status"],
            row["attempts"],
            row.get("last_error"),
            row["created_at"],
            row.get("last_attempt_at"),
            row.get("next_attempt_at"),
            row.get("delivered_at"),
        )
        for row in rows
    ]


def billing_event_rows(rows: Iterable[Dict[str, Any]]) -> List[tuple]:
    return [
        (
            row["id"],
            row["customer_id"],
            row["type"],
            row["occurred_at"],
            pack(row["payload"]),
            row["received_at"],
        )
        for row in rows
    ]
