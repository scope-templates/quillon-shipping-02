"""Idempotency-Key on the mutating POSTs: same key and body, same answer; kept per customer."""

import hashlib
import json
import sqlite3
from typing import Any, Dict, Optional, Tuple

from app.errors import QuillonError
from app.ids import now_stamp

HEADER = "Idempotency-Key"
REPLAY_HEADER = "Quillon-Idempotent-Replay"
MAX_KEY_LENGTH = 255


def body_hash(body: Any) -> str:
    packed = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()


def check_key(key: Optional[str]) -> Optional[str]:
    if key is None:
        return None
    key = key.strip()
    if not key:
        return None
    if len(key) > MAX_KEY_LENGTH:
        raise QuillonError(
            "validation_failed",
            f"{HEADER} has to be {MAX_KEY_LENGTH} characters or fewer.",
        )
    return key


def look_back(
    conn: sqlite3.Connection,
    customer_id: str,
    key: Optional[str],
    method: str,
    path: str,
    body: Any,
) -> Optional[Tuple[int, Dict[str, Any]]]:
    """The first answer, if this key has been here before. Raises when the body has changed."""
    if key is None:
        return None
    row = conn.execute(
        "SELECT method, path, body_hash, status_code, response_body, created_at "
        "FROM idempotency_keys WHERE customer_id = ? AND key = ?",
        (customer_id, key),
    ).fetchone()
    if row is None:
        return None
    if row["method"] != method or row["path"] != path or row["body_hash"] != body_hash(body):
        raise QuillonError(
            "idempotency_conflict",
            f"{HEADER} {key} was used on {row['method']} {row['path']} at {row['created_at']} "
            "with a different body. Use a fresh key for a different request.",
        )
    return row["status_code"], json.loads(row["response_body"])


def remember(
    conn: sqlite3.Connection,
    customer_id: str,
    key: Optional[str],
    method: str,
    path: str,
    body: Any,
    status_code: int,
    response: Dict[str, Any],
) -> None:
    if key is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO idempotency_keys "
        "(customer_id, key, method, path, body_hash, status_code, response_body, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            customer_id,
            key,
            method,
            path,
            body_hash(body),
            status_code,
            json.dumps(response, separators=(",", ":"), default=str),
            now_stamp(),
        ),
    )
