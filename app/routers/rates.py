"""Quoting a parcel before anybody commits to it."""

import sqlite3
from datetime import timedelta
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.auth import Caller, caller
from app.db import get_conn
from app.errors import QuillonError
from app.ids import new_id, now, stamp
from app.rates import chargeable_grams, is_postcode, quote_lines, tidy_postcode, zone_for
from app.schemas import QuoteRequest, QuoteSet, problem_responses

QUOTE_LIFETIME_MINUTES = 30

router = APIRouter(prefix="/v1", tags=["Rates"])


@router.post(
    "/rates/quotes",
    response_model=QuoteSet,
    summary="Price a parcel with every carrier that will take it",
    operation_id="quote_rates",
    responses=problem_responses("validation_failed", "rate_unavailable"),
)
def quote(
    body: QuoteRequest,
    who: Caller = Depends(caller),
    conn: sqlite3.Connection = Depends(get_conn),
) -> Dict[str, Any]:
    """Quotes for one parcel, cheapest first, at the price your plan pays.

    Quotes are held for half an hour and can be turned into a shipment by id, which is the only
    way to be sure the price a shopper saw at the checkout is the price we bill.
    """
    from_postcode = tidy_postcode(body.from_postcode)
    to_postcode = tidy_postcode(body.to_postcode)
    for label, value in (("from_postcode", from_postcode), ("to_postcode", to_postcode)):
        if not is_postcode(value):
            raise QuillonError(
                "validation_failed", f"{label} does not look like a UK postcode: {value}."
            )

    dimensions = body.dimensions_cm.as_tuple()
    lines = quote_lines(
        conn, from_postcode, to_postcode, body.weight_grams, dimensions, body.service, who.plan
    )
    if not lines:
        raise QuillonError(
            "rate_unavailable",
            "Nothing on our rate card will take that parcel to "
            f"{to_postcode}. Check the weight and the longest side, and the service if you "
            "asked for one.",
        )

    made = now()
    expires_at = stamp(made + timedelta(minutes=QUOTE_LIFETIME_MINUTES))
    quotes = []
    for line in lines:
        quote_id = new_id("quote")
        conn.execute(
            "INSERT INTO quotes (id, customer_id, mode, carrier_code, service, price_pence, "
            "estimated_days, from_postcode, to_postcode, weight_grams, dimensions_cm, "
            "created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                quote_id,
                who.customer_id,
                who.mode,
                line["carrier_code"],
                line["service"],
                line["price_pence"],
                line["estimated_days"],
                from_postcode,
                to_postcode,
                body.weight_grams,
                ",".join(str(side) for side in dimensions),
                stamp(made),
                expires_at,
            ),
        )
        quotes.append(
            {
                "id": quote_id,
                "carrier_code": line["carrier_code"],
                "carrier_name": line["carrier_name"],
                "service": line["service"],
                "price_pence": line["price_pence"],
                "estimated_days": line["estimated_days"],
                "expires_at": expires_at,
            }
        )

    return {
        "quotes": quotes,
        "zone": zone_for(to_postcode),
        "chargeable_weight_grams": chargeable_grams(body.weight_grams, dimensions),
    }
