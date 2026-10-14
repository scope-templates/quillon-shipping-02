"""Identifiers, tokens and the one way we write a time down."""

import secrets
from datetime import datetime, timezone

# No vowels, so nothing generated here can spell a word, and no character that gets misheard
# when an id is read out over the phone.
ALPHABET = "bcdfghjkmnpqrstvwxyz23456789"
BODY_LENGTH = 22
KEY_LENGTH = 24
SECRET_LENGTH = 32

PREFIXES = {
    "customer": "cus",
    "quote": "qt",
    "shipment": "shp",
    "tracking_event": "evt",
    "webhook_endpoint": "whe",
    "webhook_delivery": "whd",
    "webhook_event": "whev",
    "label": "lbl",
    "billing_event": "bev",
}


def token(length: int = BODY_LENGTH) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def new_id(kind: str) -> str:
    return f"{PREFIXES[kind]}_{token()}"


def api_key(mode: str) -> str:
    """A key as a shop sees it: qp_test_... on the sandbox, qp_live_... in anger."""
    if mode not in ("test", "live"):
        raise ValueError(f"{mode} is neither test nor live")
    return f"qp_{mode}_{token(KEY_LENGTH)}"


def tracking_number(prefix: str) -> str:
    """A carrier barcode number: their letters, then ten digits they gave us the block for."""
    digits = "".join(secrets.choice("0123456789") for _ in range(10))
    return f"{prefix}{digits}"


def webhook_secret() -> str:
    return f"whsec_{token(SECRET_LENGTH)}"


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    """UTC, seconds, a Z on the end. The only time format that leaves the building."""
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def now_stamp() -> str:
    return stamp(now())


def read_stamp(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
