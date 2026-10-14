"""Fixture world: three shops, their plans, their keys, six parcels, one webhook endpoint.

Built here rather than loaded from data/seed.json so a test that turns on one parcel can be
read. Carriers and the rate card come from app.rates and the plans from app.plans, so prices in
tests are real prices.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app import throttle
from app.db import connect, prepare
from app.main import app
from app.plans import fee_for, parcel_price
from app.rates import (
    CARRIERS,
    band_for,
    build_rate_cards,
    chargeable_grams,
    service_rows,
    zone_for,
)
from app.records import pack
from app.tracking import description_for


def price_on_card(carrier, service, recipient, parcel):
    """The card price for this parcel, so a fixture price is the card price."""
    sides = tuple(parcel["dimensions_cm"].values())
    band = band_for(chargeable_grams(parcel["weight_grams"], sides))
    zone = zone_for(recipient["postcode"])
    for row in build_rate_cards():
        if (row["carrier_code"], row["service"], row["zone"], row["max_grams"]) == (
            carrier, service, zone, band
        ):
            return row["price_pence"]
    raise LookupError(f"{carrier} {service} does not price that parcel to {zone}")

LIVE_KEY = "qp_live_wistowprovisionslivekey1"
TEST_KEY = "qp_test_wistowprovisionstestkey1"
OTHER_KEY = "qp_live_netherbycycleslivekey12"
CLOSED_KEY = "qp_live_cranbournebakerykey1234"

SHOP = "cus_wistowprovisions000001"
OTHER_SHOP = "cus_netherbycycles00000001"
CLOSED_SHOP = "cus_cranbournebakery000001"

DISPATCH = {
    "name": "Wistow Provisions",
    "line1": "Unit 6, Tannery Yard",
    "city": "Bristol",
    "postcode": "BS2 0SB",
    "phone": "07700 900118",
}

RECIPIENT = {
    "name": "Joanne Bex",
    "line1": "18 Ravensbourne Terrace",
    "city": "London",
    "postcode": "EC2A 4NE",
}

PARCEL = {
    "weight_grams": 1800,
    "dimensions_cm": {"length_cm": 32, "width_cm": 24, "height_cm": 10},
    "description": "Two glazed bowls",
}

# id, status, created_at, collected_at, delivered_at, reference
PARCELS = (
    ("shp_wistow00000000000001", "delivered", "2026-08-03T09:14:00Z",
     "2026-08-03T17:02:00Z", "2026-08-05T11:20:00Z", "WEB-20001"),
    ("shp_wistow00000000000002", "in_transit", "2026-08-24T10:31:00Z",
     "2026-08-24T16:40:00Z", None, "WEB-20002"),
    ("shp_wistow00000000000003", "held", "2026-08-25T08:02:00Z",
     "2026-08-25T15:55:00Z", None, "WEB-20003"),
    ("shp_wistow00000000000004", "created", "2026-08-28T15:47:00Z", None, None, "WEB-20004"),
    ("shp_wistow00000000000005", "created", "2026-08-29T09:05:00Z", None, None, None),
)

SCANS = (
    ("evt_wistow0000000000001", "shp_wistow00000000000001", "label_created", "Bristol",
     "2026-08-03T09:14:00Z"),
    ("evt_wistow0000000000002", "shp_wistow00000000000001", "collected", "Bristol",
     "2026-08-03T17:02:00Z"),
    ("evt_wistow0000000000003", "shp_wistow00000000000001", "in_transit", "Tanbury",
     "2026-08-04T04:35:00Z"),
    ("evt_wistow0000000000004", "shp_wistow00000000000001", "out_for_delivery", "London",
     "2026-08-05T07:11:00Z"),
    ("evt_wistow0000000000005", "shp_wistow00000000000001", "delivered", "London",
     "2026-08-05T11:20:00Z"),
    ("evt_wistow0000000000006", "shp_wistow00000000000003", "label_created", "Bristol",
     "2026-08-25T08:02:00Z"),
    ("evt_wistow0000000000007", "shp_wistow00000000000003", "collected", "Bristol",
     "2026-08-25T15:55:00Z"),
    ("evt_wistow0000000000008", "shp_wistow00000000000003", "held_at_depot", "Stanbury",
     "2026-08-26T06:40:00Z"),
    ("evt_wistow0000000000009", "shp_wistow00000000000002", "label_created", "Bristol",
     "2026-08-24T10:31:00Z"),
    ("evt_wistow0000000000010", "shp_wistow00000000000002", "collected", "Bristol",
     "2026-08-24T16:40:00Z"),
    ("evt_wistow0000000000011", "shp_wistow00000000000002", "in_transit", "Tanbury",
     "2026-08-25T03:20:00Z"),
    ("evt_wistow0000000000012", "shp_wistow00000000000004", "label_created", "Bristol",
     "2026-08-28T15:47:00Z"),
    ("evt_wistow0000000000013", "shp_wistow00000000000005", "label_created", "Bristol",
     "2026-08-29T09:05:00Z"),
)

# Wistow is on standard and Netherby pays as it goes.
SHOP_PLANS = {SHOP: "standard", OTHER_SHOP: "payg", CLOSED_SHOP: "standard"}

# What each shop pays for that parcel to EC2A on its plan, so a fixture price is a real price.
KESTREL_STANDARD = parcel_price(
    SHOP_PLANS[SHOP], price_on_card("kestrel", "standard", RECIPIENT, PARCEL)
)
WENDOVER_ECONOMY = parcel_price(
    SHOP_PLANS[OTHER_SHOP], price_on_card("wendover", "economy", RECIPIENT, PARCEL)
)

ENDPOINT_ID = "whe_wistow00000000000001"
ENDPOINT_SECRET = "whsec_wistowprovisionshooksecret01"


def add_shops(conn):
    conn.executemany(
        "INSERT INTO customers (id, name, platform, city, contact_email, status, created_at, "
        "dispatch_address) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (SHOP, "Wistow Provisions", "cartwell", "Bristol", "orders@wistowprovisions.co.uk",
             "active", "2024-11-04T10:00:00Z", pack(DISPATCH)),
            (OTHER_SHOP, "Netherby Cycles", "own build", "Netherby", "shop@netherbycycles.co.uk",
             "active", "2025-06-18T14:20:00Z", pack({**DISPATCH, "name": "Netherby Cycles"})),
            (CLOSED_SHOP, "Cranbourne Bakery", "tillbox", "Cranbourne",
             "hello@cranbournebakery.co.uk", "closed", "2024-08-01T09:00:00Z", pack(DISPATCH)),
        ],
    )
    conn.executemany(
        "INSERT INTO api_keys (key, customer_id, mode, label, created_at, last_used_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (LIVE_KEY, SHOP, "live", "Production", "2024-11-04T10:05:00Z",
             "2026-08-31T22:14:00Z"),
            (TEST_KEY, SHOP, "test", "Integration", "2024-11-04T10:05:00Z",
             "2026-08-20T11:02:00Z"),
            (OTHER_KEY, OTHER_SHOP, "live", "Checkout", "2025-06-18T14:30:00Z",
             "2026-08-30T08:41:00Z"),
            # closed account; the key is still in the table
            (CLOSED_KEY, CLOSED_SHOP, "live", "Production", "2024-08-01T09:10:00Z",
             "2026-02-11T16:30:00Z"),
        ],
    )
    conn.executemany(
        "INSERT INTO subscriptions (customer_id, plan, status, monthly_fee_pence, "
        "current_period_start, current_period_end, trial_ends_at, started_at, cancelled_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (SHOP, SHOP_PLANS[SHOP], "active", fee_for(SHOP_PLANS[SHOP]), "2026-08-04T10:00:00Z",
             "2026-09-04T10:00:00Z", None, "2024-11-04T10:00:00Z", None),
            (OTHER_SHOP, SHOP_PLANS[OTHER_SHOP], "active", fee_for(SHOP_PLANS[OTHER_SHOP]),
             None, None, None, "2025-06-18T14:20:00Z", None),
            (CLOSED_SHOP, SHOP_PLANS[CLOSED_SHOP], "cancelled", fee_for(SHOP_PLANS[CLOSED_SHOP]),
             "2026-02-01T09:00:00Z", "2026-03-01T09:00:00Z", None, "2024-08-01T09:00:00Z",
             "2026-02-19T12:40:00Z"),
        ],
    )


def add_carriers(conn):
    conn.executemany(
        "INSERT INTO carriers (code, name, collection_cutoff, tracking_prefix) "
        "VALUES (?, ?, ?, ?)",
        [
            (row["code"], row["name"], row["collection_cutoff"], row["tracking_prefix"])
            for row in CARRIERS
        ],
    )
    conn.executemany(
        "INSERT INTO carrier_services (carrier_code, service, name, description, max_grams) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (row["carrier_code"], row["service"], row["name"], row["description"],
             row["max_grams"])
            for row in service_rows()
        ],
    )
    conn.executemany(
        "INSERT INTO rate_cards (carrier_code, service, zone, max_grams, price_pence, "
        "estimated_days) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (row["carrier_code"], row["service"], row["zone"], row["max_grams"],
             row["price_pence"], row["estimated_days"])
            for row in build_rate_cards()
        ],
    )


def add_parcels(conn):
    rows = []
    for index, (parcel_id, status, created, collected, delivered, reference) in enumerate(PARCELS):
        rows.append(
            (
                parcel_id, SHOP, "live", "kestrel", "standard", status,
                f"KST100000000{index}", reference, KESTREL_STANDARD, pack(DISPATCH),
                pack(RECIPIENT),
                pack(PARCEL), created, collected, delivered,
            )
        )
    rows.append(
        (
            "shp_netherby0000000001", OTHER_SHOP, "live", "wendover", "economy", "delivered",
            "WDV9000000001", "NC-8813", WENDOVER_ECONOMY,
            pack({**DISPATCH, "name": "Netherby Cycles"}),
            pack(RECIPIENT), pack(PARCEL), "2026-08-27T12:00:00Z", "2026-08-27T18:30:00Z",
            "2026-08-29T10:05:00Z",
        )
    )
    conn.executemany(
        "INSERT INTO shipments (id, customer_id, mode, carrier_code, service, status, "
        "tracking_number, reference, price_pence, sender, recipient, parcel, created_at, "
        "collected_at, delivered_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.executemany(
        "INSERT INTO tracking_events (id, shipment_id, code, description, location, occurred_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (scan[0], scan[1], scan[2], description_for(scan[2]), scan[3], scan[4])
            for scan in SCANS
        ],
    )


def add_endpoint(conn):
    conn.execute(
        "INSERT INTO webhook_endpoints (id, customer_id, url, events, secret, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?)",
        (
            ENDPOINT_ID,
            SHOP,
            "https://wistowprovisions.co.uk/hooks/quillon",
            json.dumps(
                ["shipment.cancelled", "shipment.created", "shipment.delivered",
                 "tracking.updated"]
            ),
            ENDPOINT_SECRET,
            "2025-01-09T11:00:00Z",
        ),
    )


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A database of this test's own, with the small world already in it."""
    path = tmp_path / "quillon.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    conn = prepare(connect(path))
    add_shops(conn)
    add_carriers(conn)
    add_parcels(conn)
    add_endpoint(conn)
    conn.close()
    throttle.clear()
    yield path
    throttle.clear()


@pytest.fixture()
def conn(store):
    opened = connect(store)
    yield opened
    opened.close()


@pytest.fixture()
def client(store):
    with TestClient(app) as opened:
        yield opened


@pytest.fixture()
def live():
    return {"Authorization": f"Bearer {LIVE_KEY}"}


@pytest.fixture()
def sandbox():
    return {"Authorization": f"Bearer {TEST_KEY}"}
