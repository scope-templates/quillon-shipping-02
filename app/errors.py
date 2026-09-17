"""Every refusal the API makes, and the problem object it goes out as."""

from typing import Any, Dict, Optional

# The section in the public docs that explains each code.
TYPE_BASE = "https://quillonpost.co.uk/docs/errors"

MEDIA_TYPE = "application/problem+json"

# code -> (HTTP status, title). A code never changes meaning once it has shipped.
PROBLEMS: Dict[str, Any] = {
    "missing_credentials": (401, "No API key on the request"),
    "invalid_key": (401, "That API key is not one of ours"),
    "account_closed": (401, "That account is closed"),
    "invalid_carrier_secret": (401, "That carrier secret is not one of ours"),
    "not_found": (404, "No such thing here"),
    "method_not_allowed": (405, "That is not something you can do to this path"),
    "validation_failed": (422, "The request body will not do"),
    "invalid_cursor": (422, "That cursor is not one we handed out"),
    "rate_unavailable": (422, "No carrier will take that parcel"),
    "quote_expired": (422, "That quote has run out"),
    "quote_not_found": (422, "No such quote"),
    "idempotency_conflict": (409, "That idempotency key was used on a different body"),
    "reference_in_use": (409, "That reference is on another shipment"),
    "not_cancellable": (409, "The parcel has gone too far to cancel"),
    "not_scannable": (409, "That parcel is not taking scans"),
    "label_unavailable": (409, "There is no label for this shipment"),
    "rate_limited": (429, "Too many requests"),
    "unexpected": (500, "Something went wrong at our end"),
}


def type_url(code: str) -> str:
    return f"{TYPE_BASE}#{code}"


class QuillonError(Exception):
    """A refusal on its way out. Routers raise it; one handler turns it into JSON."""

    def __init__(
        self,
        code: str,
        detail: str,
        extra: Optional[Dict[str, Any]] = None,
        status: Optional[int] = None,
    ):
        if code not in PROBLEMS:
            raise KeyError(f"{code} is not one of our error codes")
        self.code = code
        known_status, self.title = PROBLEMS[code]
        self.status = status or known_status
        self.detail = detail
        self.extra = dict(extra or {})
        super().__init__(f"{code}: {detail}")

    def body(self) -> Dict[str, Any]:
        out = {
            "type": type_url(self.code),
            "title": self.title,
            "status": self.status,
            "detail": self.detail,
            "code": self.code,
        }
        out.update(self.extra)
        return out


def example_for(code: str) -> Dict[str, Any]:
    """One problem object per code, for the spec."""
    status, title = PROBLEMS[code]
    return {
        "type": type_url(code),
        "title": title,
        "status": status,
        "detail": title,
        "code": code,
    }
