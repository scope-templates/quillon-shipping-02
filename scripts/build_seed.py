"""Builds data/seed.json: shops, keys, a year of parcels and the scans still in retention, and
every shop's subscription with the billing provider's year of events behind it.

Two seeded Randoms, one for the shops and the parcels and one for the subscriptions and the
billing, so a second run writes the same bytes. `--check` compares the committed file with what
this script builds. Prices come off app.rates and app.plans, so a seeded price is one the quote
endpoint would have given on the plan the shop was on that day; a parcel's status is whatever its
last scan makes it, and a subscription is whatever app.billing makes of its events in the order
they arrived.
"""

import argparse
import bisect
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rates import (  # noqa: E402
    BANDS,
    CARRIERS,
    SERVICES,
    build_rate_cards,
    chargeable_grams,
    service_rows,
)
from app import billing  # noqa: E402
from app.ids import ALPHABET as ID_ALPHABET  # noqa: E402
from app.ids import read_stamp  # noqa: E402
from app.plans import TRIAL_PLAN, fee_for, one_month_on, parcel_price  # noqa: E402
from app.tracking import status_after  # noqa: E402

SEED = 20260901
BILLING_SEED = 20260714
OUT = Path(__file__).resolve().parent.parent / "data" / "seed.json"

# Snapshot: 06:00 UTC on 1 September 2026. Nothing in the file is later than this.
AS_OF = datetime(2026, 9, 1, 6, 0, tzinfo=timezone.utc)
FIRST_DAY = date(2025, 9, 1)
LAST_DAY = date(2026, 8, 31)
OPENED_FOR_BUSINESS = date(2024, 4, 15)

SHOPS = 140
LIVE_SHOPS = 60
CLOSED_SHOPS = 6
LIVE_PARCELS = 5620
BIGGEST_SHARE = 0.33
ENDPOINTS = 40
DELIVERY_HISTORY_DAYS = 14
# Scans are kept for ninety days, as long as the carriers answer for a parcel.
SCAN_RETENTION_DAYS = 90
# Dates the service changed under the data. See CHANGELOG.md.
BLUECOAT_FROM = date(2026, 7, 22)
REFERENCE_RULE_FROM = date(2026, 6, 9)
SENDER_ON_EVERY_PARCEL_UNTIL = date(2026, 4, 2)

# The shops that came in through the form on the website and are still trialling.
TRIALLING_SHOPS = 12
SIGNUP_WINDOW_DAYS = 42
# Plans: the busiest live shops on volume, the rest of the live ones on standard bar most of the
# quietest, and the shops that never went live on pay as you go bar a few that signed lately.
VOLUME_SHOPS = 18
QUIET_TAIL = 9
PAYG_IN_THE_TAIL = 6
IDLE_ON_STANDARD = 9
CLOSED_PLANS = ("volume", "volume", "standard", "standard", "payg", "payg")
# Invoices in the last two months that the card did not pay, and nothing paid since.
PAST_DUE_SENDING = 5
PAST_DUE_QUIET = 3
PAST_DUE_WITHIN_DAYS = 60
# Failed payments earlier in the year that the card paid a few days on, two of which reached
# us after the payment that settled them.
RECOVERED_FAILURES = 7
LATE_ARRIVALS = 2
# The billing feed went live on 14 July 2026 (see CHANGELOG.md). Everything the provider had sent
# before that day was loaded in that morning, a few seconds apart, in the order it happened.
FEED_LIVE_FROM = datetime(2026, 7, 14, tzinfo=timezone.utc)
BACKLOG_LOADED_AT = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)

FAIL_WORDING = (
    "The card was declined",
    "Not enough in the account",
    "The card on file has expired",
    "The bank asked for the payment to be authorised and it was not",
)
CANCEL_WORDING = (
    "Closing the shop at the end of the season",
    "Moving to a carrier account of their own",
    "The marketplace they sell on books its own delivery now",
    "Business sold; the new owners have their own arrangements",
    "Stopped selling online",
    "Too few parcels to be worth the monthly fee",
)

# November and January are the two peaks.
MONTH_WEIGHT = {
    9: 0.75, 10: 0.95, 11: 1.85, 12: 1.20, 1: 1.55, 2: 0.85,
    3: 0.95, 4: 0.85, 5: 0.90, 6: 0.80, 7: 0.85, 8: 0.95,
}
DAY_WEIGHT = (1.0, 1.0, 1.0, 1.0, 0.95, 0.38, 0.08)  # Monday through Sunday

SHOP_FIRST = (
    "Ashcombe", "Barrowfield", "Brindle", "Cawdon", "Marfield", "Netherby", "Wrenbury",
    "Dunstall", "Halloway", "Penhale", "Redgate", "Stanbury", "Thornbeck", "Upcott",
    "Wybourne", "Calderstone", "Ellersby", "Fallowmere", "Granthorpe", "Haversham",
    "Ingleby", "Kirkstall", "Loxley", "Mereton", "Norbury", "Oakhanger", "Pinvin",
    "Quarrington", "Rushmere", "Saltmarsh", "Tanbury", "Underhill", "Vellow", "Wistow",
    "Yarnfield", "Amberwell", "Bexmoor", "Cranbourne", "Dowsett", "Eastney",
)
SHOP_SECOND = (
    "Ceramics", "Supplies", "Trading Co", "Provisions", "Workshop", "Studio", "Kitchen",
    "Cycles", "Prints", "Apothecary", "Bakery", "Woollens", "Records", "Hardware",
    "Nursery", "Brewing", "Leatherwork", "Candles", "Toy Company", "Stationers",
)

PLATFORMS = (
    ("own build", 0.24),
    ("cartwell", 0.22),
    ("marketside", 0.18),
    ("tillbox", 0.14),
    ("perchbox", 0.12),
    ("bramble", 0.10),
)

# Recipients only. Staff names are kept out of the data.
FIRST_NAMES = (
    "Amelia", "Joanne", "Rhian", "Dermot", "Saskia", "Nadia", "Olu", "Bethan", "Fergus",
    "Imogen", "Krishan", "Lorna", "Marcus", "Neve", "Ottoline", "Piers", "Rosa", "Sanjay",
    "Tilda", "Ursula", "Vikram", "Wendy", "Yusuf", "Zoe", "Alasdair", "Bryn", "Cerys",
    "Dilip", "Eleri", "Fionn", "Gwen", "Hamish", "Isla", "Jonty", "Keziah", "Leon",
    "Mairead", "Niall", "Orla", "Pavel", "Rafe", "Siobhan", "Theo", "Verity", "Walter",
    "Xanthe", "Bridget", "Conall", "Delyth", "Esme",
)
LAST_NAMES = (
    "Adeyemi", "Barr", "Chowdhury", "Doherty", "Eames", "Fitzgerald", "Gallacher",
    "Haddon", "Iqbal", "Jarrett", "Kowalczyk", "Lyndhurst", "Mbeki", "Okonjo",
    "Pemberton", "Quayle", "Sinclair", "Tavendale", "Underwood", "Vance", "Yarrow",
    "Zieliński", "Alderton", "Bex", "Crowther", "Dunbar", "Ellery", "Fenwick",
    "Grimshaw", "Hollingsworth", "Ivory", "Jessop", "Kerrigan", "Loveday", "Mottram",
    "Netherwood", "Ollerenshaw", "Parbury", "Rathbone", "Stapleton", "Thirlwell",
    "Vasey", "Whitcombe", "Ackroyd", "Braithwaite", "Cadwallader",
)

STREET_FIRST = (
    "Feeder", "Ravensbourne", "Lampeter", "Sandpiper", "Coldharbour", "Marlborough",
    "Quarry", "Stapleford", "Tannery", "Vicarage", "Whitcliffe", "Brunswick", "Clayhill",
    "Dovecote", "Elmbank", "Fosseway", "Gasworks", "Hollybush", "Ironmonger", "Jubilee",
    "Kingsdown", "Limekiln", "Mulberry", "Northfield", "Orchard", "Pottery", "Rope Walk",
    "Saltford", "Turnpike", "Union",
)
STREET_TYPE = (
    "Road", "Street", "Lane", "Terrace", "Way", "Close", "Rise", "Gardens", "Crescent",
    "Hill", "Buildings", "Yard",
)
UNIT_PREFIX = ("Unit", "Workshop", "Studio", "Suite", "Bay")

# Postcode area, the town we put with it, and the zone it prices in.
AREAS = (
    ("BS", "Bristol", "mainland"), ("BA", "Ashcombe", "mainland"),
    ("GL", "Marfield", "mainland"), ("TA", "Netherby", "mainland"),
    ("EX", "Penhale", "mainland"), ("PL", "Wrenbury", "mainland"),
    ("SN", "Dunstall", "mainland"), ("OX", "Halloway", "mainland"),
    ("CV", "Redgate", "mainland"), ("LE", "Stanbury", "mainland"),
    ("NG", "Thornbeck", "mainland"), ("S", "Upcott", "mainland"),
    ("LS", "Wybourne", "mainland"), ("M", "Calderstone", "mainland"),
    ("L", "Ellersby", "mainland"), ("CH", "Fallowmere", "mainland"),
    ("DE", "Granthorpe", "mainland"), ("NR", "Haversham", "mainland"),
    ("IP", "Ingleby", "mainland"), ("CB", "Kirkstall", "mainland"),
    ("CF", "Loxley", "mainland"), ("SA", "Mereton", "mainland"),
    ("NP", "Norbury", "mainland"), ("YO", "Oakhanger", "mainland"),
    ("NE", "Pinvin", "mainland"), ("CA", "Quarrington", "mainland"),
    ("PR", "Rushmere", "mainland"), ("ST", "Saltmarsh", "mainland"),
    ("PE", "Tanbury", "mainland"), ("MK", "Underhill", "mainland"),
    ("GU", "Vellow", "mainland"), ("BN", "Wistow", "mainland"),
    ("CT", "Yarnfield", "mainland"), ("SO", "Amberwell", "mainland"),
    ("BH", "Bexmoor", "mainland"), ("EH", "Cranbourne", "mainland"),
    ("G", "Dowsett", "mainland"), ("DD", "Eastney", "mainland"),
    ("EC", "London", "london"), ("WC", "London", "london"),
    ("E", "London", "london"), ("N", "London", "london"),
    ("SE", "London", "london"), ("SW", "London", "london"),
    ("W", "London", "london"), ("NW", "London", "london"),
    ("IV", "Kildrummie", "highlands"), ("AB", "Torrinch", "highlands"),
    ("PH", "Glenbarrow", "highlands"), ("KW", "Sarclet", "highlands"),
    ("HS", "Balivanich", "islands"), ("ZE", "Voesgarth", "islands"),
    ("IM", "Ballasalla", "islands"), ("JE", "Grouville", "islands"),
)
AREA_WEIGHT = {"mainland": 0.66, "london": 0.27, "highlands": 0.05, "islands": 0.02}

DEPOT_TOWNS = (
    "Ashcombe", "Calderstone", "Granthorpe", "Marfield", "Netherby", "Redgate",
    "Stanbury", "Tanbury", "Wrenbury", "Yarnfield",
)

BOXES = (
    ((16, 12, 6), 180, 900),
    ((24, 18, 8), 350, 2200),
    ((32, 24, 10), 700, 4200),
    ((40, 30, 15), 1400, 8000),
    ((45, 35, 22), 2600, 12000),
    ((60, 40, 30), 4000, 18000),
)
BOX_WEIGHT = (0.22, 0.28, 0.24, 0.15, 0.08, 0.03)

CONTENTS = (
    "Two glazed bowls", "Refill pouches, four", "A pair of walking socks",
    "Seed trays and labels", "One framed print, boxed", "Coffee, three bags",
    "Replacement inner tube", "Wool, six skeins", "A jar of honey and a card",
    "Ink cartridges", "Soap, gift set", "Tea, loose leaf, two tins",
    "Bicycle bell and lights", "Cushion cover", "Chopping board", "Notebook and pen",
    "Candle, large", "Leather belt", "Toy train and track", "Spare filter",
    "Two mugs, wrapped", "Enamel plate", "Dog collar", "Watercolour paper",
    "Bird feeder", "Jigsaw, 1000 piece", "Apron", "Lavender bags", "Kitchen scales",
    "Pot of paint, tester", None, None, None,
)

REFERENCE_PREFIX = ("WEB", "ORD", "SO", "SHOP", "OC", "INV")

MAILBOX_DOMAINS = (
    "larkmail.co.uk", "brightbox.co.uk", "penfold.net", "havenmail.com",
    "orchardpost.co.uk", "tallowmail.co.uk", "mereside.net",
)
INWARD_LETTERS = "ABDEFGHJLNPQRSTUWXYZ"

KEY_LABELS = ("Production", "Checkout", "Back office", "Warehouse", "Integration", "Staging")

FAIL_REASONS = (
    "504 from endpoint",
    "timed out after 10s",
    "500 from endpoint",
    "certificate has expired",
)
REFUSED = "connection_refused"


# ------------------------------------------------------------------ small deterministic helpers


def make_id(rng, prefix, length=22):
    return prefix + "_" + "".join(rng.choice(ID_ALPHABET) for _ in range(length))


def pick(rng, options, weights):
    return rng.choices(options, weights=weights, k=1)[0]


def stamp(moment):
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def months_between(first, last):
    out = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        out.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return out


def days_in(year, month):
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def postcode(rng, area):
    """Outward code of two to four characters, then the inward code. Valid shapes only."""
    outward = f"{area}{rng.randint(1, 9)}"
    roll = rng.random()
    if roll < 0.45:
        outward += str(rng.randint(0, 9))
    elif roll < 0.55 and len(area) == 1:
        outward += rng.choice("ABCDEFGHW")
    inward = f"{rng.randint(0, 9)}{rng.choice(INWARD_LETTERS)}{rng.choice(INWARD_LETTERS)}"
    return f"{outward} {inward}"


def area_for_zone(rng, zone):
    choices = [row for row in AREAS if row[2] == zone]
    return rng.choice(choices)


def pick_area(rng):
    zone = pick(rng, list(AREA_WEIGHT), list(AREA_WEIGHT.values()))
    return area_for_zone(rng, zone)


def person(rng):
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def street(rng):
    return f"{rng.randint(1, 240)} {rng.choice(STREET_FIRST)} {rng.choice(STREET_TYPE)}"


def phone(rng):
    """The range reserved for fiction: 07700 900000 to 07700 900999."""
    return f"07700 900{rng.randint(0, 999):03d}"


def domain_for(name):
    words = [word for word in name.lower().replace("&", "and").split() if word.isalnum()]
    return "".join(words[:2]) + ".co.uk"


# ------------------------------------------------------------------------------------ the shops


def build_shops(rng):
    names = set()
    while len(names) < SHOPS:
        first = rng.choice(SHOP_FIRST)
        second = rng.choice(SHOP_SECOND)
        name = f"{first} {second}"
        if rng.random() < 0.12:
            name = f"The {name}"
        names.add(name)
    ordered = sorted(names)
    rng.shuffle(ordered)

    shops = []
    for index, name in enumerate(ordered):
        area, town, _zone = pick_area(rng)
        joined_days = rng.randint(0, (LAST_DAY - OPENED_FOR_BUSINESS).days - 30)
        joined = OPENED_FOR_BUSINESS + timedelta(days=joined_days)
        shops.append(
            {
                "id": make_id(rng, "cus"),
                "name": name,
                "platform": pick(rng, [row[0] for row in PLATFORMS], [row[1] for row in PLATFORMS]),
                "city": town,
                "contact_email": f"{rng.choice(('orders', 'hello', 'dispatch', 'shop'))}@"
                                 f"{domain_for(name)}",
                "status": "active",
                "created_at": stamp(
                    datetime(joined.year, joined.month, joined.day, rng.randint(8, 17),
                             rng.randint(0, 59), tzinfo=timezone.utc)
                ),
                "dispatch_address": {
                    "name": name,
                    "line1": f"{rng.choice(UNIT_PREFIX)} {rng.randint(1, 24)}, {street(rng)}",
                    "city": town,
                    "postcode": postcode(rng, area),
                    "phone": phone(rng),
                },
                "_area": area,
                "_town": town,
                "_joined": joined,
                "_live": index < LIVE_SHOPS,
            }
        )

    # Six accounts closed during the year. Their keys stay in the table.
    for shop in shops[LIVE_SHOPS:LIVE_SHOPS + CLOSED_SHOPS]:
        shop["status"] = "closed"
        shop["_live"] = False
    return shops


def build_keys(rng, shops):
    keys = []
    for index, shop in enumerate(shops):
        joined = shop["_joined"]
        made = datetime(joined.year, joined.month, joined.day, 9, 30, tzinfo=timezone.utc) + \
            timedelta(minutes=rng.randint(0, 600))
        wanted = [("test", "Integration")]
        if index == 0:
            # The biggest shop runs on one live key and has never used the sandbox.
            wanted = [("live", "Production")]
        elif shop["_live"]:
            wanted.append(("live", "Production"))
            if rng.random() < 0.22:
                wanted.append(("live", rng.choice(KEY_LABELS)))
        elif shop["status"] == "closed":
            wanted.append(("live", "Production"))
        for offset, (mode, label) in enumerate(wanted):
            created = made + timedelta(days=offset * rng.randint(0, 40))
            if shop["status"] == "closed":
                last_used = created + timedelta(days=rng.randint(30, 300))
            elif shop["_live"]:
                last_used = AS_OF - timedelta(
                    minutes=rng.randint(2, 2400) if mode == "live" else rng.randint(60, 90000)
                )
            else:
                last_used = created + timedelta(days=rng.randint(0, 60))
            if last_used > AS_OF:
                last_used = AS_OF - timedelta(minutes=5)
            keys.append(
                {
                    "key": f"qp_{mode}_" + "".join(rng.choice(ID_ALPHABET) for _ in range(24)),
                    "customer_id": shop["id"],
                    "mode": mode,
                    "label": label,
                    "created_at": stamp(created),
                    "last_used_at": stamp(last_used) if rng.random() < 0.94 else None,
                }
            )
    keys.sort(key=lambda row: (row["created_at"], row["key"]))
    return keys


# --------------------------------------------------------------------------------- the parcels


def card_lookup():
    """(carrier, service, zone, band) -> price and days, off the same card the service quotes."""
    out = {}
    for row in build_rate_cards():
        out[(row["carrier_code"], row["service"], row["zone"], row["max_grams"])] = (
            row["price_pence"],
            row["estimated_days"],
        )
    return out


def services_for_zone(zone, grams):
    out = []
    for carrier, service, _name, _blurb, zones, max_grams, _base, _step, _days in SERVICES:
        if zone in zones and grams <= max_grams:
            out.append((carrier, service))
    return out


def band_for(grams):
    for band in BANDS:
        if grams <= band:
            return band
    return None


def shop_shares(rng, live_shops):
    """One shop is a third of everything; the rest fall away sharply."""
    shares = [BIGGEST_SHARE]
    tail = [1.0 / (index + 2.0) ** 0.95 for index in range(len(live_shops) - 1)]
    rough = sum(tail)
    shares.extend((1 - BIGGEST_SHARE) * value / rough for value in tail)
    counts = [max(int(round(share * LIVE_PARCELS)), 4) for share in shares]
    # Nine live shops at very low volume.
    for index in range(len(counts) - 9, len(counts)):
        counts[index] = rng.randint(3, 40)
    return counts


def pick_day(rng, shop_joined):
    months = [
        (year, month)
        for year, month in months_between(FIRST_DAY, LAST_DAY)
        if date(year, month, days_in(year, month)) >= shop_joined
    ]
    if not months:
        months = [(LAST_DAY.year, LAST_DAY.month)]
    year, month = pick(rng, months, [MONTH_WEIGHT[month] for _year, month in months])
    span = days_in(year, month)
    days = [date(year, month, day) for day in range(1, span + 1)]
    days = [day for day in days if FIRST_DAY <= day <= LAST_DAY and day >= shop_joined]
    if not days:
        return LAST_DAY
    return pick(rng, days, [DAY_WEIGHT[day.weekday()] for day in days])


def booked_at(rng, day):
    hour = pick(
        rng,
        list(range(8, 20)),
        (0.6, 1.0, 1.4, 1.5, 1.3, 1.0, 1.2, 1.4, 1.5, 1.1, 0.6, 0.3),
    )
    return datetime(
        day.year, day.month, day.day, hour, rng.randint(0, 59), rng.randint(0, 59),
        tzinfo=timezone.utc,
    )


def parcel_for(rng):
    box, low, high = pick(rng, BOXES, BOX_WEIGHT)
    length, width, height = box
    jitter = rng.uniform(0.85, 1.0)
    parcel = {
        "weight_grams": rng.randint(low, high),
        "dimensions_cm": {
            "length_cm": round(length * jitter, 1),
            "width_cm": round(width * jitter, 1),
            "height_cm": round(height * jitter, 1),
        },
    }
    description = rng.choice(CONTENTS)
    if description:
        parcel["description"] = description
    return parcel


def recipient_for(rng):
    area, town, zone = pick_area(rng)
    who = {
        "name": person(rng),
        "line1": street(rng),
        "city": town,
        "postcode": postcode(rng, area),
    }
    if rng.random() < 0.28:
        who["line2"] = rng.choice(("Flat 2", "Flat 11b", "The Annexe", "Rear of shop",
                                   "c/o The Post Office", "Apartment 4"))
    if rng.random() < 0.55:
        who["phone"] = phone(rng)
    if rng.random() < 0.35:
        mailbox = who["name"].lower().replace(" ", ".").replace("ń", "n")
        who["email"] = f"{mailbox}@{rng.choice(MAILBOX_DOMAINS)}"
    return who, zone


def outcome_for(rng):
    roll = rng.random()
    if roll < 0.026:
        return "cancelled"
    if roll < 0.049:
        return "returned"
    if roll < 0.068:
        return "held"
    return "delivered"


# Northgate scan at both depots, Kestrel on arrival, the other two at neither.
ORIGIN_SCANS = ("northgate",)
ARRIVAL_SCANS = ("northgate", "kestrel")


def timeline(rng, created, outcome, sender_city, recipient_city, depot, carrier_code):
    """The scans a parcel gets, in order, whatever happens to it."""
    events = [("label_created", sender_city, created)]
    if outcome == "cancelled":
        events.append(("cancelled", sender_city, created + timedelta(
            minutes=rng.randint(6, 420))))
        return events

    collected = created + timedelta(hours=rng.randint(3, 22), minutes=rng.randint(0, 59))
    while collected.weekday() >= 5:
        collected += timedelta(days=1)
    events.append(("collected", sender_city, collected))
    origin = collected + timedelta(hours=rng.randint(2, 7))
    if carrier_code in ORIGIN_SCANS:
        events.append(("at_origin_depot", depot, origin))
    moving = origin + timedelta(hours=rng.randint(4, 15))
    events.append(("in_transit", depot, moving))
    arrived = moving + timedelta(hours=rng.randint(5, 26))
    if carrier_code in ARRIVAL_SCANS:
        events.append(("at_delivery_depot", recipient_city, arrived))

    if outcome == "held":
        held_code = "held_at_depot" if rng.random() < 0.45 else "address_query"
        events.append((held_code, recipient_city, arrived + timedelta(
            hours=rng.randint(1, 20))))
        return events

    out = arrived.replace(hour=rng.randint(6, 8), minute=rng.randint(0, 59)) + timedelta(days=1)
    while out.weekday() >= 5:
        out += timedelta(days=1)
    events.append(("out_for_delivery", recipient_city, out))

    if outcome == "returned":
        events.append(("delivery_attempted", recipient_city, out + timedelta(
            hours=rng.randint(2, 9))))
        events.append(("held_at_depot", recipient_city, out + timedelta(
            hours=rng.randint(10, 30))))
        events.append(("returned_to_sender", sender_city, out + timedelta(
            days=rng.randint(4, 9), hours=rng.randint(0, 20))))
        return events

    if rng.random() < 0.06:
        events.append(("delivery_attempted", recipient_city, out + timedelta(
            hours=rng.randint(2, 8))))
        out = out + timedelta(days=1)
        while out.weekday() >= 5:
            out += timedelta(days=1)
        events.append(("out_for_delivery", recipient_city, out))
    events.append(("delivered", recipient_city, out + timedelta(
        hours=rng.randint(1, 9), minutes=rng.randint(0, 59))))
    return events


def build_parcels(rng, shops):
    card = card_lookup()
    live_shops = [shop for shop in shops if shop["_live"]]
    counts = shop_shares(rng, live_shops)
    testing_shops = [shop for shop in shops if not shop["_live"]]

    work = []
    for shop, count in zip(live_shops, counts):
        work.append((shop, "live", count))
    for shop in testing_shops:
        work.append((shop, "test", rng.randint(1, 6)))
    for shop in rng.sample(live_shops, 18):
        work.append((shop, "test", rng.randint(1, 5)))

    shipments = []
    events = []
    references = {}
    scans_from = AS_OF - timedelta(days=SCAN_RETENTION_DAYS)
    for shop, mode, count in work:
        sender = shop["dispatch_address"]
        prefix = rng.choice(REFERENCE_PREFIX)
        counter = references.setdefault(shop["id"], rng.randint(1000, 90000))
        preferred = rng.sample(
            [row["code"] for row in CARRIERS], k=rng.randint(1, 3)
        )
        for _ in range(count):
            day = pick_day(rng, shop["_joined"])
            if mode == "test":
                day = min(
                    LAST_DAY,
                    max(FIRST_DAY, shop["_joined"] + timedelta(days=rng.randint(0, 25))),
                )
            created = booked_at(rng, day)
            if created >= AS_OF:
                continue
            recipient, zone = recipient_for(rng)
            parcel = parcel_for(rng)
            grams = chargeable_grams(
                parcel["weight_grams"],
                (
                    parcel["dimensions_cm"]["length_cm"],
                    parcel["dimensions_cm"]["width_cm"],
                    parcel["dimensions_cm"]["height_cm"],
                ),
            )
            band = band_for(grams)
            options = [
                (carrier, service)
                for carrier, service in services_for_zone(zone, grams)
                if (carrier, service, zone, band) in card
            ]
            if day < BLUECOAT_FROM:
                options = [pair for pair in options if pair[0] != "bluecoat"]
            if not options:
                continue
            liked = [pair for pair in options if pair[0] in preferred]
            carrier_code, service = rng.choice(liked or options)
            price, _days = card[(carrier_code, service, zone, band)]

            counter += 1
            references[shop["id"]] = counter
            outcome = outcome_for(rng)
            depot = rng.choice(DEPOT_TOWNS)
            scans = timeline(
                rng, created, outcome, sender["city"], recipient["city"], depot, carrier_code
            )
            scans = [scan for scan in scans if scan[2] < AS_OF]
            if not scans:
                continue
            kept_scans = [scan for scan in scans if scan[2] >= scans_from]

            shipment_id = make_id(rng, "shp")
            carrier = next(row for row in CARRIERS if row["code"] == carrier_code)
            last_code = scans[-1][0]
            status = status_after(last_code)
            row = {
                "id": shipment_id,
                "customer_id": shop["id"],
                "mode": mode,
                "carrier_code": carrier_code,
                "service": service,
                "status": status,
                "tracking_number": carrier["tracking_prefix"] + "".join(
                    rng.choice("0123456789") for _ in range(10)
                ),
                "price_pence": price,
                "recipient": recipient,
                "parcel": parcel,
                "created_at": stamp(created),
            }
            if rng.random() < 0.82:
                row["reference"] = f"{prefix}-{counter}"
            if rng.random() < 0.6:
                row["quote_id"] = make_id(rng, "qt")
            if day < SENDER_ON_EVERY_PARCEL_UNTIL:
                # Before April 2026 there was no account address to fall back on.
                row["sender"] = sender
            for code, _where, when in scans:
                if code == "collected":
                    row["collected_at"] = stamp(when)
                elif code == "delivered":
                    row["delivered_at"] = stamp(when)
                elif code == "cancelled":
                    row["cancelled_at"] = stamp(when)
            shipments.append(row)
            for code, where, when in kept_scans:
                events.append(
                    {
                        "id": make_id(rng, "evt"),
                        "shipment_id": shipment_id,
                        "code": code,
                        "location": where,
                        "occurred_at": stamp(when),
                    }
                )

    shipments.sort(key=lambda row: (row["created_at"], row["id"]))
    events.sort(key=lambda row: (row["occurred_at"], row["id"]))
    return shipments, events


def strand_a_few(rng, shipments, events):
    """Four parcels held in a depot since July, with no scan after it."""
    by_shipment = {}
    for event in events:
        by_shipment.setdefault(event["shipment_id"], []).append(event)
    candidates = [
        row for row in shipments
        if row["status"] == "delivered" and row["created_at"][:7] == "2026-07"
    ]
    for row in rng.sample(candidates, 4):
        scans = by_shipment[row["id"]]
        keep = [scan for scan in scans if scan["code"] in
                ("label_created", "collected", "at_origin_depot", "in_transit",
                 "at_delivery_depot")]
        if not keep:
            continue
        stuck = keep[-1]
        held = {
            "id": make_id(rng, "evt"),
            "shipment_id": row["id"],
            "code": "held_at_depot",
            "location": stuck["location"],
            "occurred_at": stamp(
                datetime.fromisoformat(stuck["occurred_at"].replace("Z", "+00:00"))
                + timedelta(hours=rng.randint(2, 9))
            ),
        }
        row["status"] = "held"
        row.pop("delivered_at", None)
        for scan in scans:
            if scan not in keep:
                events.remove(scan)
        events.append(held)
    events.sort(key=lambda row: (row["occurred_at"], row["id"]))
    return shipments, events


def repeat_a_few_references(rng, shipments):
    """Six references used twice, from before the rule that keeps them apart."""
    cutoff = REFERENCE_RULE_FROM.isoformat()
    by_shop = {}
    for row in shipments:
        if row.get("reference") and row["mode"] == "live" and row["created_at"] < cutoff:
            by_shop.setdefault(row["customer_id"], []).append(row)
    pairs = [rows for rows in by_shop.values() if len(rows) >= 2]
    for rows in rng.sample(pairs, min(6, len(pairs))):
        first, second = rng.sample(rows, 2)
        second["reference"] = first["reference"]
    return shipments


# -------------------------------------------------------------------------------- the webhooks


def build_webhooks(rng, shops, shipments):
    live_shops = [shop for shop in shops if shop["_live"]]
    # The six busiest shops all have an endpoint.
    listening = live_shops[:6] + rng.sample(live_shops[6:], min(ENDPOINTS, len(live_shops)) - 6)
    endpoints = []
    for shop in listening:
        joined = shop["_joined"]
        made = datetime(joined.year, joined.month, joined.day, tzinfo=timezone.utc) + timedelta(
            days=rng.randint(1, 60), hours=rng.randint(9, 18)
        )
        wanted = rng.sample(
            ["shipment.created", "shipment.cancelled", "shipment.delivered", "tracking.updated"],
            k=rng.randint(1, 3),
        )
        endpoints.append(
            {
                "id": make_id(rng, "whe"),
                "customer_id": shop["id"],
                "url": f"https://{domain_for(shop['name'])}/"
                       f"{rng.choice(('hooks/quillon', 'webhooks/quillon', 'api/parcels/hook'))}",
                "events": sorted(wanted),
                "secret": "whsec_" + "".join(rng.choice(ID_ALPHABET) for _ in range(32)),
                "status": "active",
                "created_at": stamp(min(made, AS_OF - timedelta(days=2))),
            }
        )
    endpoints.sort(key=lambda row: (row["created_at"], row["id"]))

    recent_cut = AS_OF - timedelta(days=DELIVERY_HISTORY_DAYS)
    by_customer = {}
    for row in shipments:
        if row["created_at"] >= stamp(recent_cut) and row["mode"] == "live":
            by_customer.setdefault(row["customer_id"], []).append(row)

    # One endpoint has been refusing connections for a week.
    with_traffic = [
        endpoint for endpoint in endpoints if by_customer.get(endpoint["customer_id"])
    ]
    refusing = rng.choice(with_traffic or endpoints)["id"]

    deliveries = []
    for endpoint in endpoints:
        parcels = by_customer.get(endpoint["customer_id"], [])
        rng.shuffle(parcels)
        for row in parcels[:30]:
            for event_type in endpoint["events"]:
                if event_type == "shipment.delivered" and row["status"] != "delivered":
                    continue
                if event_type == "shipment.cancelled" and row["status"] != "cancelled":
                    continue
                created = datetime.fromisoformat(
                    row["created_at"].replace("Z", "+00:00")
                ) + timedelta(minutes=rng.randint(1, 90))
                if created >= AS_OF:
                    continue
                payload = {
                    "id": make_id(rng, "whev"),
                    "type": event_type,
                    "created_at": stamp(created),
                    "data": {
                        "id": row["id"],
                        "status": row["status"],
                        "carrier_code": row["carrier_code"],
                        "service": row["service"],
                        "tracking_number": row["tracking_number"],
                        "reference": row.get("reference"),
                    },
                }
                delivery = {
                    "id": make_id(rng, "whd"),
                    "endpoint_id": endpoint["id"],
                    "event_type": event_type,
                    "shipment_id": row["id"],
                    "payload": payload,
                    "created_at": stamp(created),
                }
                if endpoint["id"] == refusing:
                    attempts = rng.randint(6, 9)
                    last = created + timedelta(hours=rng.randint(1, 40))
                    delivery.update(
                        {
                            "status": "failed" if attempts < 9 else "given_up",
                            "attempts": attempts,
                            "last_error": REFUSED,
                            "last_attempt_at": stamp(min(last, AS_OF)),
                            "next_attempt_at": stamp(AS_OF + timedelta(
                                hours=rng.randint(1, 12))) if attempts < 9 else None,
                        }
                    )
                elif rng.random() < 0.04:
                    attempts = rng.randint(2, 4)
                    last = created + timedelta(minutes=rng.randint(5, 240))
                    delivery.update(
                        {
                            "status": "failed",
                            "attempts": attempts,
                            "last_error": rng.choice(FAIL_REASONS),
                            "last_attempt_at": stamp(min(last, AS_OF)),
                            "next_attempt_at": stamp(min(
                                last + timedelta(minutes=30), AS_OF + timedelta(minutes=20))),
                        }
                    )
                else:
                    attempts = 1 if rng.random() < 0.93 else 2
                    done = created + timedelta(seconds=rng.randint(1, 240))
                    delivery.update(
                        {
                            "status": "delivered",
                            "attempts": attempts,
                            "last_attempt_at": stamp(min(done, AS_OF)),
                            "delivered_at": stamp(min(done, AS_OF)),
                        }
                    )
                deliveries.append(delivery)
    deliveries.sort(key=lambda row: (row["created_at"], row["id"]))
    return endpoints, deliveries


# ------------------------------------------------------------------- the plans and the billing

YEAR_FROM = datetime(FIRST_DAY.year, FIRST_DAY.month, FIRST_DAY.day, tzinfo=timezone.utc)


def moment_between(paper, first, last):
    """A time between the two, in working hours, for something a person did."""
    days = max((last - first).days, 0)
    day = first + timedelta(days=paper.randint(0, days))
    return day.replace(hour=paper.randint(8, 18), minute=paper.randint(0, 59),
                       second=paper.randint(0, 59))


def own_addresses(shops):
    """One account to an email address: a second shop on one is written to at its own domain."""
    taken = set()
    for shop in shops:
        if shop["contact_email"] in taken:
            mailbox = shop["contact_email"].split("@")[0]
            shop["contact_email"] = f"{mailbox}@{domain_for(shop['name'].removeprefix('The '))}"
        taken.add(shop["contact_email"])


def sign_up_recently(paper, shops):
    """A dozen shops that never went live came in through the website in the last six weeks."""
    idle = [shop for shop in shops if not shop["_live"] and shop["status"] == "active"]
    for shop in paper.sample(idle, TRIALLING_SHOPS):
        shop["_joined"] = LAST_DAY - timedelta(days=paper.randint(0, SIGNUP_WINDOW_DAYS - 1))
        shop["status"] = "trialling"


def date_signups(shops, keys):
    """A signup and its test key are made in the same moment."""
    made = {row["customer_id"]: row["created_at"] for row in keys}
    for shop in shops:
        if shop["status"] == "trialling":
            shop["created_at"] = made[shop["id"]]


def last_activity(shop, keys, shipments):
    stamps = [shop["created_at"]]
    for row in keys:
        if row["customer_id"] == shop["id"]:
            stamps.extend(value for value in (row["created_at"], row["last_used_at"]) if value)
    stamps.extend(row["created_at"] for row in shipments if row["customer_id"] == shop["id"])
    return read_stamp(max(stamps))


def plan_at(history, when):
    """The plan in force at a moment: before the subscription started, the trial's."""
    plan = TRIAL_PLAN
    for since, named in history:
        if since <= when:
            plan = named
    return plan


def choose_plans(paper, shops, keys, shipments):
    """Each shop's start, the plans it has been on and when, and when it cancelled if it did."""
    live = [shop for shop in shops if shop["_live"]]
    closed = [shop for shop in shops if shop["status"] == "closed"]
    idle = [shop for shop in shops if not shop["_live"] and shop["status"] == "active"]

    final = {}
    for index, shop in enumerate(live):
        final[shop["id"]] = "volume" if index < VOLUME_SHOPS else "standard"
    for shop in paper.sample(live[-QUIET_TAIL:], PAYG_IN_THE_TAIL):
        final[shop["id"]] = "payg"
    for shop, plan in zip(closed, paper.sample(CLOSED_PLANS, len(CLOSED_PLANS))):
        final[shop["id"]] = plan
    lately = sorted(idle, key=lambda shop: (shop["_joined"], shop["id"]))[-3 * IDLE_ON_STANDARD:]
    on_standard = {shop["id"] for shop in paper.sample(lately, IDLE_ON_STANDARD)}
    for shop in idle:
        final[shop["id"]] = "standard" if shop["id"] in on_standard else "payg"

    started, cancelled, history = {}, {}, {}
    for shop in shops:
        if shop["status"] == "trialling":
            continue
        started[shop["id"]] = read_stamp(shop["created_at"]) + timedelta(
            minutes=paper.randint(30, 3 * 24 * 60)
        )
        history[shop["id"]] = [(started[shop["id"]], final[shop["id"]])]
    for shop in closed:
        quiet_from = max(last_activity(shop, keys, shipments), YEAR_FROM, started[shop["id"]])
        cancelled[shop["id"]] = min(
            moment_between(paper, quiet_from + timedelta(days=2), quiet_from + timedelta(days=28)),
            AS_OF - timedelta(days=1),
        )

    def move(shop, before, first, last):
        """The shop was on `before` and moved to its plan of today somewhere in the window."""
        begun = started[shop["id"]]
        last = min(last, cancelled.get(shop["id"], AS_OF) - timedelta(days=5))
        first = max(first, begun + timedelta(days=20))
        if first >= last:
            return
        history[shop["id"]] = [(begun, before), (moment_between(paper, first, last),
                                                 final[shop["id"]])]

    year_to = AS_OF - timedelta(days=3)
    standard_live = [shop for shop in live if final[shop["id"]] == "standard"]
    payg_live = [shop for shop in live if final[shop["id"]] == "payg"]
    for shop in paper.sample(live[1:VOLUME_SHOPS], 4):
        move(shop, "standard", YEAR_FROM, year_to)
    picked = paper.sample(standard_live, 7)
    for shop in picked[:5]:
        move(shop, "payg", YEAR_FROM, year_to)
    for shop in picked[5:7]:
        move(shop, "volume", YEAR_FROM, year_to)
    for shop in paper.sample(payg_live, 2) + [
        shop for shop in closed if final[shop["id"]] == "payg"
    ][:1]:
        move(shop, "standard", YEAR_FROM, year_to)

    # One went up to volume for the November peak, and back down when it had passed.
    peak_from = datetime(2025, 10, 13, tzinfo=timezone.utc)
    steady = [
        shop for shop in standard_live
        if shop not in picked and started[shop["id"]] < peak_from - timedelta(days=20)
    ]
    if steady:
        peaked = paper.choice(steady)
        history[peaked["id"]] = [
            (started[peaked["id"]], "standard"),
            (moment_between(paper, peak_from, datetime(2025, 11, 7, tzinfo=timezone.utc)),
             "volume"),
            (moment_between(paper, datetime(2026, 1, 26, tzinfo=timezone.utc),
                            datetime(2026, 2, 27, tzinfo=timezone.utc)), "standard"),
        ]
    return started, cancelled, history


def price_on_plans(shipments, history):
    """The card price each parcel was booked at, less what its shop's plan took off that day."""
    for row in shipments:
        plan = plan_at(history.get(row["customer_id"], []), read_stamp(row["created_at"]))
        row["price_pence"] = parcel_price(plan, row["price_pence"])
    return shipments


def invoice_walk(shop_id, history, begun, ends, parcels, fails=None, stops_at=None):
    """Every invoice from the start to the end, a month apart, each moving the next one on.

    An invoice is the plan's fee and the live parcels since the last one; a month with nothing to
    pay, which is a pay-as-you-go month without a parcel, raises none. `fails` is a failed
    invoice the card paid a few days on: (not before, how long after). `stops_at` is the invoice
    the card did not pay, after which there is nothing more.
    """
    times = [stamp_at for stamp_at, _price in parcels]
    out = []
    since = begun
    due = begun + timedelta(seconds=40)
    failed_once = False
    while due < ends:
        plan = plan_at(history, due)
        low = bisect.bisect_left(times, stamp(since))
        high = bisect.bisect_left(times, stamp(due))
        charged = [price for _when, price in parcels[low:high]]
        if not fee_for(plan) and not charged:
            since, due = due, one_month_on(due)
            continue
        invoice = {
            "customer_id": shop_id,
            "due": due,
            "data": {
                "plan": plan,
                "amount_pence": fee_for(plan) + sum(charged),
                "fee_pence": fee_for(plan),
                "parcels": len(charged),
                "parcels_pence": sum(charged),
            },
            "attempts": [("invoice.paid", due)],
        }
        out.append(invoice)
        paid_at = due
        if stops_at is not None and due == stops_at:
            invoice["attempts"] = [("invoice.payment_failed", due)]
            break
        if fails and not failed_once and due >= fails[0] and due + fails[1] < ends:
            failed_once = True
            paid_at = due + fails[1]
            invoice["attempts"] = [("invoice.payment_failed", due), ("invoice.paid", paid_at)]
        since = due
        due = one_month_on(paid_at)
    return out


def build_billing(paper, shops, keys, shipments):
    """Every shop's subscription, and the year of billing events that put it where it is."""
    started, cancelled, history = choose_plans(paper, shops, keys, shipments)
    shipments = price_on_plans(shipments, history)

    parcels = {}
    for row in shipments:
        if row["mode"] == "live" and row["status"] != "cancelled":
            charged = (row["created_at"], row["price_pence"])
            parcels.setdefault(row["customer_id"], []).append(charged)
    last_parcel = {shop_id: read_stamp(rows[-1][0]) for shop_id, rows in parcels.items()}

    def walk(shop, **extra):
        shop_id = shop["id"]
        return invoice_walk(
            shop_id, history[shop_id], started[shop_id], cancelled.get(shop_id, AS_OF),
            parcels.get(shop_id, []), **extra,
        )

    # Past due: a fee-paying live shop whose last invoice in the last two months failed.
    live = [shop for shop in shops if shop["_live"]]
    paying = [shop for shop in live[1:] if fee_for(plan_at(history[shop["id"]], AS_OF))]
    sending = [shop for shop in paying if last_parcel[shop["id"]] >= AS_OF - timedelta(days=7)]
    quiet = [shop for shop in paying if last_parcel[shop["id"]] <= AS_OF - timedelta(days=21)]
    gone_quiet = paper.sample(quiet, min(PAST_DUE_QUIET, len(quiet)))
    still_sending = paper.sample(sending, PAST_DUE_SENDING + PAST_DUE_QUIET - len(gone_quiet))
    unpaid = {}
    for shop in still_sending + gone_quiet:
        recent = [
            invoice["due"] for invoice in walk(shop)
            if invoice["due"] >= AS_OF - timedelta(days=PAST_DUE_WITHIN_DAYS)
        ]
        unpaid[shop["id"]] = paper.choice(recent[-2:])

    settled = [
        shop for shop in live[1:] + [shop for shop in shops if shop["status"] == "closed"]
        if shop["id"] not in unpaid
    ]
    recovered = {}
    for shop in paper.sample(settled, RECOVERED_FAILURES):
        not_before = moment_between(
            paper, YEAR_FROM, AS_OF - timedelta(days=PAST_DUE_WITHIN_DAYS + 10)
        )
        recovered[shop["id"]] = (
            not_before, timedelta(days=paper.randint(2, 6), hours=paper.randint(1, 11))
        )

    invoices = []
    for shop in shops:
        if shop["id"] not in started:
            continue
        invoices.extend(
            walk(shop, fails=recovered.get(shop["id"]), stops_at=unpaid.get(shop["id"]))
        )
    invoices.sort(key=lambda invoice: (invoice["due"], invoice["customer_id"]))

    events = []

    def add(shop_id, kind, when, data):
        events.append(
            {
                "id": make_id(paper, "bev"),
                "customer_id": shop_id,
                "type": kind,
                "occurred_at": stamp(when),
                "payload": data,
                "received_at": None,
            }
        )

    tried_again = {shop["id"] for shop in gone_quiet}
    for number, invoice in enumerate(invoices, start=1):
        data = {"invoice": f"QP-{number:05d}", **invoice["data"]}
        for attempt, (kind, when) in enumerate(invoice["attempts"], start=1):
            if kind == "invoice.payment_failed":
                add(invoice["customer_id"], kind, when,
                    {**data, "attempt": attempt, "reason": paper.choice(FAIL_WORDING)})
            else:
                add(invoice["customer_id"], kind, when, data)
        unpaid_last = invoice["attempts"][-1][0] == "invoice.payment_failed"
        if unpaid_last and invoice["customer_id"] in tried_again:
            # The card was tried again a few days on, and failed again.
            again = invoice["due"] + timedelta(days=paper.randint(3, 5), hours=paper.randint(0, 9))
            if again < AS_OF:
                add(invoice["customer_id"], "invoice.payment_failed", again,
                    {**data, "attempt": 2, "reason": paper.choice(FAIL_WORDING)})

    for shop_id, plans in history.items():
        add(shop_id, "subscription.started", started[shop_id], {"plan": plans[0][1]})
        for (_was_since, was), (since, now_on) in zip(plans, plans[1:]):
            add(shop_id, "subscription.plan_changed", since, {"from_plan": was, "plan": now_on})
    reasons = list(CANCEL_WORDING)
    paper.shuffle(reasons)
    # The shops that were paying no fee choose first, so none of them goes for the fee.
    leaving = sorted(
        (bool(fee_for(plan_at(history[shop_id], when))), when, shop_id)
        for shop_id, when in cancelled.items()
    )
    for paid_a_fee, when, shop_id in leaving:
        reason = next(text for text in reasons if paid_a_fee or "fee" not in text)
        reasons.remove(reason)
        add(shop_id, "subscription.cancelled", when, {"reason": reason})

    # The year, and every start however long ago it was.
    kept = [
        row for row in events
        if row["occurred_at"] >= stamp(YEAR_FROM) or row["type"] == "subscription.started"
    ]
    arrive(paper, kept)

    subscriptions = []
    by_shop = {}
    for row in kept:
        by_shop.setdefault(row["customer_id"], []).append(row)
    for shop in shops:
        subscription = billing.trial(shop["id"], read_stamp(shop["created_at"]))
        if shop["status"] != "trialling":
            # The shops Ada signed by hand had no trial to end.
            subscription["trial_ends_at"] = None
            latest = None
            for row in sorted(by_shop[shop["id"]], key=lambda row: (row["received_at"], row["id"])):
                if latest is None or row["occurred_at"] >= latest:
                    subscription = billing.apply(
                        subscription, row["type"], row["occurred_at"], row["payload"]
                    )
                latest = max(latest or row["occurred_at"], row["occurred_at"])
        if billing.CUSTOMER_STATUS[subscription["status"]] != shop["status"]:
            raise AssertionError(f"{shop['name']} is {shop['status']} on a {subscription}")
        subscriptions.append(subscription)

    kept.sort(key=lambda row: (row["occurred_at"], row["id"]))
    return shipments, subscriptions, kept


def arrive(paper, events):
    """When each event reached us, which is the order the billing feed would have moved on.

    The backlog came in on the morning the feed went live and everything since a few seconds after
    it happened. Two failed payments in the backlog came in just after the payment that settled
    them.
    """
    live_from = stamp(FEED_LIVE_FROM)
    by_invoice = {}
    for row in events:
        if row["type"].startswith("invoice.") and row["occurred_at"] < live_from:
            by_invoice.setdefault(row["payload"]["invoice"], []).append(row)
    pairs = [
        rows for rows in by_invoice.values()
        if [row["type"] for row in rows] == ["invoice.payment_failed", "invoice.paid"]
    ]
    behind = {
        failed["id"]: paid["occurred_at"]
        for failed, paid in paper.sample(pairs, min(LATE_ARRIVALS, len(pairs)))
    }

    def in_turn(row):
        if row["id"] in behind:
            return (behind[row["id"]], 1, row["id"])
        return (row["occurred_at"], 0, row["id"])

    moment = BACKLOG_LOADED_AT
    for row in sorted((row for row in events if row["occurred_at"] < live_from), key=in_turn):
        moment += timedelta(seconds=paper.randint(1, 4))
        row["received_at"] = stamp(moment)
    loaded = moment
    for row in sorted((row for row in events if row["occurred_at"] >= live_from), key=in_turn):
        arrived = max(read_stamp(row["occurred_at"]), loaded)
        row["received_at"] = stamp(arrived + timedelta(seconds=paper.randint(1, 40)))


# -------------------------------------------------------------------------------------- writing


def build():
    rng = random.Random(SEED)
    paper = random.Random(BILLING_SEED)
    shops = build_shops(rng)
    own_addresses(shops)
    sign_up_recently(paper, shops)
    keys = build_keys(rng, shops)
    date_signups(shops, keys)
    shipments, events = build_parcels(rng, shops)
    shipments, events = strand_a_few(rng, shipments, events)
    shipments = repeat_a_few_references(rng, shipments)
    endpoints, deliveries = build_webhooks(rng, shops, shipments)
    shipments, subscriptions, billing_events = build_billing(paper, shops, keys, shipments)
    return {
        "customers": [
            {key: value for key, value in shop.items() if not key.startswith("_")}
            for shop in shops
        ],
        "api_keys": keys,
        "subscriptions": subscriptions,
        "carriers": [dict(row) for row in CARRIERS],
        "carrier_services": service_rows(),
        "rate_cards": build_rate_cards(),
        "shipments": shipments,
        "tracking_events": events,
        "webhook_endpoints": endpoints,
        "webhook_deliveries": deliveries,
        "billing_events": billing_events,
    }


def as_text(data):
    """One record to a line."""
    parts = []
    for name, rows in data.items():
        lines = ",\n".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows
        )
        parts.append(f'"{name}": [\n{lines}\n]' if rows else f'"{name}": []')
    return "{\n" + ",\n".join(parts) + "\n}\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the bundled history.")
    parser.add_argument("--check", action="store_true", help="compare against the committed file")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    text = as_text(build())
    target = Path(args.out)
    if args.check:
        if not target.exists():
            print(f"{target} is not there")
            return 1
        if target.read_text(encoding="utf-8") != text:
            print(f"{target} is not what this script builds")
            return 1
        print(f"{target} matches")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
