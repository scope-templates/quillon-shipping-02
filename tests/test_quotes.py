"""Pricing a parcel before anybody commits to it."""

from app.plans import parcel_price
from conftest import OTHER_KEY

PARCEL = {
    "from_postcode": "BS1 4DJ",
    "to_postcode": "EC2A 4NE",
    "weight_grams": 1800,
    "dimensions_cm": {"length_cm": 32, "width_cm": 24, "height_cm": 10},
}


def quote(client, live, **over):
    return client.post("/v1/rates/quotes", headers=live, json={**PARCEL, **over})


def test_quotes_come_back_cheapest_first_with_an_id_to_book_on(client, live):
    answer = quote(client, live)
    assert answer.status_code == 200
    body = answer.json()
    prices = [line["price_pence"] for line in body["quotes"]]
    assert prices == sorted(prices)
    assert all(line["id"].startswith("qt_") for line in body["quotes"])
    assert all(line["estimated_days"] >= 1 for line in body["quotes"])
    assert body["zone"] == "london"
    assert body["chargeable_weight_grams"] == 1800

    # A big light box is charged for the room it takes up rather than what it weighs.
    bulky = quote(
        client, live, weight_grams=900,
        dimensions_cm={"length_cm": 60, "width_cm": 40, "height_cm": 30},
    )
    assert bulky.json()["chargeable_weight_grams"] == 14400
    assert min(line["price_pence"] for line in bulky.json()["quotes"]) > min(prices)


def test_asking_for_one_service_prices_only_that_service(client, live):
    answer = quote(client, live, service="economy")
    assert answer.status_code == 200
    assert {line["service"] for line in answer.json()["quotes"]} == {"economy"}
    assert {line["carrier_code"] for line in answer.json()["quotes"]} == {"wendover"}


def test_a_parcel_we_cannot_price_is_refused_with_a_reason(client, live):
    too_long = quote(
        client, live, dimensions_cm={"length_cm": 150, "width_cm": 20, "height_cm": 20}
    )
    assert too_long.status_code == 422
    assert too_long.json()["code"] == "rate_unavailable"

    too_heavy = quote(client, live, weight_grams=45000)
    assert too_heavy.json()["code"] == "rate_unavailable"

    not_a_postcode = quote(client, live, to_postcode="EC2A4")
    assert not_a_postcode.status_code == 422
    assert not_a_postcode.json()["code"] == "validation_failed"
    assert "to_postcode" in not_a_postcode.json()["detail"]


def test_the_carrier_list_names_all_four_and_their_services(client, live):
    answer = client.get("/v1/carriers", headers=live)
    assert answer.status_code == 200
    carriers = answer.json()["data"]
    assert [row["code"] for row in carriers] == [
        "bluecoat", "kestrel", "northgate", "wendover"
    ]
    services = {row["service"] for carrier in carriers for row in carrier["services"]}
    assert "next_day" in services and "economy" in services


def test_each_plan_pays_its_own_percentage_of_the_card_on_every_line(client, live):
    def by_service(headers):
        lines = quote(client, headers).json()["quotes"]
        return {(line["carrier_code"], line["service"]): line["price_pence"] for line in lines}

    # Wistow is on standard, which pays the card; Netherby pays as it goes, which is 15% more.
    on_standard = by_service(live)
    on_payg = by_service({"Authorization": f"Bearer {OTHER_KEY}"})
    assert set(on_standard) == set(on_payg)
    for line, card in on_standard.items():
        assert on_payg[line] == parcel_price("payg", card) > card
        assert parcel_price("volume", card) < card
