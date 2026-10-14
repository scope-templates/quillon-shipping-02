"""The billing feed: one event at a time, on the secret we share with the billing provider."""

import json

import pytest

from app import billing
from app.ids import read_stamp
from conftest import OTHER_KEY, OTHER_SHOP, SHOP

SECRET = "billing-feed-secret-for-tests"
FEED = "/billing/events"
NEW_SHOP = "cus_halloway0candles000001"


@pytest.fixture()
def provider(monkeypatch):
    monkeypatch.setenv("BILLING_SECRET", SECRET)
    return {"Billing-Secret": SECRET}


def event(kind, occurred_at, customer_id=SHOP, **data):
    return {"type": kind, "customer_id": customer_id, "occurred_at": occurred_at, "data": data}


def subscription(conn, customer_id):
    return dict(
        conn.execute("SELECT * FROM subscriptions WHERE customer_id = ?", (customer_id,))
        .fetchone()
    )


def customer_status(conn, customer_id):
    return conn.execute("SELECT status FROM customers WHERE id = ?", (customer_id,)).fetchone()[0]


def add_trialling_shop(conn):
    conn.execute(
        "INSERT INTO customers (id, name, platform, city, contact_email, status, created_at) "
        "VALUES (?, 'Halloway Candles', 'bramble', 'Halloway', 'hello@hallowaycandles.co.uk', "
        "'trialling', '2026-08-20T10:12:00Z')",
        (NEW_SHOP,),
    )
    billing.save(conn, billing.trial(NEW_SHOP, read_stamp("2026-08-20T10:12:00Z")))


def test_the_feed_is_closed_without_the_secret(client, monkeypatch):
    unset = client.post(FEED, json=event("invoice.paid", "2026-09-04T10:00:00Z"))
    assert unset.status_code == 401
    assert unset.json()["code"] == "invalid_billing_secret"

    monkeypatch.setenv("BILLING_SECRET", SECRET)
    wrong = client.post(
        FEED,
        headers={"Billing-Secret": "not-the-secret"},
        json=event("invoice.paid", "2026-09-04T10:00:00Z"),
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "invalid_billing_secret"

    bare = client.post(FEED, json=event("invoice.paid", "2026-09-04T10:00:00Z"))
    assert bare.status_code == 401

    garbled = client.post(
        FEED,
        headers={"Billing-Secret": "billing-feed-secrét".encode("latin-1")},
        json=event("invoice.paid", "2026-09-04T10:00:00Z"),
    )
    assert garbled.status_code == 401


def test_a_start_puts_a_trialling_shop_on_its_plan(client, provider, conn):
    add_trialling_shop(conn)
    started = client.post(
        FEED,
        headers=provider,
        json=event("subscription.started", "2026-09-02T09:30:00Z", NEW_SHOP, plan="standard"),
    )
    assert started.status_code == 200
    assert started.json()["plan"] == "standard"
    assert started.json()["status"] == "active"
    assert started.json()["moved"] is True
    assert started.json()["id"].startswith("bev_")

    after = subscription(conn, NEW_SHOP)
    assert after["monthly_fee_pence"] == 1200
    assert after["started_at"] == "2026-09-02T09:30:00Z"
    assert after["current_period_start"] == "2026-09-02T09:30:00Z"
    assert after["current_period_end"] == "2026-10-02T09:30:00Z"
    assert after["trial_ends_at"] == "2026-09-19T10:12:00Z"
    assert customer_status(conn, NEW_SHOP) == "active"


def test_a_plan_change_moves_the_plan_and_the_fee(client, provider, conn):
    moved = client.post(
        FEED,
        headers=provider,
        json=event("subscription.plan_changed", "2026-08-21T15:02:00Z", from_plan="standard",
                   plan="volume"),
    )
    assert moved.json()["plan"] == "volume"
    assert moved.json()["status"] == "active"
    after = subscription(conn, SHOP)
    assert after["monthly_fee_pence"] == 4500
    assert after["current_period_end"] == "2026-09-04T10:00:00Z"


def test_a_failed_payment_and_then_a_paid_one(client, provider, conn, live):
    failed = client.post(
        FEED,
        headers=provider,
        json=event("invoice.payment_failed", "2026-09-04T10:00:00Z", amount_pence=1200,
                   reason="The card was declined"),
    )
    assert failed.json()["status"] == "past_due"
    assert subscription(conn, SHOP)["current_period_end"] == "2026-09-04T10:00:00Z"
    # The shop still has its keys while the provider tries the card again.
    assert customer_status(conn, SHOP) == "active"
    assert client.get("/v1/carriers", headers=live).status_code == 200

    paid = client.post(
        FEED,
        headers=provider,
        json=event("invoice.paid", "2026-09-07T08:15:00Z", amount_pence=1200),
    )
    assert paid.json()["status"] == "active"
    after = subscription(conn, SHOP)
    assert after["current_period_start"] == "2026-09-07T08:15:00Z"
    assert after["current_period_end"] == "2026-10-07T08:15:00Z"


def test_a_cancellation_closes_the_shop(client, provider, conn):
    theirs = {"Authorization": f"Bearer {OTHER_KEY}"}
    assert client.get("/v1/carriers", headers=theirs).status_code == 200

    cancelled = client.post(
        FEED,
        headers=provider,
        json=event("subscription.cancelled", "2026-09-10T17:45:00Z", OTHER_SHOP,
                   reason="Stopped selling online"),
    )
    assert cancelled.json()["status"] == "cancelled"
    assert subscription(conn, OTHER_SHOP)["cancelled_at"] == "2026-09-10T17:45:00Z"
    assert customer_status(conn, OTHER_SHOP) == "closed"

    refused = client.get("/v1/carriers", headers=theirs)
    assert refused.status_code == 401
    assert refused.json()["code"] == "account_closed"

    # A cancelled subscription is finished with: what comes after it is kept and moves nothing.
    late = client.post(
        FEED, headers=provider, json=event("invoice.paid", "2026-09-18T14:20:00Z", OTHER_SHOP)
    )
    assert late.status_code == 200
    assert late.json()["moved"] is False
    assert late.json()["status"] == "cancelled"


def test_an_event_older_than_the_last_one_is_kept_and_moves_nothing(client, provider, conn):
    client.post(FEED, headers=provider, json=event("invoice.paid", "2026-09-04T10:00:00Z"))
    stale = client.post(
        FEED,
        headers=provider,
        json=event("invoice.payment_failed", "2026-09-04T09:59:00Z", amount_pence=1200),
    )
    assert stale.status_code == 200
    assert stale.json()["moved"] is False
    assert stale.json()["status"] == "active"
    assert subscription(conn, SHOP)["status"] == "active"

    kept = conn.execute(
        "SELECT type, occurred_at, payload FROM billing_events WHERE customer_id = ? "
        "ORDER BY occurred_at",
        (SHOP,),
    ).fetchall()
    assert [(row["type"], row["occurred_at"]) for row in kept] == [
        ("invoice.payment_failed", "2026-09-04T09:59:00Z"),
        ("invoice.paid", "2026-09-04T10:00:00Z"),
    ]
    assert json.loads(kept[0]["payload"]) == {"amount_pence": 1200}


def test_what_the_feed_will_not_take(client, provider):
    nobody = client.post(
        FEED, headers=provider, json=event("invoice.paid", "2026-09-04T10:00:00Z", "cus_nobody")
    )
    assert nobody.status_code == 404
    assert nobody.json()["code"] == "not_found"

    unknown = client.post(FEED, headers=provider, json=event("invoice.refunded", "2026-09-04"))
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "validation_failed"

    no_plan = client.post(
        FEED, headers=provider, json=event("subscription.plan_changed", "2026-09-04T10:00:00Z")
    )
    assert no_plan.status_code == 422
    assert "data.plan" in no_plan.json()["detail"]

    no_zone = client.post(
        FEED, headers=provider, json=event("invoice.paid", "2026-09-04T10:00:00")
    )
    assert no_zone.status_code == 422
    assert "occurred_at" in no_zone.json()["detail"]
