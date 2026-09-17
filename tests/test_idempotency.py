"""Idempotency-Key: a checkout that retries books one parcel, not two."""

from conftest import PARCEL, RECIPIENT

BODY = {
    "recipient": RECIPIENT,
    "parcel": PARCEL,
    "carrier_code": "wendover",
    "service": "economy",
}


def test_the_same_key_and_the_same_body_give_the_first_answer_back(client, live):
    first = client.post(
        "/v1/shipments", headers={**live, "Idempotency-Key": "checkout-8814"}, json=BODY
    )
    again = client.post(
        "/v1/shipments", headers={**live, "Idempotency-Key": "checkout-8814"}, json=BODY
    )
    assert first.status_code == 201
    assert again.status_code == 201
    assert again.json() == first.json()
    assert again.headers["Quillon-Idempotent-Replay"] == "true"
    listed = client.get("/v1/shipments", headers=live).json()["data"]
    assert [row["id"] for row in listed].count(first.json()["id"]) == 1

    # No key: the same body twice is two parcels.
    one = client.post("/v1/shipments", headers=live, json=BODY)
    two = client.post("/v1/shipments", headers=live, json=BODY)
    assert one.json()["id"] != two.json()["id"]
    assert one.json()["tracking_number"] != two.json()["tracking_number"]


def test_the_same_key_on_a_different_body_is_a_conflict(client, live):
    client.post(
        "/v1/shipments", headers={**live, "Idempotency-Key": "checkout-8815"}, json=BODY
    )
    changed = client.post(
        "/v1/shipments",
        headers={**live, "Idempotency-Key": "checkout-8815"},
        json={**BODY, "reference": "WEB-91"},
    )
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_conflict"


def test_a_cancel_sent_twice_under_one_key_stops_one_parcel_once(client, live):
    made = client.post("/v1/shipments", headers=live, json=BODY).json()
    headers = {**live, "Idempotency-Key": "stop-that-one"}
    first = client.post(f"/v1/shipments/{made['id']}/cancel", headers=headers)
    again = client.post(f"/v1/shipments/{made['id']}/cancel", headers=headers)
    assert first.status_code == 200
    assert again.status_code == 200
    assert again.json()["cancelled_at"] == first.json()["cancelled_at"]
