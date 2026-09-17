"""Cursor paging: newest first, the cursor being the last row's sort key in url-safe base64."""

import base64
import binascii
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.errors import QuillonError

DEFAULT_LIMIT = 25
MAX_LIMIT = 100
SEPARATOR = "|"


def check_limit(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    if limit < 1 or limit > MAX_LIMIT:
        raise QuillonError(
            "validation_failed",
            f"limit has to be between 1 and {MAX_LIMIT}; you sent {limit}.",
        )
    return limit


def encode_cursor(created_at: str, row_id: str) -> str:
    raw = f"{created_at}{SEPARATOR}{row_id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> Tuple[str, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise QuillonError(
            "invalid_cursor",
            "Pass back the next_cursor exactly as we sent it, or leave cursor off for the "
            "first page.",
        ) from None
    created_at, found, row_id = raw.partition(SEPARATOR)
    if not found or not created_at or not row_id:
        raise QuillonError(
            "invalid_cursor",
            "Pass back the next_cursor exactly as we sent it, or leave cursor off for the "
            "first page.",
        )
    return created_at, row_id


def after_clause(cursor: Optional[str]) -> Tuple[str, List[Any]]:
    """The SQL that puts us back where the last page stopped."""
    if not cursor:
        return "", []
    created_at, row_id = decode_cursor(cursor)
    return " AND (created_at, id) < (?, ?)", [created_at, row_id]


def page(rows: Sequence[Dict[str, Any]], limit: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Trim the one extra row the query asked for and turn it into the next cursor."""
    rows = list(rows)
    if len(rows) <= limit:
        return rows, None
    kept = rows[:limit]
    last = kept[-1]
    return kept, encode_cursor(last["created_at"], last["id"])
