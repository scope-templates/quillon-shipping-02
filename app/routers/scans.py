"""The feed the carriers post scans into. Not part of /v1 and not for shops."""

import os
import sqlite3
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header

from app import tracking, webhooks
from app.db import get_conn
from app.errors import QuillonError
from app.ids import new_id
from app.records import shipment_out, unpack
from app.schemas import CarrierScan, ScanReceipt, problem_responses

router = APIRouter(tags=["Carrier feeds"])

SECRET_PREFIX = "CARRIER_SECRET_"

# The status a scan moves a parcel to, and the column on the shipment that goes with it.
STAMPS = {"collected": "collected_at", "delivered": "delivered_at"}


def secret_for(carrier_code: str) -> Optional[str]:
    return os.environ.get(f"{SECRET_PREFIX}{carrier_code.upper()}")


def check_secret(carrier_code: str, given: Optional[str]) -> None:
    wanted = secret_for(carrier_code)
    if not wanted or not given or given.strip() != wanted:
        raise QuillonError(
            "invalid_carrier_secret",
            f"Send the secret we gave you for {carrier_code} as "
            f"Authorization: Bearer <secret>.",
        )


def already_there(conn: sqlite3.Connection, shipment_id: str, scan: CarrierScan) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM tracking_events WHERE shipment_id = ? AND code = ? AND occurred_at = ?",
            (shipment_id, scan.code, scan.occurred_at),
        ).fetchone()
        is not None
    )


@router.post(
    "/carriers/{carrier_code}/scans",
    response_model=ScanReceipt,
    summary="Record one scan against a parcel",
    operation_id="record_scan",
    responses=problem_responses(
        "invalid_carrier_secret", "not_found", "not_scannable", authenticated=False
    ),
)
def record_scan(
    carrier_code: str,
    scan: CarrierScan,
    authorization: Optional[str] = Header(default=None),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """One scan, matched to the parcel by tracking number.

    The same scan posted twice is recorded once. A scan that would wind a parcel backwards is
    kept but leaves the status where it is; a parcel that is finished with takes no more.
    """
    given = authorization[7:] if (authorization or "").lower().startswith("bearer ") else None
    check_secret(carrier_code, given)

    row = conn.execute(
        "SELECT * FROM shipments WHERE tracking_number = ? AND carrier_code = ?",
        (scan.tracking_number, carrier_code),
    ).fetchone()
    if row is None:
        raise QuillonError(
            "not_found", f"No parcel of ours on {carrier_code} with {scan.tracking_number}."
        )
    shipment = dict(row)
    if tracking.is_finished(shipment["status"]):
        raise QuillonError(
            "not_scannable",
            f"{scan.tracking_number} is {shipment['status']} and takes no more scans.",
        )
    if already_there(conn, shipment["id"], scan):
        return {"shipment_id": shipment["id"], "status": shipment["status"], "recorded": False}

    conn.execute(
        "INSERT INTO tracking_events (id, shipment_id, code, description, location, occurred_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            new_id("tracking_event"),
            shipment["id"],
            scan.code,
            scan.description or tracking.description_for(scan.code),
            scan.location or unpack(shipment["recipient"]).get("city", ""),
            scan.occurred_at,
        ),
    )

    status = shipment["status"]
    if tracking.moves_forward(status, scan.code):
        status = tracking.status_after(scan.code) or status
        column = STAMPS.get(status)
        if column:
            conn.execute(
                f"UPDATE shipments SET status = ?, {column} = ? WHERE id = ?",
                (status, scan.occurred_at, shipment["id"]),
            )
        else:
            conn.execute(
                "UPDATE shipments SET status = ? WHERE id = ?", (status, shipment["id"])
            )

    fresh = shipment_out(
        conn.execute("SELECT * FROM shipments WHERE id = ?", (shipment["id"],)).fetchone()
    )
    told = webhooks.summary(fresh)
    webhooks.queue(conn, shipment["customer_id"], "tracking.updated", told, shipment["id"])
    if status == "delivered" and shipment["status"] != "delivered":
        webhooks.queue(
            conn, shipment["customer_id"], "shipment.delivered", told, shipment["id"]
        )
    return {"shipment_id": shipment["id"], "status": status, "recorded": True}
