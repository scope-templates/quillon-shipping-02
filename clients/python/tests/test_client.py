"""The client library, talking to the API in this repository rather than over the wire."""

import pytest

from conftest import LIVE_KEY, PARCEL, RECIPIENT
from quillonpost import QuillonClient, QuillonError, __version__


@pytest.fixture()
def post(client):
    """The library pointed at the app running in this process."""
    with QuillonClient(LIVE_KEY, base_url="http://testserver", session=client) as opened:
        yield opened


def test_the_package_says_which_version_it_is():
    assert __version__ == "1.3.0"


def test_a_quote_turns_into_a_parcel_and_a_label(post):
    quotes = post.quote(
        from_postcode="BS1 4DJ",
        to_postcode="EC2A 4NE",
        weight_grams=1800,
        dimensions_cm=(32, 24, 10),
    )
    assert quotes[0]["price_pence"] < quotes[-1]["price_pence"]

    parcel = post.create_shipment(
        quote_id=quotes[0]["id"],
        recipient=RECIPIENT,
        parcel=PARCEL,
        reference="WEB-40001",
    )
    assert parcel["status"] == "created"
    assert post.get_shipment(parcel["id"])["reference"] == "WEB-40001"

    label = post.label(parcel["id"])
    assert label["format"] == "pdf"
    assert label["tracking_number"] == parcel["tracking_number"]


def test_a_list_comes_back_a_page_at_a_time(post):
    page = post.list_shipments(limit=2)
    assert len(page["data"]) == 2
    following = post.list_shipments(limit=2, cursor=page["next_cursor"])
    assert not {row["id"] for row in page["data"]} & {row["id"] for row in following["data"]}
    assert post.list_shipments(status="created")["data"]


def test_a_refusal_arrives_as_an_error_with_the_code_on_it(post):
    with pytest.raises(QuillonError) as refused:
        post.get_shipment("shp_nothinglikeit")
    assert refused.value.code == "not_found"
    assert refused.value.status == 404
    assert refused.value.detail


def test_the_carriers_can_be_read_off_the_account(post):
    codes = [row["code"] for row in post.carriers()]
    assert "northgate" in codes and len(codes) == 4
