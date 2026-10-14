"""Signing up from the website: a trialling shop and one test key, with no key needed to ask."""

from datetime import timedelta

from app import billing, throttle
from app.ids import now, read_stamp
from app.plans import TRIAL_DAYS

FORM = {
    "shop_name": "Saltmarsh Woollens",
    "contact_email": "Hello@SaltmarshWoollens.co.uk",
    "platform": "marketside",
    "city": "Saltmarsh",
}


def test_a_signup_gets_a_trial_and_one_test_key_shown_once(client, conn):
    answer = client.post("/signups", json=FORM)
    assert answer.status_code == 201
    body = answer.json()

    customer = body["customer"]
    assert customer["id"].startswith("cus_")
    assert customer["name"] == "Saltmarsh Woollens"
    assert customer["contact_email"] == "hello@saltmarshwoollens.co.uk"
    assert customer["status"] == "trialling"

    trial = body["subscription"]
    assert trial["plan"] == "payg"
    assert trial["status"] == "trialling"
    assert trial["monthly_fee_pence"] == 0
    assert trial["current_period_start"] is None
    assert trial["current_period_end"] is None
    lasts = read_stamp(trial["trial_ends_at"]) - read_stamp(customer["created_at"])
    assert lasts == timedelta(days=TRIAL_DAYS) == timedelta(days=30)

    assert body["key"].startswith("qp_test_")
    keys = conn.execute(
        "SELECT mode, label FROM api_keys WHERE customer_id = ?", (customer["id"],)
    ).fetchall()
    assert [(row["mode"], row["label"]) for row in keys] == [("test", "Integration")]


def test_the_key_from_a_signup_works_at_once_on_its_own_allowance(client):
    key = client.post("/signups", json=FORM).json()["key"]
    sandbox = {"Authorization": f"Bearer {key}"}

    throttle.clear()
    carriers = client.get("/v1/carriers", headers=sandbox)
    assert carriers.status_code == 200
    assert carriers.headers["X-RateLimit-Limit"] == str(throttle.LIMITS["test"])

    booked = client.post(
        "/v1/shipments",
        headers=sandbox,
        json={
            "sender": {"name": "Saltmarsh Woollens", "line1": "Bay 3, Quarry Yard",
                       "city": "Saltmarsh", "postcode": "ST4 2JQ"},
            "recipient": {"name": "Isla Dunbar", "line1": "9 Orchard Rise", "city": "Wybourne",
                          "postcode": "LS6 1PN"},
            "parcel": {"weight_grams": 600,
                       "dimensions_cm": {"length_cm": 24, "width_cm": 18, "height_cm": 8}},
            "carrier_code": "wendover",
            "service": "economy",
        },
    )
    assert booked.status_code == 201
    assert booked.json()["mode"] == "test"


def test_a_trial_past_its_end_date_still_lets_the_shop_in(client, conn):
    """A trial stays open until the billing provider starts a plan or cancels it."""
    made = client.post("/signups", json=FORM).json()
    customer_id = made["customer"]["id"]
    billing.save(conn, billing.trial(customer_id, now() - timedelta(days=45)))

    sandbox = {"Authorization": f"Bearer {made['key']}"}
    assert client.get("/v1/carriers", headers=sandbox).status_code == 200
    status = conn.execute(
        "SELECT status FROM subscriptions WHERE customer_id = ?", (customer_id,)
    ).fetchone()[0]
    assert status == "trialling"


def test_an_email_that_already_has_an_account_is_refused(client, conn):
    assert client.post("/signups", json=FORM).status_code == 201
    again = client.post("/signups", json={**FORM, "contact_email": "hello@saltmarshwoollens.co.uk"})
    assert again.status_code == 409
    assert again.json()["code"] == "email_in_use"
    assert "hello@saltmarshwoollens.co.uk" in again.json()["detail"]

    # A shop we set up by hand counts too.
    existing = client.post(
        "/signups", json={**FORM, "contact_email": "orders@wistowprovisions.co.uk"}
    )
    assert existing.status_code == 409

    count = conn.execute(
        "SELECT COUNT(*) FROM customers WHERE contact_email = 'hello@saltmarshwoollens.co.uk'"
    ).fetchone()[0]
    assert count == 1


def test_a_form_that_will_not_do_is_refused(client):
    not_an_email = client.post("/signups", json={**FORM, "contact_email": "saltmarsh"})
    assert not_an_email.status_code == 422
    assert not_an_email.json()["code"] == "validation_failed"
    assert "contact_email" in not_an_email.json()["detail"]

    no_name = client.post("/signups", json={**FORM, "shop_name": ""})
    assert no_name.status_code == 422

    blank_name = client.post("/signups", json={**FORM, "shop_name": "   "})
    assert blank_name.status_code == 422
    assert "shop_name" in blank_name.json()["detail"]

    blank_platform = client.post("/signups", json={**FORM, "platform": " 	 "})
    assert blank_platform.status_code == 422
    assert "platform" in blank_platform.json()["detail"]


def test_an_address_is_the_same_address_whatever_its_letters(client):
    first = client.post(
        "/signups", json={**FORM, "contact_email": "straße@saltmarshwoollens.co.uk"}
    )
    assert first.status_code == 201
    assert first.json()["customer"]["contact_email"] == "straße@saltmarshwoollens.co.uk"

    again = client.post(
        "/signups", json={**FORM, "contact_email": "STRASSE@saltmarshwoollens.co.uk"}
    )
    assert again.status_code == 409
    assert again.json()["code"] == "email_in_use"
