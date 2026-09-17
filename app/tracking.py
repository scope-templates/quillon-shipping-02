"""Statuses, the scan codes the four carriers are mapped onto, and what may still be stopped."""

from typing import Dict, Optional, Sequence, Tuple

STATUSES = (
    "created",
    "collected",
    "in_transit",
    "out_for_delivery",
    "delivered",
    "held",
    "returned",
    "cancelled",
)

# A parcel is ours to stop until a driver has it. After that it belongs to the carrier.
CANCELLABLE_FROM = ("created",)

FINISHED = ("delivered", "returned", "cancelled")

# code -> the words we put in front of a shopper, and the status the code moves a parcel to.
EVENT_CODES: Dict[str, Tuple[str, Optional[str]]] = {
    "label_created": ("Label created", "created"),
    "collected": ("Collected from sender", "collected"),
    "at_origin_depot": ("At origin depot", "in_transit"),
    "in_transit": ("In transit", "in_transit"),
    "at_delivery_depot": ("At delivery depot", "in_transit"),
    "out_for_delivery": ("Out for delivery", "out_for_delivery"),
    "delivery_attempted": ("Delivery attempted, card left", "held"),
    "held_at_depot": ("Held at depot", "held"),
    "address_query": ("Held, address query with the sender", "held"),
    "delivered": ("Delivered", "delivered"),
    "returned_to_sender": ("Returned to sender", "returned"),
    "cancelled": ("Cancelled before collection", "cancelled"),
}

# The ordinary run of a parcel that goes nowhere unusual.
HAPPY_PATH: Sequence[str] = (
    "label_created",
    "collected",
    "at_origin_depot",
    "in_transit",
    "at_delivery_depot",
    "out_for_delivery",
    "delivered",
)


def description_for(code: str) -> str:
    return EVENT_CODES[code][0]


def status_after(code: str) -> Optional[str]:
    return EVENT_CODES[code][1]


def is_finished(status: str) -> bool:
    return status in FINISHED


def rank_of(code: str) -> Optional[int]:
    """Where a code sits on the ordinary run of a parcel, or None if it is off it."""
    return HAPPY_PATH.index(code) if code in HAPPY_PATH else None


def moves_forward(status: str, code: str) -> bool:
    """Carriers repeat and re-order scans. A scan that would wind the parcel back is recorded
    but does not move the status."""
    coming = rank_of(code)
    if coming is None:
        return True
    for standing, name in enumerate(HAPPY_PATH):
        if status_after(name) == status and standing > coming:
            return False
    return True


def can_cancel(status: str) -> bool:
    return status in CANCELLABLE_FROM


def refusal_for(status: str) -> str:
    """Why a cancel was turned down, in words a shop can put in front of a customer."""
    if status == "cancelled":
        return "This shipment was already cancelled."
    if status == "delivered":
        return "This parcel has been delivered."
    if status == "returned":
        return "This parcel has been returned to the sender."
    return (
        f"This parcel is {status.replace('_', ' ')} and the carrier has it. Ask the recipient to "
        "refuse the delivery, and it will come back to you."
    )
