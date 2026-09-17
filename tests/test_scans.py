"""The carrier feed: one scan at a time, on the carrier's own secret."""

import pytest

CREATED = "shp_wistow00000000000004"
TRACKING = "KST1000000003"
SECRET = "kestrel-feed-secret-for-tests"
FEED = "/carriers/kestrel/scans"


@pytest.fixture()
def carrier(monkeypatch):
    monkeypatch.setenv("CARRIER_SECRET_KESTREL", SECRET)
    return {"Authorization": f"Bearer {SECRET}"}


def scan(code, occurred_at, location="Tanbury"):
    return {
        "tracking_number": TRACKING,
        "code": code,
        "occurred_at": occurred_at,
        "location": location,
    }


def test_a_scan_moves_the_parcel_on_and_tells_the_endpoints(client, live, carrier, conn):
    collected = client.post(FEED, headers=carrier, json=scan("collected", "2026-09-01T16:40:00Z"))
    assert collected.status_code == 200
    assert collected.json() == {
        "shipment_id": CREATED, "status": "collected", "recorded": True
    }

    delivered = client.post(
        FEED, headers=carrier, json=scan("delivered", "2026-09-03T11:02:00Z", "London")
    )
    assert delivered.json()["status"] == "delivered"

    parcel = client.get(f"/v1/shipments/{CREATED}", headers=live).json()
    assert parcel["status"] == "delivered"
    assert parcel["collected_at"] == "2026-09-01T16:40:00Z"
    assert parcel["delivered_at"] == "2026-09-03T11:02:00Z"

    scans = client.get(f"/v1/shipments/{CREATED}/events", headers=live).json()["data"]
    assert [row["code"] for row in scans] == ["label_created", "collected", "delivered"]
    assert scans[-1]["description"] == "Delivered"

    told = conn.execute(
        "SELECT event_type, COUNT(*) AS how_many FROM webhook_deliveries "
        "WHERE shipment_id = ? GROUP BY event_type",
        (CREATED,),
    ).fetchall()
    assert dict((row["event_type"], row["how_many"]) for row in told) == {
        "tracking.updated": 2,
        "shipment.delivered": 1,
    }

    again = client.post(FEED, headers=carrier, json=scan("delivered", "2026-09-03T11:02:00Z"))
    assert again.status_code == 409


def test_the_same_scan_twice_is_recorded_once(client, live, carrier):
    first = client.post(FEED, headers=carrier, json=scan("collected", "2026-09-01T16:40:00Z"))
    second = client.post(FEED, headers=carrier, json=scan("collected", "2026-09-01T16:40:00Z"))
    assert first.json()["recorded"] is True
    assert second.json()["recorded"] is False
    scans = client.get(f"/v1/shipments/{CREATED}/events", headers=live).json()["data"]
    assert [row["code"] for row in scans].count("collected") == 1


def test_a_scan_without_the_right_secret_goes_nowhere(client, carrier):
    wrong = client.post(
        FEED,
        headers={"Authorization": "Bearer not-the-secret"},
        json=scan("collected", "2026-09-01T16:40:00Z"),
    )
    assert wrong.status_code == 401
    assert wrong.json()["code"] == "invalid_carrier_secret"

    bare = client.post(FEED, json=scan("collected", "2026-09-01T16:40:00Z"))
    assert bare.status_code == 401

    # The secret is per carrier, and Wendover has none set at all.
    elsewhere = client.post(
        "/carriers/wendover/scans",
        headers=carrier,
        json=scan("collected", "2026-09-01T16:40:00Z"),
    )
    assert elsewhere.status_code == 401


def test_a_cancelled_parcel_takes_no_more_scans(client, live, carrier):
    assert client.post(f"/v1/shipments/{CREATED}/cancel", headers=live).status_code == 200
    refused = client.post(FEED, headers=carrier, json=scan("collected", "2026-09-01T16:40:00Z"))
    assert refused.status_code == 409
    assert refused.json()["code"] == "not_scannable"
    assert "cancelled" in refused.json()["detail"]

    unknown = client.post(
        FEED,
        headers=carrier,
        json={
            "tracking_number": "KST9999999999",
            "code": "collected",
            "occurred_at": "2026-09-01T16:40:00Z",
        },
    )
    assert unknown.status_code == 404
