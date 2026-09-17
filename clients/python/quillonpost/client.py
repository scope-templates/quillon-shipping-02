"""A small Python wrapper over the Quillon Post API.

    from quillonpost import QuillonClient

    with QuillonClient("qp_live_...") as post:
        quotes = post.quote(
            from_postcode="BS1 4DJ",
            to_postcode="EC2A 4NE",
            weight_grams=1800,
            dimensions_cm=(32, 24, 10),
        )
        parcel = post.create_shipment(
            quote_id=quotes[0]["id"],
            recipient={
                "name": "Joanne Bex",
                "line1": "18 Ravensbourne Terrace",
                "city": "London",
                "postcode": "EC2A 4NE",
            },
            parcel={"weight_grams": 1800, "dimensions_cm": (32, 24, 10)},
        )
        label = post.label(parcel["id"])
"""

from typing import Any, Dict, List, Optional, Sequence, Union

import httpx

from quillonpost.errors import QuillonError

DEFAULT_BASE_URL = "https://api.quillonpost.co.uk"
DEFAULT_TIMEOUT = 30.0

Dimensions = Union[Sequence[float], Dict[str, float]]


def as_dimensions(value: Dimensions) -> Dict[str, float]:
    """Length, width and height, given either as three numbers or as the API spells them."""
    if isinstance(value, dict):
        return dict(value)
    length, width, height = value
    return {"length_cm": length, "width_cm": width, "height_cm": height}


def as_parcel(parcel: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(parcel)
    if "dimensions_cm" in out:
        out["dimensions_cm"] = as_dimensions(out["dimensions_cm"])
    return out


class QuillonClient:
    """One shop's connection to the API. Hold on to it; it keeps a connection pool."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        session: Optional[httpx.Client] = None,
    ):
        if not api_key:
            raise ValueError("an API key is needed: qp_test_... or qp_live_...")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._owned = session is None
        self._session = session or httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------ plumbing

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

    def _call(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        answer = self._session.request(
            method,
            f"{self.base_url}{path}",
            params={key: value for key, value in (params or {}).items() if value is not None},
            json=body,
            headers=self._headers(),
        )
        if answer.status_code >= 400:
            raise QuillonError.from_response(answer)
        if answer.status_code == 204 or not answer.content:
            return None
        return answer.json()

    def close(self) -> None:
        if self._owned:
            self._session.close()

    def __enter__(self) -> "QuillonClient":
        return self

    def __exit__(self, *_details: Any) -> None:
        self.close()

    # --------------------------------------------------------------------- rates

    def quote(
        self,
        from_postcode: str,
        to_postcode: str,
        weight_grams: int,
        dimensions_cm: Dimensions,
        service: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Prices for one parcel, cheapest first. Each quote holds for half an hour."""
        answer = self._call(
            "POST",
            "/v1/rates/quotes",
            body={
                "from_postcode": from_postcode,
                "to_postcode": to_postcode,
                "weight_grams": weight_grams,
                "dimensions_cm": as_dimensions(dimensions_cm),
                "service": service,
            },
        )
        return answer["quotes"]

    def carriers(self) -> List[Dict[str, Any]]:
        """The carriers on the account and the services they sell."""
        return self._call("GET", "/v1/carriers")["data"]

    # ----------------------------------------------------------------- shipments

    def create_shipment(
        self,
        recipient: Dict[str, Any],
        parcel: Dict[str, Any],
        quote_id: Optional[str] = None,
        carrier_code: Optional[str] = None,
        service: Optional[str] = None,
        sender: Optional[Dict[str, Any]] = None,
        reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Book a parcel, either on a quote or by naming a carrier and a service."""
        body: Dict[str, Any] = {"recipient": recipient, "parcel": as_parcel(parcel)}
        for name, value in (
            ("quote_id", quote_id),
            ("carrier_code", carrier_code),
            ("service", service),
            ("sender", sender),
            ("reference", reference),
        ):
            if value is not None:
                body[name] = value
        return self._call("POST", "/v1/shipments", body=body)

    def get_shipment(self, shipment_id: str) -> Dict[str, Any]:
        return self._call("GET", f"/v1/shipments/{shipment_id}")

    def list_shipments(
        self,
        status: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """One page of shipments, newest first, with next_cursor for the page after it."""
        return self._call(
            "GET",
            "/v1/shipments",
            params={"status": status, "cursor": cursor, "limit": limit},
        )

    def label(self, shipment_id: str) -> Dict[str, Any]:
        """The link to the label PDF, and when the link runs out."""
        return self._call("POST", f"/v1/shipments/{shipment_id}/label")
