"""The app: the headers on every response, and the handlers that shape every refusal."""

import sqlite3
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import API_VERSION, SERVICE_VERSION, spec, throttle
from app.auth import mode_of
from app.db import connect, get_conn, open_store
from app.errors import MEDIA_TYPE, QuillonError
from app.routers import (
    billing,
    carriers,
    labels,
    rates,
    scans,
    shipments,
    signups,
    webhooks,
)
from app.schemas import Health

VERSION_HEADER = "Quillon-Version"
COUNTED_PREFIX = "/v1"

DESCRIPTION = """
Parcel shipping for online shops. Ask for rates, book the parcel, print the label and follow it
to the door; we hand it to one of four carriers and keep the tracking in one shape.

Send your API key as `Authorization: Bearer qp_live_...`. Keys that start with `qp_test_` book
parcels that no van ever collects, and their labels come back marked SAMPLE.

Dates in this API are UTC. Money is in pence, weight in grams, lengths in centimetres.
"""

TAGS = [
    {"name": "Rates", "description": "What a parcel costs with each carrier that will take it."},
    {"name": "Shipments", "description": "Booking a parcel, the label, the cancel, the tracking."},
    {"name": "Webhooks", "description": "Being told about a parcel instead of asking."},
    {"name": "Carriers", "description": "Who we route to and what they sell."},
    {"name": "Labels", "description": "The PDF behind a label link."},
    {"name": "Signups", "description": "A new shop from the form on the website."},
    {"name": "Service", "description": "Is it up."},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    open_store()
    yield


app = FastAPI(
    title="Quillon Post API",
    version=API_VERSION,
    description=DESCRIPTION.strip(),
    openapi_tags=TAGS,
    contact={"name": "Quillon Post support", "email": "support@quillonpost.co.uk"},
    servers=[{"url": "https://api.quillonpost.co.uk", "description": "Live"}],
    lifespan=lifespan,
)


def problem_response(error: QuillonError) -> JSONResponse:
    return JSONResponse(error.body(), status_code=error.status, media_type=MEDIA_TYPE)


@app.exception_handler(QuillonError)
async def refused(request: Request, error: QuillonError) -> JSONResponse:
    return problem_response(error)


@app.exception_handler(RequestValidationError)
async def malformed(request: Request, error: RequestValidationError) -> JSONResponse:
    """Pydantic's complaints, said in our own shape so shops only parse one thing."""
    first = error.errors()[0] if error.errors() else {}
    where = ".".join(str(part) for part in first.get("loc", ())[1:]) or "the body"
    detail = f"{where}: {first.get('msg', 'will not do')}."
    return problem_response(QuillonError("validation_failed", detail))


@app.exception_handler(StarletteHTTPException)
async def not_there(request: Request, error: StarletteHTTPException) -> JSONResponse:
    """Starlette's own refusals, said in our shape so shops only ever parse one thing."""
    if error.status_code == 405:
        return problem_response(
            QuillonError(
                "method_not_allowed",
                f"{request.method} is not something you can do to {request.url.path}.",
            )
        )
    if error.status_code == 404:
        return problem_response(
            QuillonError("not_found", f"There is nothing at {request.url.path}.")
        )
    return problem_response(
        QuillonError("unexpected", str(error.detail), status=error.status_code)
    )


def counted_as(request: Request):
    """Which bucket this call comes out of, and how much that bucket is allowed.

    A key only counts as itself once it names an open account, trialling or not: anything else,
    whatever it is prefixed with, is counted against the address it arrived from.
    """
    header = request.headers.get("authorization", "")
    key = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if key and mode_of(key):
        conn = connect()
        try:
            row = conn.execute(
                "SELECT k.mode FROM api_keys k JOIN customers c ON c.id = k.customer_id "
                "WHERE k.key = ? AND c.status != 'closed'",
                (key,),
            ).fetchone()
        finally:
            conn.close()
        if row is not None:
            return key, throttle.limit_for(row["mode"])
    where = request.client.host if request.client else "unknown"
    return f"anonymous:{where}", throttle.ANONYMOUS_LIMIT


@app.middleware("http")
async def stamp_and_count(request: Request, call_next):
    """Version and rate-limit headers on the way out, and the counter on the way in."""
    bucket = None
    limit = throttle.ANONYMOUS_LIMIT
    if request.url.path.startswith(COUNTED_PREFIX):
        bucket, limit = counted_as(request)

    if bucket is not None:
        allowed, remaining, resets_at = throttle.take(bucket, limit)
        if not allowed:
            error = QuillonError(
                "rate_limited",
                f"More than {limit} requests in a minute on this key. Try again at the time in "
                f"{throttle.RESET_HEADER}.",
            )
            response = problem_response(error)
        else:
            response = await call_next(request)
        response.headers[throttle.LIMIT_HEADER] = str(limit)
        response.headers[throttle.REMAINING_HEADER] = str(remaining)
        response.headers[throttle.RESET_HEADER] = str(resets_at)
    else:
        response = await call_next(request)

    response.headers[VERSION_HEADER] = API_VERSION
    return response


@app.get(
    "/health",
    response_model=Health,
    tags=["Service"],
    summary="Is the service up",
    operation_id="health",
)
def health(conn: sqlite3.Connection = Depends(get_conn)) -> Dict[str, Any]:
    """No key needed. This is what the load balancer polls."""
    booked = conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
    return {
        "status": "ok",
        "version": API_VERSION,
        "build": SERVICE_VERSION,
        "shipments": booked,
    }


app.include_router(rates.router)
app.include_router(shipments.router)
app.include_router(webhooks.router)
app.include_router(carriers.router)
app.include_router(labels.router)
app.include_router(signups.router)
app.include_router(scans.router)
app.include_router(billing.router)

spec.install(app)
