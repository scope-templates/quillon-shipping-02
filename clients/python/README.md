# quillonpost

The Python client library for the [Quillon Post](https://quillonpost.co.uk) parcel API. It wraps
the HTTP calls a shop makes at the checkout: price a parcel, book it, and get the label.

```
pip install quillonpost
```

## Using it

```python
from quillonpost import QuillonClient, QuillonError

with QuillonClient("qp_live_...") as post:
    quotes = post.quote(
        from_postcode="BS1 4DJ",
        to_postcode="EC2A 4NE",
        weight_grams=1800,
        dimensions_cm=(32, 24, 10),
    )
    cheapest = quotes[0]

    parcel = post.create_shipment(
        quote_id=cheapest["id"],
        reference="WEB-10482",
        recipient={
            "name": "Joanne Bex",
            "line1": "18 Ravensbourne Terrace",
            "city": "London",
            "postcode": "EC2A 4NE",
        },
        parcel={"weight_grams": 1800, "dimensions_cm": (32, 24, 10)},
    )

    label = post.label(parcel["id"])
    print(parcel["tracking_number"], label["url"])
```

`dimensions_cm` takes either three numbers in the order length, width, height, or the dictionary
the API itself uses.

## Methods

| Method | Call |
| --- | --- |
| `quote(from_postcode, to_postcode, weight_grams, dimensions_cm, service=None)` | `POST /v1/rates/quotes` |
| `create_shipment(recipient, parcel, quote_id=..., carrier_code=..., service=..., sender=..., reference=...)` | `POST /v1/shipments` |
| `get_shipment(shipment_id)` | `GET /v1/shipments/{id}` |
| `list_shipments(status=None, cursor=None, limit=None)` | `GET /v1/shipments` |
| `label(shipment_id)` | `POST /v1/shipments/{id}/label` |
| `carriers()` | `GET /v1/carriers` |

Anything the API refuses comes back as a `QuillonError` carrying the problem object:

```python
try:
    post.get_shipment("shp_nothing")
except QuillonError as refused:
    print(refused.code, refused.status, refused.detail)
```

## Keys and hosts

Pass a `qp_test_` key while you are building; parcels booked on one are never collected and the
label comes back marked SAMPLE. `base_url` takes another host if you have been given one, and
`session` takes an `httpx.Client` of your own if you want to set proxies or retries.

The full docs are at <https://quillonpost.co.uk/docs>.
