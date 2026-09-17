"""Labels: the link, the PDF behind it, and what a test key gets."""

from conftest import PARCEL, RECIPIENT

CREATED = "shp_wistow00000000000004"

BODY = {
    "recipient": RECIPIENT,
    "parcel": PARCEL,
    "carrier_code": "wendover",
    "service": "economy",
}


def test_a_label_is_a_link_to_a_pdf_that_prints(client, live):
    answer = client.post(f"/v1/shipments/{CREATED}/label", headers=live)
    assert answer.status_code == 200
    label = answer.json()
    assert label["format"] == "pdf"
    assert label["url"].endswith(".pdf")
    assert label["tracking_number"]

    served = client.get(label["url"].replace("http://testserver", ""))
    assert served.status_code == 200
    assert served.headers["content-type"] == "application/pdf"
    assert served.content.startswith(b"%PDF-")
    assert label["tracking_number"].encode() in served.content

    # Asking again before it runs out gives the same link back.
    again = client.post(f"/v1/shipments/{CREATED}/label", headers=live).json()
    assert again["url"] == label["url"]
    assert again["expires_at"] == label["expires_at"]


def test_a_label_on_a_test_key_is_marked_so_no_depot_takes_it(client, sandbox):
    made = client.post("/v1/shipments", headers=sandbox, json=BODY).json()
    label = client.post(f"/v1/shipments/{made['id']}/label", headers=sandbox).json()
    served = client.get(label["url"].replace("http://testserver", ""))
    assert b"SAMPLE" in served.content


def test_a_cancelled_parcel_has_no_label_and_its_old_link_stops_working(client, live):
    label = client.post(f"/v1/shipments/{CREATED}/label", headers=live).json()
    client.post(f"/v1/shipments/{CREATED}/cancel", headers=live)

    answer = client.post(f"/v1/shipments/{CREATED}/label", headers=live)
    assert answer.status_code == 409
    assert answer.json()["code"] == "label_unavailable"
    assert client.get(label["url"].replace("http://testserver", "")).status_code == 404
