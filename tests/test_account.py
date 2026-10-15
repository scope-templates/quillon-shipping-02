"""GET /v1/account: the plan, where the subscription stands, and the month so far."""

from contextlib import closing
from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import connect, prepare
from app.ids import now, stamp
from app.main import app
from app.records import pack
from conftest import DISPATCH, OTHER_KEY, PARCEL, RECIPIENT, SHOP

# The two tables a key is looked up in, as a store made before subscriptions had them.
OLDER_STORE = """
CREATE TABLE customers (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    platform      TEXT NOT NULL,
    city          TEXT NOT NULL,
    contact_email TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    dispatch_address TEXT
);
CREATE TABLE api_keys (
    key          TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    mode         TEXT NOT NULL,
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
INSERT INTO customers VALUES ('cus_olderstorewistow00001', 'Wistow Provisions', 'cartwell',
    'Bristol', 'orders@wistowprovisions.co.uk', 'active', '2024-11-04T10:00:00Z', NULL);
INSERT INTO customers VALUES ('cus_olderstorecranbourne1', 'Cranbourne Bakery', 'tillbox',
    'Cranbourne', 'hello@cranbournebakery.co.uk', 'closed', '2024-08-01T09:00:00Z', NULL);
INSERT INTO api_keys VALUES ('qp_live_olderstorewistowkey01', 'cus_olderstorewistow00001',
    'live', 'Production', '2024-11-04T10:05:00Z', NULL);
"""

SUBSCRIPTIONS = (
    "SELECT customer_id, plan, status, monthly_fee_pence, current_period_start, trial_ends_at, "
    "started_at, cancelled_at FROM subscriptions ORDER BY customer_id"
)

BOOKING = {
    "recipient": RECIPIENT,
    "parcel": PARCEL,
    "carrier_code": "wendover",
    "service": "economy",
}


def book(client, headers):
    made = client.post("/v1/shipments", headers=headers, json=BOOKING)
    assert made.status_code == 201
    return made.json()


def add_parcel_last_month(conn):
    """One parcel a second before this month began, which is last month's and not this one's."""
    began = now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    conn.execute(
        "INSERT INTO shipments (id, customer_id, mode, carrier_code, service, status, "
        "tracking_number, price_pence, sender, recipient, parcel, created_at) "
        "VALUES ('shp_wistowlastmonth00001', ?, 'live', 'wendover', 'economy', 'created', "
        "'WDV9000000777', 455, ?, ?, ?, ?)",
        (SHOP, pack(DISPATCH), pack(RECIPIENT), pack(PARCEL),
         stamp(began - timedelta(seconds=1))),
    )


def test_the_account_says_its_plan_and_where_the_subscription_stands(client, live):
    answer = client.get("/v1/account", headers=live)
    assert answer.status_code == 200
    body = answer.json()
    assert body["id"] == SHOP
    assert body["name"] == "Wistow Provisions"
    assert body["platform"] == "cartwell"
    assert body["mode"] == "live"
    assert body["plan"] == "standard"
    assert body["status"] == "active"
    assert body["current_period_start"] == "2026-08-04T10:00:00Z"
    assert body["current_period_end"] == "2026-09-04T10:00:00Z"
    assert body["trial_ends_at"] is None
    assert body["technical_contact_name"] is None
    assert body["technical_contact_email"] is None
    assert body["this_month"]["month"] == now().strftime("%Y-%m")


def test_the_month_counts_this_months_parcels_on_this_mode(client, live, conn):
    add_parcel_last_month(conn)
    before = client.get("/v1/account", headers=live).json()["this_month"]

    first = book(client, live)
    second = book(client, live)
    stopped = book(client, live)
    assert client.post(f"/v1/shipments/{stopped['id']}/cancel", headers=live).status_code == 200

    month = client.get("/v1/account", headers=live).json()["this_month"]
    assert month["parcels"] == before["parcels"] + 2
    assert month["spend_pence"] == (
        before["spend_pence"] + first["price_pence"] + second["price_pence"]
    )
    assert month["last_booked_at"] == second["created_at"]


def test_a_test_key_sees_the_same_account_and_only_its_test_parcels(client, live, sandbox):
    book(client, live)
    on_test = client.get("/v1/account", headers=sandbox).json()
    assert on_test["id"] == SHOP
    assert on_test["mode"] == "test"
    assert on_test["plan"] == "standard"
    assert on_test["this_month"]["parcels"] == 0
    assert on_test["this_month"]["spend_pence"] == 0
    assert on_test["this_month"]["last_booked_at"] is None

    sampled = book(client, sandbox)
    month = client.get("/v1/account", headers=sandbox).json()["this_month"]
    assert month["parcels"] == 1
    assert month["spend_pence"] == sampled["price_pence"]


def test_each_key_sees_its_own_account(client):
    theirs = client.get("/v1/account", headers={"Authorization": f"Bearer {OTHER_KEY}"}).json()
    assert theirs["name"] == "Netherby Cycles"
    assert theirs["plan"] == "payg"

    trialling = client.post(
        "/signups",
        json={"shop_name": "Penhale Prints", "contact_email": "shop@penhaleprints.co.uk",
              "platform": "tillbox", "city": "Penhale"},
    ).json()
    mine = client.get(
        "/v1/account", headers={"Authorization": f"Bearer {trialling['key']}"}
    ).json()
    assert mine["status"] == "trialling"
    assert mine["plan"] == "payg"
    assert mine["trial_ends_at"] == trialling["subscription"]["trial_ends_at"]
    assert mine["this_month"]["parcels"] == 0

    assert client.get("/v1/account").json()["code"] == "missing_credentials"


def test_a_store_from_before_subscriptions_gives_every_shop_one(tmp_path, monkeypatch):
    older = tmp_path / "older.sqlite"
    with closing(connect(older)) as conn:
        conn.executescript(OLDER_STORE)
        prepare(conn)
        given = [tuple(row) for row in conn.execute(SUBSCRIPTIONS).fetchall()]
        assert given == [
            ("cus_olderstorecranbourne1", "payg", "cancelled", 0, None, None,
             "2024-08-01T09:00:00Z", None),
            ("cus_olderstorewistow00001", "payg", "active", 0, None, None,
             "2024-11-04T10:00:00Z", None),
        ]
        # Opening it again leaves them as they are, and finds the shop added since.
        conn.execute(
            "INSERT INTO customers (id, name, platform, city, contact_email, status, created_at) "
            "VALUES ('cus_olderstorenetherby001', 'Netherby Cycles', "
            "'own build', 'Netherby', 'shop@netherbycycles.co.uk', 'active', "
            "'2025-06-18T14:20:00Z')"
        )
        prepare(conn)
        assert [tuple(row) for row in conn.execute(SUBSCRIPTIONS).fetchall()] == sorted(given + [
            ("cus_olderstorenetherby001", "payg", "active", 0, None, None,
             "2025-06-18T14:20:00Z", None),
        ])

    monkeypatch.setenv("DATABASE_PATH", str(older))
    with TestClient(app) as opened:
        mine = opened.get(
            "/v1/account", headers={"Authorization": "Bearer qp_live_olderstorewistowkey01"}
        )
    assert mine.status_code == 200
    assert mine.json()["plan"] == "payg"
    assert mine.json()["status"] == "active"
    assert mine.json()["current_period_start"] is None


def test_a_shop_added_while_the_service_runs_is_given_its_first_subscription(
    client, conn, monkeypatch
):
    conn.executescript(
        """
        INSERT INTO customers (id, name, platform, city, contact_email, status, created_at)
        VALUES ('cus_addedbyhandmarfield01', 'Marfield Kitchen', 'bramble', 'Marfield',
                'hello@marfieldkitchen.co.uk', 'active', '2026-09-02T11:00:00Z'),
               ('cus_addedbyhandpenhale001', 'Penhale Prints', 'tillbox', 'Penhale',
                'shop@penhaleprints.co.uk', 'trialling', '2026-09-03T15:20:00Z');
        INSERT INTO api_keys (key, customer_id, mode, label, created_at) VALUES
            ('qp_live_addedbyhandmarfield01', 'cus_addedbyhandmarfield01', 'live', 'Production',
             '2026-09-02T11:05:00Z'),
            ('qp_test_addedbyhandpenhale001', 'cus_addedbyhandpenhale001', 'test', 'Integration',
             '2026-09-03T15:20:00Z');
        """
    )
    running = client.get(
        "/v1/account", headers={"Authorization": "Bearer qp_live_addedbyhandmarfield01"}
    )
    assert running.status_code == 200
    assert running.json()["plan"] == "payg"
    assert running.json()["status"] == "active"
    assert running.json()["current_period_start"] is None

    trialling = client.get(
        "/v1/account", headers={"Authorization": "Bearer qp_test_addedbyhandpenhale001"}
    )
    assert trialling.json()["status"] == "trialling"
    assert trialling.json()["trial_ends_at"] == "2026-10-03T15:20:00Z"

    monkeypatch.setenv("BILLING_SECRET", "billing-feed-secret-for-tests")
    started = client.post(
        "/billing/events",
        headers={"Billing-Secret": "billing-feed-secret-for-tests"},
        json={"type": "subscription.started", "customer_id": "cus_addedbyhandpenhale001",
              "occurred_at": "2026-09-10T09:00:00Z", "data": {"plan": "standard"}},
    )
    assert started.status_code == 200
    assert started.json()["moved"] is True
    assert started.json()["status"] == "active"
