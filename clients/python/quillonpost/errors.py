"""The one exception this package raises."""

from typing import Any, Dict, Optional


class QuillonError(Exception):
    """A refusal from Quillon Post, with the problem object's fields on it.

    The code is the part worth branching on; it is stable across versions of the API.
    """

    def __init__(
        self,
        code: str,
        detail: str,
        status: int,
        title: str = "",
        body: Optional[Dict[str, Any]] = None,
    ):
        self.code = code
        self.detail = detail
        self.status = status
        self.title = title
        self.body = body or {}
        super().__init__(f"{code}: {detail}")

    @classmethod
    def from_response(cls, response: Any) -> "QuillonError":
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        return cls(
            code=body.get("code", "unexpected"),
            detail=body.get("detail", response.text[:200]),
            status=body.get("status", response.status_code),
            title=body.get("title", ""),
            body=body,
        )
