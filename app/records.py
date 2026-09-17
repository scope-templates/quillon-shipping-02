"""Rows to JSON and back. Addresses and parcels live packed in one column each."""

import json
import sqlite3
from typing import Any, Dict, List, Optional

PACKED_FIELDS = ("sender", "recipient", "parcel")

SHIPMENT_FIELDS = (
    "id",
    "mode",
    "status",
    "carrier_code",
    "service",
    "tracking_number",
    "price_pence",
    "reference",
    "quote_id",
    "sender",
    "recipient",
    "parcel",
    "created_at",
    "collected_at",
    "delivered_at",
    "cancelled_at",
)


def pack(value: Dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def unpack(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def shipment_out(row: Any) -> Dict[str, Any]:
    raw = dict(row)
    for field in PACKED_FIELDS:
        raw[field] = unpack(raw.get(field))
    return {field: raw.get(field) for field in SHIPMENT_FIELDS}


def event_out(row: Any) -> Dict[str, Any]:
    raw = dict(row)
    return {
        "code": raw["code"],
        "description": raw["description"],
        "location": raw["location"],
        "occurred_at": raw["occurred_at"],
    }


def carriers_out(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    carriers = conn.execute(
        "SELECT code, name, collection_cutoff FROM carriers ORDER BY name ASC"
    ).fetchall()
    services = conn.execute(
        "SELECT carrier_code, service, name, description, max_grams FROM carrier_services "
        "ORDER BY carrier_code ASC, service ASC"
    ).fetchall()
    by_carrier: Dict[str, List[Dict[str, Any]]] = {}
    for row in services:
        by_carrier.setdefault(row["carrier_code"], []).append(
            {
                "service": row["service"],
                "name": row["name"],
                "description": row["description"],
                "max_grams": row["max_grams"],
            }
        )
    return [
        {
            "code": carrier["code"],
            "name": carrier["name"],
            "collection_cutoff": carrier["collection_cutoff"],
            "services": by_carrier.get(carrier["code"], []),
        }
        for carrier in carriers
    ]


def find_shipment(
    conn: sqlite3.Connection, customer_id: str, mode: str, shipment_id: str
) -> Optional[Dict[str, Any]]:
    """A parcel belongs to one account and one mode. A live key cannot see a test parcel."""
    row = conn.execute(
        "SELECT * FROM shipments WHERE id = ? AND customer_id = ? AND mode = ?",
        (shipment_id, customer_id, mode),
    ).fetchone()
    return dict(row) if row is not None else None
