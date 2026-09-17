"""Booking a parcel, and reading it back."""

from conftest import DISPATCH, OTHER_KEY, PARCEL, RECIPIENT

QUOTE = {
    "from_postcode": "BS1 4DJ",
    "to_postcode": "EC2A 4NE",
    "weight_grams": 1800,
    "dimensions_cm": {"length_cm": 32, "width_cm": 24, "height_cm": 10},
}


def book(client, live, **over):
    body = {"recipient": RECIPIENT, "parcel": PARCEL}
    body.update(over)
    return client.post("/v1/shipments", headers=live, json=body)


def test_a_quote_becomes_a_parcel_at_the_price_it_was_quoted(client, live):
    quoted = client.post("/v1/rates/quotes", headers=live, json=QUOTE).json()["quotes"][0]
    made = book(client, live, quote_id=quoted["id"], reference="WEB-30001")
    assert made.status_code == 201
    parcel = made.json()
    assert parcel["status"] == "created"
    assert parcel["price_pence"] == quoted["price_pence"]
    assert parcel["carrier_code"] == quoted["carrier_code"]
    assert parcel["tracking_number"].startswith("KST") or parcel["tracking_number"][:3].isalpha()
    assert client.get(f"/v1/shipments/{parcel['id']}", headers=live).json() == parcel


def test_a_carrier_and_a_service_are_priced_off_the_card(client, live):
    made = book(client, live, carrier_code="wendover", service="economy")
    assert made.status_code == 201
    assert made.json()["carrier_code"] == "wendover"
    assert made.json()["price_pence"] > 0

    wrong = book(client, live, carrier_code="bluecoat", service="before_noon",
                 recipient={**RECIPIENT, "city": "Netherby", "postcode": "TA1 3QP"})
    assert wrong.status_code == 422
    assert wrong.json()["code"] == "rate_unavailable"


def test_the_account_address_stands_in_when_no_sender_is_sent(client, live):
    made = book(client, live, carrier_code="wendover", service="economy")
    assert made.json()["sender"]["postcode"] == DISPATCH["postcode"]
    assert made.json()["sender"]["name"] == DISPATCH["name"]

    theirs = book(
        client, live, carrier_code="wendover", service="economy",
        sender={**DISPATCH, "name": "Wistow Provisions, Bath shop", "postcode": "BA1 5LR"},
    )
    assert theirs.json()["sender"]["postcode"] == "BA1 5LR"


def test_a_reference_is_kept_to_one_parcel_on_an_account(client, live):
    first = book(client, live, carrier_code="wendover", service="economy", reference="WEB-77")
    assert first.status_code == 201
    again = book(client, live, carrier_code="wendover", service="economy", reference="WEB-77")
    assert again.status_code == 409
    assert again.json()["code"] == "reference_in_use"
    assert first.json()["id"] in again.json()["detail"]

    # The other shop has that reference free, and cannot see ours.
    theirs = {"Authorization": f"Bearer {OTHER_KEY}"}
    mine = client.get(f"/v1/shipments/{first.json()['id']}", headers=theirs)
    assert mine.status_code == 404
    assert mine.json()["code"] == "not_found"


def test_a_parcel_booked_on_a_test_key_is_not_there_for_the_live_one(client, live, sandbox):
    sandboxed = client.post(
        "/v1/shipments",
        headers=sandbox,
        json={"recipient": RECIPIENT, "parcel": PARCEL, "carrier_code": "wendover",
              "service": "economy", "reference": "WEB-88"},
    ).json()
    assert sandboxed["mode"] == "test"

    assert client.get(f"/v1/shipments/{sandboxed['id']}", headers=live).status_code == 404
    assert client.post(f"/v1/shipments/{sandboxed['id']}/label", headers=live).status_code == 404
    assert client.post(f"/v1/shipments/{sandboxed['id']}/cancel", headers=live).status_code == 404
    assert client.get(f"/v1/shipments/{sandboxed['id']}/events", headers=live).status_code == 404

    # The reference is free on the live side, because it is kept per mode.
    live_one = book(client, live, carrier_code="wendover", service="economy", reference="WEB-88")
    assert live_one.status_code == 201
