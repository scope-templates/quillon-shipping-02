"""What can still be stopped, and what the carrier has told us so far."""

CREATED = "shp_wistow00000000000004"
IN_TRANSIT = "shp_wistow00000000000002"
DELIVERED = "shp_wistow00000000000001"
HELD = "shp_wistow00000000000003"


def test_a_parcel_the_driver_has_not_got_yet_can_be_stopped(client, live):
    answer = client.post(f"/v1/shipments/{CREATED}/cancel", headers=live)
    assert answer.status_code == 200
    assert answer.json()["status"] == "cancelled"
    assert answer.json()["cancelled_at"]

    scans = client.get(f"/v1/shipments/{CREATED}/events", headers=live).json()
    assert scans["status"] == "cancelled"
    assert scans["data"][-1]["code"] == "cancelled"
    assert scans["data"][-1]["description"] == "Cancelled before collection"

    again = client.post(f"/v1/shipments/{CREATED}/cancel", headers=live)
    assert again.status_code == 409
    assert again.json()["detail"] == "This shipment was already cancelled."


def test_a_parcel_the_carrier_has_cannot_be_stopped(client, live):
    answer = client.post(f"/v1/shipments/{IN_TRANSIT}/cancel", headers=live)
    assert answer.status_code == 409
    assert answer.json()["code"] == "not_cancellable"
    assert "in transit" in answer.json()["detail"]

    delivered = client.post(f"/v1/shipments/{DELIVERED}/cancel", headers=live)
    assert delivered.status_code == 409
    assert "delivered" in delivered.json()["detail"]


def test_the_scans_come_back_oldest_first_with_the_words_we_show_a_shopper(client, live):
    answer = client.get(f"/v1/shipments/{DELIVERED}/events", headers=live)
    assert answer.status_code == 200
    body = answer.json()
    assert body["status"] == "delivered"
    assert [row["code"] for row in body["data"]] == [
        "label_created", "collected", "in_transit", "out_for_delivery", "delivered"
    ]
    assert [row["occurred_at"] for row in body["data"]] == sorted(
        row["occurred_at"] for row in body["data"]
    )
    assert body["data"][-1]["location"] == "London"


def test_a_parcel_sitting_in_a_depot_says_where_it_is(client, live):
    body = client.get(f"/v1/shipments/{HELD}/events", headers=live).json()
    assert body["status"] == "held"
    assert body["data"][-1]["code"] == "held_at_depot"
    assert body["data"][-1]["location"] == "Stanbury"

    nothing = client.get("/v1/shipments/shp_nothing/events", headers=live)
    assert nothing.status_code == 404
    assert nothing.json()["code"] == "not_found"
