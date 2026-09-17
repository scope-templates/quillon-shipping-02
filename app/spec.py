"""The OpenAPI document: what FastAPI works out, plus what a route cannot say for itself."""

from typing import Any, Dict

from app import API_VERSION
from app.errors import MEDIA_TYPE, example_for
from app.idempotency import REPLAY_HEADER
from app.schemas import Problem
from app.throttle import LIMIT_HEADER, LIMITS, REMAINING_HEADER, RESET_HEADER
from app.webhooks import EVENT_TYPES, SIGNATURE_HEADER, TOLERANCE_SECONDS

VERSION_HEADER = "Quillon-Version"
# The delivery of the parcel the public docs follow, signed at the moment it arrived.
SIGNATURE_EXAMPLE = (
    "t=1785928804,"
    "v1=6f0c1e1b0b0bb61e0dc63f0f9b6b0a7c9b1f2a4e7d8c0b5a3e2d1c0b9a8f7e6d"
)
RATE_LIMITED = "#/components/responses/RateLimited"
PROBLEM_SCHEMA = "#/components/schemas/Problem"

# Routes that take Idempotency-Key, and so can answer with a replay.
IDEMPOTENT = {
    ("/v1/shipments", "post"),
    ("/v1/shipments/{shipment_id}/cancel", "post"),
    ("/v1/webhooks", "post"),
}

# FastAPI puts these in for the 422 it would raise itself. Ours is a problem object, so they
# have nothing to describe.
UNUSED_SCHEMAS = ("HTTPValidationError", "ValidationError")


def header(description: str, example: Any, kind: str = "string") -> Dict[str, Any]:
    return {
        "description": description,
        "schema": {"type": kind, "examples": [example]},
    }


def common_headers(on_v1: bool) -> Dict[str, Any]:
    headers = {
        VERSION_HEADER: header("The dated version this deployment speaks.", API_VERSION),
    }
    if on_v1:
        headers[LIMIT_HEADER] = header(
            "Requests allowed on this key in a minute.", LIMITS["live"], "integer"
        )
        headers[REMAINING_HEADER] = header(
            "What is left of the limit in this minute.", 573, "integer"
        )
        headers[RESET_HEADER] = header(
            "Unix seconds at which the minute turns over.", 1788080460, "integer"
        )
    return headers


def rate_limited_response() -> Dict[str, Any]:
    return {
        "description": "Too many requests on this key this minute.",
        "headers": common_headers(True),
        "content": {
            MEDIA_TYPE: {
                "schema": {"$ref": PROBLEM_SCHEMA},
                "example": example_for("rate_limited"),
            }
        },
    }


def webhook_block() -> Dict[str, Any]:
    """What we post to an endpoint, described where a reader looks for it."""
    return {
        "shipment_event": {
            "post": {
                "summary": "A delivery to a registered endpoint",
                "description": (
                    "Posted to every endpoint listening for the event. Signed with the "
                    f"endpoint secret in `{SIGNATURE_HEADER}`; refuse a signature more than "
                    f"{TOLERANCE_SECONDS} seconds old. Answer with any 2xx."
                ),
                "operationId": "receiveShipmentEvent",
                "parameters": [
                    {
                        "name": SIGNATURE_HEADER,
                        "in": "header",
                        "required": True,
                        "description": "t=<unix seconds>,v1=<hex hmac-sha256>",
                        "schema": {
                            "type": "string",
                            "examples": [SIGNATURE_EXAMPLE],
                        },
                    }
                ],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id", "type", "created_at", "data"],
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "examples": ["whev_hjgktwzmmpdbnyzpmptfk9"],
                                    },
                                    "type": {"type": "string", "enum": list(EVENT_TYPES)},
                                    "created_at": {"type": "string"},
                                    "data": {"type": "object"},
                                },
                            }
                        }
                    },
                },
                "responses": {"2XX": {"description": "Taken. Anything else is retried."}},
            }
        }
    }


def decorate(spec: Dict[str, Any]) -> Dict[str, Any]:
    components = spec.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas["Problem"] = Problem.model_json_schema()
    for name in UNUSED_SCHEMAS:
        schemas.pop(name, None)
    components.setdefault("responses", {})["RateLimited"] = rate_limited_response()

    for path, operations in spec.get("paths", {}).items():
        on_v1 = path.startswith("/v1")
        for method, operation in operations.items():
            responses = operation.get("responses", {})
            if "429" in responses:
                responses["429"] = {"$ref": RATE_LIMITED}
            for status, answer in responses.items():
                if "$ref" in answer:
                    continue
                headers = dict(common_headers(on_v1))
                if (path, method) in IDEMPOTENT and status in ("200", "201"):
                    headers[REPLAY_HEADER] = header(
                        "true when this is the answer to an earlier call with the same key.",
                        "true",
                    )
                answer.setdefault("headers", {}).update(headers)

    spec["webhooks"] = webhook_block()
    return spec


def install(app) -> None:
    """Wrap the app's own generator so /openapi.json and the committed file are one document."""
    base = app.openapi

    def openapi() -> Dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        app.openapi_schema = decorate(base())
        return app.openapi_schema

    app.openapi = openapi
