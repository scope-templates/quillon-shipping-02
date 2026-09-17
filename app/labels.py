"""The label PDF and the link that serves it. A test key gets one marked SAMPLE."""

import json
import sqlite3
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.ids import new_id, now, read_stamp, stamp

LABEL_LIFETIME_HOURS = 24
FORMAT = "pdf"

# A thermal label: 420 by 595 points, which is A5 on its side and prints on A4 set to fit.
PAGE_WIDTH = 420
PAGE_HEIGHT = 595
MARGIN = 36

Line = Tuple[int, int, int, str]


def expiry_from(created: Optional[str] = None) -> str:
    moment = read_stamp(created) if created else now()
    return stamp(moment + timedelta(hours=LABEL_LIFETIME_HOURS))


def issue(conn: sqlite3.Connection, shipment: Dict[str, Any]) -> Dict[str, str]:
    """Hand out a token for this shipment, or refresh the one it has if it has run out."""
    token = shipment.get("label_token")
    expires_at = shipment.get("label_expires_at")
    if not token or not expires_at or read_stamp(expires_at) <= now():
        token = new_id("label")
        expires_at = expiry_from()
        conn.execute(
            "UPDATE shipments SET label_token = ?, label_expires_at = ? WHERE id = ?",
            (token, expires_at, shipment["id"]),
        )
        shipment["label_token"] = token
        shipment["label_expires_at"] = expires_at
    return {"token": token, "expires_at": expires_at}


def address_lines(recipient: Dict[str, Any]) -> List[str]:
    """Name, then whatever of the address is filled in, then the town."""
    wanted = ("company", "line1", "line2", "city")
    out = [recipient.get("name", "")]
    out.extend(str(recipient[field]) for field in wanted if recipient.get(field))
    return out


def check_inside(lines: List[Line]) -> None:
    """Nothing is allowed off the page; a label that will not print is worse than no label."""
    for x, y, size, _text in lines:
        if not MARGIN <= x <= PAGE_WIDTH - MARGIN:
            raise ValueError(f"x={x} is off a {PAGE_WIDTH} point page")
        if y < MARGIN or y + size > PAGE_HEIGHT - MARGIN:
            raise ValueError(f"y={y} with {size} point text is off a {PAGE_HEIGHT} point page")


def lay_out(shipment: Dict[str, Any], carrier_name: str) -> List[Line]:
    recipient = unpacked(shipment["recipient"])
    parcel = unpacked(shipment["parcel"])

    lines: List[Line] = [
        (MARGIN, 520, 18, carrier_name.upper()),
        (MARGIN, 496, 12, shipment["service"].replace("_", " ").title()),
    ]
    top = 452
    for row in address_lines(recipient)[:5]:
        lines.append((MARGIN, top, 11, row))
        top -= 16
    lines.append((MARGIN, top - 8, 16, recipient.get("postcode", "")))

    lines.append((MARGIN, 330, 10, f"Parcel {parcel.get('weight_grams', 0)} g"))
    lines.append((MARGIN, 280, 20, shipment["tracking_number"]))
    lines.append((MARGIN, 256, 9, f"Quillon Post - {shipment['id']}"))
    if shipment.get("mode") == "test":
        lines.append((MARGIN + 40, 150, 44, "SAMPLE"))

    check_inside(lines)
    return lines


def unpacked(value: Any) -> Dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else value


def pdf_bytes(shipment: Dict[str, Any], carrier_name: str) -> bytes:
    """The label itself. Built inline, so nothing has to be installed to print one."""
    body = ["BT"]
    for x, y, size, text in lay_out(shipment, carrier_name):
        body.append(f"/F1 {size} Tf 1 0 0 1 {x} {y} Tm ({escape(text)}) Tj")
    body.append("ET")
    stream = "\n".join(body).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] ".encode("ascii")
        + b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(number).encode("ascii") + b" 0 obj\n" + obj + b"\nendobj\n"
    start_xref = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode("ascii") + b"\n"
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode("ascii")
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(start_xref).encode("ascii") + b"\n%%EOF\n"
    )
    return bytes(out)


def escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
