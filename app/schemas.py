"""The shapes that go in and out. Money is pence, weight grams, length centimetres."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.billing import EVENT_TYPES as BILLING_EVENT_TYPES
from app.billing import STATUSES as SUBSCRIPTION_STATUSES
from app.errors import MEDIA_TYPE, PROBLEMS, example_for
from app.plans import PLANS
from app.rates import ZONES
from app.tracking import EVENT_CODES, STATUSES
from app.webhooks import EVENT_TYPES

Mode = Literal["test", "live"]


class Problem(BaseModel):
    """Every refusal the API makes looks like this."""

    type: str = Field(description="A link to the page in our docs about this code.")
    title: str
    status: int
    detail: str = Field(description="What went wrong with this particular request.")
    code: str = Field(description="The stable name for the refusal. Branch on this.")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "https://quillonpost.co.uk/docs/errors#not_cancellable",
                "title": "The parcel has gone too far to cancel",
                "status": 409,
                "detail": "This parcel is in transit and the carrier has it.",
                "code": "not_cancellable",
            }
        }
    )


class Dimensions(BaseModel):
    length_cm: float = Field(gt=0, le=300)
    width_cm: float = Field(gt=0, le=300)
    height_cm: float = Field(gt=0, le=300)

    def as_tuple(self) -> tuple:
        return (self.length_cm, self.width_cm, self.height_cm)


class Address(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    company: Optional[str] = Field(default=None, max_length=120)
    line1: str = Field(min_length=1, max_length=160)
    line2: Optional[str] = Field(default=None, max_length=160)
    city: str = Field(min_length=1, max_length=80)
    postcode: str = Field(min_length=5, max_length=9)
    country: str = Field(default="GB", min_length=2, max_length=2)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[EmailStr] = None


class Parcel(BaseModel):
    weight_grams: int = Field(gt=0, le=60000)
    dimensions_cm: Dimensions
    description: Optional[str] = Field(default=None, max_length=120)


class QuoteRequest(BaseModel):
    from_postcode: str = Field(min_length=5, max_length=9)
    to_postcode: str = Field(min_length=5, max_length=9)
    weight_grams: int = Field(gt=0, le=60000)
    dimensions_cm: Dimensions
    service: Optional[str] = Field(
        default=None, description="Ask for one service by name instead of all of them."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "from_postcode": "BS1 4DJ",
                "to_postcode": "EC2A 4NE",
                "weight_grams": 1800,
                "dimensions_cm": {"length_cm": 32, "width_cm": 24, "height_cm": 10},
            }
        }
    )


class Quote(BaseModel):
    id: str
    carrier_code: str
    carrier_name: str
    service: str
    price_pence: int
    estimated_days: int
    expires_at: str


class QuoteSet(BaseModel):
    quotes: List[Quote]
    zone: Literal[ZONES]  # type: ignore[valid-type]
    chargeable_weight_grams: int = Field(
        description="The greater of what the parcel weighs and what its size comes to."
    )


class ShipmentRequest(BaseModel):
    sender: Optional[Address] = Field(
        default=None,
        description="Leave it out and we use the dispatch address held on your account.",
    )
    recipient: Address
    parcel: Parcel
    quote_id: Optional[str] = Field(
        default=None, description="A quote from /v1/rates/quotes, taken as priced."
    )
    carrier_code: Optional[str] = None
    service: Optional[str] = None
    reference: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Your own order number. We keep it unique per account.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "quote_id": "qt_r2fd29gwz5zgtd3nznjbtc",
                "reference": "WEB-10482",
                "recipient": {
                    "name": "Joanne Bex",
                    "line1": "18 Ravensbourne Terrace",
                    "city": "London",
                    "postcode": "EC2A 4NE",
                    "phone": "07700 900412",
                },
                "parcel": {
                    "weight_grams": 1800,
                    "dimensions_cm": {"length_cm": 32, "width_cm": 24, "height_cm": 10},
                    "description": "Two glazed bowls",
                },
            }
        }
    )


class Shipment(BaseModel):
    id: str
    mode: Mode
    status: Literal[STATUSES]  # type: ignore[valid-type]
    carrier_code: str
    service: str
    tracking_number: str
    price_pence: int
    reference: Optional[str] = None
    quote_id: Optional[str] = None
    sender: Address
    recipient: Address
    parcel: Parcel
    created_at: str
    collected_at: Optional[str] = None
    delivered_at: Optional[str] = None
    cancelled_at: Optional[str] = None


class ShipmentPage(BaseModel):
    data: List[Shipment]
    next_cursor: Optional[str] = Field(
        default=None, description="Pass this back as ?cursor= for the next page."
    )


class Label(BaseModel):
    url: str
    format: Literal["pdf"]
    expires_at: str
    tracking_number: str


class TrackingEvent(BaseModel):
    code: str
    description: str
    location: str
    occurred_at: str


class TrackingEvents(BaseModel):
    data: List[TrackingEvent]
    status: Literal[STATUSES]  # type: ignore[valid-type]


class WebhookRequest(BaseModel):
    url: str = Field(min_length=8, max_length=400)
    events: List[Literal[EVENT_TYPES]] = Field(min_length=1)  # type: ignore[valid-type]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://yourshop.co.uk/hooks/quillon",
                "events": ["shipment.delivered", "tracking.updated"],
            }
        }
    )


class ListedEndpoint(BaseModel):
    """An endpoint as it comes back from the list. The secret is not on it."""

    id: str
    url: str
    events: List[str]
    status: str
    created_at: str


class WebhookEndpoint(ListedEndpoint):
    secret: str = Field(description="Shown once, when the endpoint is created. Keep it.")


class WebhookEndpoints(BaseModel):
    data: List[ListedEndpoint]


class CarrierService(BaseModel):
    service: str
    name: str
    description: str
    max_grams: int


class Carrier(BaseModel):
    code: str
    name: str
    collection_cutoff: str
    services: List[CarrierService]


class Carriers(BaseModel):
    data: List[Carrier]


class CarrierScan(BaseModel):
    """One scan as a carrier posts it to us."""

    tracking_number: str = Field(min_length=6, max_length=40)
    code: Literal[tuple(EVENT_CODES)]  # type: ignore[valid-type]
    occurred_at: str = Field(description="When the scan happened, UTC, ISO 8601.")
    location: Optional[str] = Field(default=None, max_length=80)
    description: Optional[str] = Field(
        default=None, max_length=160, description="Their wording. Ours is used if this is left out."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "tracking_number": "WDV4471029358",
                "code": "out_for_delivery",
                "occurred_at": "2026-08-15T07:11:00Z",
                "location": "London",
            }
        }
    )


class ScanReceipt(BaseModel):
    shipment_id: str
    status: Literal[STATUSES]  # type: ignore[valid-type]
    recorded: bool = Field(description="False when this scan was already on the parcel.")


class AccountMonth(BaseModel):
    """The calendar month so far, UTC, on the mode of the key that asked."""

    month: str = Field(description="Which month, as 2026-08.")
    parcels: int = Field(description="Parcels booked this month and not cancelled.")
    spend_pence: int = Field(description="What those parcels cost, at the plan's prices.")
    last_booked_at: Optional[str] = Field(
        default=None, description="The latest of them, or null when the month has none."
    )


class Account(BaseModel):
    """One account as its own key sees it."""

    id: str
    name: str
    platform: str
    mode: Mode
    plan: Literal[tuple(PLANS)]  # type: ignore[valid-type]
    status: Literal[SUBSCRIPTION_STATUSES]  # type: ignore[valid-type]
    current_period_start: str
    current_period_end: str
    trial_ends_at: Optional[str] = None
    this_month: AccountMonth


class SignupRequest(BaseModel):
    """What the form on the website asks a shop for."""

    shop_name: str = Field(min_length=1, max_length=120)
    contact_email: EmailStr
    platform: str = Field(
        min_length=1,
        max_length=40,
        description="What the shop's checkout runs on, or `own build`.",
    )
    city: str = Field(min_length=1, max_length=80)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "shop_name": "Saltmarsh Woollens",
                "contact_email": "hello@saltmarshwoollens.co.uk",
                "platform": "marketside",
                "city": "Saltmarsh",
            }
        }
    )


class Customer(BaseModel):
    id: str
    name: str
    platform: str
    city: str
    contact_email: str
    status: Literal["trialling", "active", "closed"]
    created_at: str


class Subscription(BaseModel):
    plan: Literal[tuple(PLANS)]  # type: ignore[valid-type]
    status: Literal[SUBSCRIPTION_STATUSES]  # type: ignore[valid-type]
    monthly_fee_pence: int
    current_period_start: str
    current_period_end: str
    trial_ends_at: Optional[str] = None
    started_at: str
    cancelled_at: Optional[str] = None


class Signup(BaseModel):
    customer: Customer
    subscription: Subscription
    key: str = Field(description="A qp_test_ key, shown once, here. Keep it.")


class BillingEventData(BaseModel):
    """What the provider sends with an event. Everything in it is kept as it came."""

    plan: Optional[Literal[tuple(PLANS)]] = Field(  # type: ignore[valid-type]
        default=None, description="The plan the shop is on now, on a start and on a plan change."
    )

    model_config = ConfigDict(extra="allow")

    def as_sent(self) -> Dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class BillingEvent(BaseModel):
    """One event as the billing provider posts it to us."""

    type: Literal[BILLING_EVENT_TYPES]  # type: ignore[valid-type]
    customer_id: str = Field(min_length=4, max_length=40, description="Our id for the shop.")
    occurred_at: str = Field(description="When it happened at the provider, UTC, ISO 8601.")
    data: BillingEventData = Field(default_factory=BillingEventData)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "type": "subscription.plan_changed",
                "customer_id": "cus_wq7tbkx4mdz2hy9vcnrfgp",
                "occurred_at": "2026-08-12T10:04:31Z",
                "data": {"from_plan": "payg", "plan": "standard"},
            }
        }
    )


class BillingReceipt(BaseModel):
    id: str = Field(description="Our id for the event, which is kept whatever it does.")
    customer_id: str
    plan: Optional[Literal[tuple(PLANS)]] = None  # type: ignore[valid-type]
    status: Optional[Literal[SUBSCRIPTION_STATUSES]] = None  # type: ignore[valid-type]
    moved: bool = Field(
        description="False when the event left the subscription where it was: older than one "
        "we already hold, after a cancellation, or saying what it already says."
    )


class Health(BaseModel):
    status: str
    version: str
    build: str
    shipments: int


AUTH_CODES = ("missing_credentials", "invalid_key", "account_closed")


def problem_responses(*codes: str, authenticated: bool = True) -> Dict[int, Dict[str, Any]]:
    """The responses block a route hangs on itself so the reference lists its refusals."""
    wanted = list(codes)
    if authenticated:
        wanted = list(AUTH_CODES) + ["rate_limited"] + wanted
    out: Dict[int, Dict[str, Any]] = {}
    for code in wanted:
        status, title = PROBLEMS[code]
        entry = out.setdefault(
            status,
            {
                "description": title,
                "content": {
                    MEDIA_TYPE: {
                        "schema": {"$ref": "#/components/schemas/Problem"},
                        "examples": {},
                    }
                },
            },
        )
        entry["content"][MEDIA_TYPE]["examples"][code] = {
            "summary": title,
            "value": example_for(code),
        }
    return out
