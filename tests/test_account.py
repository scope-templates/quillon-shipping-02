"""GET /v1/account: the plan, where the subscription stands, and the month so far."""

from datetime import timedelta

from app.ids import now, stamp
from app.records import pack
from conftest import DISPATCH, OTHER_KEY, PARCEL, RECIPIENT, SHOP

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
