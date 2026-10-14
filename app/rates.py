"""The rate card: zone from the postcode, band from the weight, price from the two."""

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.plans import TRIAL_PLAN, parcel_price

# Outward code areas that are not simply "the mainland". Everything else falls to mainland.
LONDON_AREAS = ("EC", "WC", "E", "N", "NW", "SE", "SW", "W")
HIGHLAND_AREAS = ("AB", "IV", "KW", "PA", "PH")
ISLAND_AREAS = ("HS", "ZE", "IM", "JE", "GY", "BT")

ZONES = ("london", "mainland", "highlands", "islands")

# Anything longer than this on one side goes on a pallet, which is not something we sell.
LONGEST_SIDE_CM = 120
VOLUMETRIC_DIVISOR = 5000
BANDS = (1000, 2000, 5000, 10000, 20000, 30000)

CARRIERS: Sequence[Dict[str, Any]] = (
    {
        "code": "northgate",
        "name": "Northgate Express",
        "collection_cutoff": "16:30",
        "tracking_prefix": "NGE",
    },
    {
        "code": "kestrel",
        "name": "Kestrel Parcels",
        "collection_cutoff": "15:00",
        "tracking_prefix": "KST",
    },
    {
        "code": "wendover",
        "name": "Wendover",
        "collection_cutoff": "14:00",
        "tracking_prefix": "WDV",
    },
    {
        "code": "bluecoat",
        "name": "Bluecoat Couriers",
        "collection_cutoff": "11:00",
        "tracking_prefix": "BCC",
    },
)

# carrier, service, public name, what it is, the zones it covers, the heaviest parcel it takes,
# the price of the first kilo, what each band above that adds, and days on the mainland.
SERVICES: Sequence[Tuple[str, str, str, str, Tuple[str, ...], int, int, int, int]] = (
    ("northgate", "next_day", "Northgate Next Day",
     "Collected by half four, delivered the next working day.",
     ("london", "mainland"), 30000, 649, 185, 1),
    ("northgate", "standard", "Northgate Standard",
     "Two to three working days, and the workhorse of the four.",
     ("london", "mainland", "highlands"), 30000, 389, 120, 2),
    ("kestrel", "standard", "Kestrel Standard",
     "Two working days to most addresses, longer past Inverness.",
     ("london", "mainland", "highlands", "islands"), 20000, 415, 135, 2),
    ("kestrel", "two_day", "Kestrel Two Day",
     "A dated two-day service with a booked collection slot.",
     ("london", "mainland"), 20000, 520, 150, 2),
    ("wendover", "economy", "Wendover Economy",
     "Three to five working days. The cheapest thing we can put a parcel on.",
     ("london", "mainland", "highlands"), 15000, 299, 96, 3),
    ("bluecoat", "next_day", "Bluecoat Next Day",
     "Next working day, with a photograph on delivery.",
     ("london", "mainland"), 10000, 695, 210, 1),
    ("bluecoat", "before_noon", "Bluecoat Before Noon",
     "Next working day before twelve, inside the M25 only.",
     ("london",), 10000, 949, 260, 1),
)

# What the carriers charge us on top for a zone, and how many days it adds.
ZONE_LOADING = {
    "london": (1.06, 0),
    "mainland": (1.00, 0),
    "highlands": (1.34, 2),
    "islands": (1.62, 3),
}

POSTCODE = re.compile(r"^[A-Z]{1,2}[0-9][A-Z0-9]?\s*[0-9][A-Z]{2}$")


def tidy_postcode(value: str) -> str:
    """Upper case, one space before the inward code. What we store and what we quote on."""
    squashed = re.sub(r"\s+", "", (value or "")).upper()
    if len(squashed) < 5:
        return squashed
    return f"{squashed[:-3]} {squashed[-3:]}"


def is_postcode(value: str) -> bool:
    return bool(POSTCODE.match(tidy_postcode(value)))


def area_of(postcode: str) -> str:
    """The letters at the front of the outward code: BS, EC, IV."""
    outward = tidy_postcode(postcode).split(" ")[0]
    letters = ""
    for character in outward:
        if character.isalpha():
            letters += character
        else:
            break
    return letters


def zone_for(postcode: str) -> str:
    area = area_of(postcode)
    if area in ISLAND_AREAS:
        return "islands"
    if area in HIGHLAND_AREAS:
        return "highlands"
    if area in LONDON_AREAS:
        return "london"
    return "mainland"


def volumetric_grams(dimensions_cm: Sequence[float]) -> int:
    """The carriers charge for the room a parcel takes up when that beats what it weighs."""
    length, width, height = dimensions_cm
    return int(math.ceil((length * width * height) / VOLUMETRIC_DIVISOR * 1000))


def chargeable_grams(weight_grams: int, dimensions_cm: Sequence[float]) -> int:
    return max(int(weight_grams), volumetric_grams(dimensions_cm))


def band_for(grams: int) -> Optional[int]:
    for band in BANDS:
        if grams <= band:
            return band
    return None


def build_rate_cards() -> List[Dict[str, Any]]:
    """The whole card: a row per carrier, service, zone and band. Seeded into rate_cards."""
    rows: List[Dict[str, Any]] = []
    for carrier, service, _name, _blurb, zones, max_grams, base, step, days in SERVICES:
        for zone in zones:
            loading, extra_days = ZONE_LOADING[zone]
            for index, band in enumerate(BANDS):
                if band > max_grams:
                    continue
                price = int(round((base + step * index) * loading / 5.0)) * 5
                rows.append(
                    {
                        "carrier_code": carrier,
                        "service": service,
                        "zone": zone,
                        "max_grams": band,
                        "price_pence": price,
                        "estimated_days": days + extra_days,
                    }
                )
    rows.sort(
        key=lambda row: (row["carrier_code"], row["service"], row["zone"], row["max_grams"])
    )
    return rows


def service_rows() -> List[Dict[str, Any]]:
    return [
        {
            "carrier_code": carrier,
            "service": service,
            "name": name,
            "description": blurb,
            "max_grams": max_grams,
        }
        for carrier, service, name, blurb, _zones, max_grams, _base, _step, _days in SERVICES
    ]


def price_rows(conn, zone: str, grams: int, service: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every card row that covers this zone and this weight, cheapest first."""
    band = band_for(grams)
    if band is None:
        return []
    sql = (
        "SELECT r.carrier_code, r.service, r.price_pence, r.estimated_days, "
        "c.name AS carrier_name "
        "FROM rate_cards r JOIN carriers c ON c.code = r.carrier_code "
        "JOIN carrier_services s ON s.carrier_code = r.carrier_code AND s.service = r.service "
        "WHERE r.zone = ? AND r.max_grams = ? AND s.max_grams >= ?"
    )
    params: List[Any] = [zone, band, grams]
    if service:
        sql += " AND r.service = ?"
        params.append(service)
    sql += " ORDER BY r.price_pence ASC, r.carrier_code ASC"
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def quote_lines(
    conn,
    from_postcode: str,
    to_postcode: str,
    weight_grams: int,
    dimensions_cm: Sequence[float],
    service: Optional[str] = None,
    plan: str = TRIAL_PLAN,
) -> List[Dict[str, Any]]:
    """The quotes for one parcel, at the shop's plan. Empty when nothing on the card takes it."""
    if max(dimensions_cm) > LONGEST_SIDE_CM:
        return []
    grams = chargeable_grams(weight_grams, dimensions_cm)
    lines = price_rows(conn, zone_for(to_postcode), grams, service)
    # Collecting outside the mainland costs the carriers more, and they pass it on.
    from_zone = zone_for(from_postcode)
    far = from_zone in ("highlands", "islands")
    for line in lines:
        if far:
            loading = ZONE_LOADING[from_zone][0]
            line["price_pence"] = int(round(line["price_pence"] * loading / 5.0)) * 5
        line["price_pence"] = parcel_price(plan, line["price_pence"])
    lines.sort(key=lambda line: (line["price_pence"], line["carrier_code"]))
    return lines
