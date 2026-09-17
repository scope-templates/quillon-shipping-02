"""Endpoints, the signature we send with a delivery, and the queue behind it."""

import json

from app import webhooks
from conftest import ENDPOINT_ID, ENDPOINT_SECRET, PARCEL, RECIPIENT

BODY = {
    "recipient": RECIPIENT,
    "parcel": PARCEL,
    "carrier_code": "wendover",
    "service": "economy",
}


def test_the_secret_is_shown_once_when_the_endpoint_is_made(client, live):
    made = client.post(
        "/v1/webhooks",
        headers=live,
        json={"url": "https://wistowprovisions.co.uk/hooks/late", "events": [
            "shipment.delivered"]},
    )
    assert made.status_code == 201
    assert made.json()["secret"].startswith("whsec_")

    listed = client.get("/v1/webhooks", headers=live).json()["data"]
    assert made.json()["id"] in [row["id"] for row in listed]
    assert all(row.get("secret") is None for row in listed)

    in_the_clear = client.post(
        "/v1/webhooks",
        headers=live,
        json={"url": "http://wistowprovisions.co.uk/hooks", "events": ["shipment.created"]},
    )
    assert in_the_clear.status_code == 422
    assert in_the_clear.json()["code"] == "validation_failed"


def test_a_signature_is_the_timestamp_and_the_body_under_the_endpoint_secret():
    body = b'{"id":"whev_1","type":"shipment.created"}'
    header = webhooks.sign(ENDPOINT_SECRET, body, timestamp=1788000000)
    assert header.startswith("t=1788000000,v1=")
    assert webhooks.verify(ENDPOINT_SECRET, body, header, now_seconds=1788000100)
    assert not webhooks.verify("whsec_someoneelses", body, header, now_seconds=1788000100)
    assert not webhooks.verify(ENDPOINT_SECRET, b'{"id":"whev_2"}', header, now_seconds=1788000100)
    assert not webhooks.verify(ENDPOINT_SECRET, body, header, now_seconds=1788090000)


def test_booking_a_parcel_writes_a_delivery_for_a_listening_endpoint(client, live, conn):
    made = client.post("/v1/shipments", headers=live, json=BODY).json()
    rows = conn.execute(
        "SELECT * FROM webhook_deliveries WHERE shipment_id = ?", (made["id"],)
    ).fetchall()
    assert len(rows) == 1
    delivery = dict(rows[0])
    assert delivery["endpoint_id"] == ENDPOINT_ID
    assert delivery["event_type"] == "shipment.created"
    assert delivery["status"] == "pending"
    assert delivery["attempts"] == 0
    payload = json.loads(delivery["payload"])
    assert payload["data"]["tracking_number"] == made["tracking_number"]
    assert payload["id"].startswith("whev_")


def test_deleting_an_endpoint_stops_it_and_empties_its_queue(client, live, conn):
    client.post("/v1/shipments", headers=live, json=BODY)
    assert client.delete(f"/v1/webhooks/{ENDPOINT_ID}", headers=live).status_code == 204
    assert client.get("/v1/webhooks", headers=live).json()["data"] == []

    waiting = conn.execute(
        "SELECT status FROM webhook_deliveries WHERE endpoint_id = ?", (ENDPOINT_ID,)
    ).fetchall()
    assert {row["status"] for row in waiting} == {"given_up"}
    assert client.delete(f"/v1/webhooks/{ENDPOINT_ID}", headers=live).status_code == 404


def test_the_wait_between_attempts_gets_longer_and_then_we_stop(client):
    assert webhooks.next_attempt_at(0, "2026-09-01T10:00:00Z") == "2026-09-01T10:00:00Z"
    assert webhooks.next_attempt_at(1, "2026-09-01T10:00:00Z") == "2026-09-01T10:00:30Z"
    assert webhooks.next_attempt_at(4, "2026-09-01T10:00:00Z") == "2026-09-01T10:30:00Z"
    assert webhooks.next_attempt_at(webhooks.MAX_ATTEMPTS, "2026-09-01T10:00:00Z") is None
