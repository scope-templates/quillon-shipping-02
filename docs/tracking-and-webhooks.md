# Tracking and webhooks

There are two ways to know where a parcel is: ask us, or be told. Ask for one parcel when a
shopper is looking at a page; be told about all of them if you keep your own order status.

## Asking

`GET /v1/shipments/{id}/events` gives every scan we have had from the carrier, oldest first,
with the status the parcel is in now.

```bash
curl https://api.quillonpost.co.uk/v1/shipments/shp_xh5b8nrjxwzr4tfr4brx92/events \
  -H "Authorization: Bearer $QUILLON_KEY"
```

```json
{
  "data": [
    {
      "code": "label_created",
      "description": "Label created",
      "location": "Bristol",
      "occurred_at": "2026-08-03T09:14:00Z"
    },
    {
      "code": "collected",
      "description": "Collected from sender",
      "location": "Bristol",
      "occurred_at": "2026-08-03T17:02:00Z"
    },
    {
      "code": "in_transit",
      "description": "In transit",
      "location": "Tanbury",
      "occurred_at": "2026-08-04T04:35:00Z"
    },
    {
      "code": "out_for_delivery",
      "description": "Out for delivery",
      "location": "London",
      "occurred_at": "2026-08-05T07:11:00Z"
    },
    {
      "code": "delivered",
      "description": "Delivered",
      "location": "London",
      "occurred_at": "2026-08-05T11:20:00Z"
    }
  ],
  "status": "delivered"
}
```

Branch on `code`. The `description` is written for a shopper; the codes are what stay put.

| Code | Status it moves the parcel to |
| --- | --- |
| `label_created` | `created` |
| `collected` | `collected` |
| `at_origin_depot` | `in_transit` |
| `in_transit` | `in_transit` |
| `at_delivery_depot` | `in_transit` |
| `out_for_delivery` | `out_for_delivery` |
| `delivery_attempted` | `held` |
| `held_at_depot` | `held` |
| `address_query` | `held` |
| `delivered` | `delivered` |
| `returned_to_sender` | `returned` |
| `cancelled` | `cancelled` |

The four carriers scan different things. All of them tell us about the collection, a leg in
transit and the delivery; Northgate add a scan into their origin depot, and Northgate and
Kestrel one when the parcel reaches the delivery depot. Scans arrive out of order often enough
to plan for, and one that would wind a parcel backwards is kept but leaves the status where it
is. We keep scans for ninety days, which is how long the carriers answer for a parcel;
`collected_at` and `delivered_at` stay on the shipment for good.

## Being told

Register a URL and we post to it when something happens.

```bash
curl https://api.quillonpost.co.uk/v1/webhooks \
  -H "Authorization: Bearer $QUILLON_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://yourshop.co.uk/hooks/quillon",
    "events": ["shipment.delivered", "tracking.updated"]
  }'
```

```json
{
  "id": "whe_znbpbxymhy6z24xdh6cznb",
  "url": "https://yourshop.co.uk/hooks/quillon",
  "events": ["shipment.delivered", "tracking.updated"],
  "status": "active",
  "created_at": "2026-08-14T10:41:00Z",
  "secret": "whsec_pydb77x2kpxygnsmjkrbfptv9jhj9wtm"
}
```

**The secret is shown once, here.** Store it; `GET /v1/webhooks` lists your endpoints without
it. `DELETE /v1/webhooks/{id}` stops an endpoint and empties whatever was still queued for it.

The URL has to be `https`. Ten endpoints per account.

The events we send:

| Event | When |
| --- | --- |
| `shipment.created` | A parcel is booked. |
| `shipment.cancelled` | A parcel is stopped before collection. |
| `shipment.delivered` | A parcel arrives. |
| `tracking.updated` | Any scan from a carrier, including the one that delivers it. |

The body carries the parcel in short: the id to look it up by, where it has got to, and your own
reference. The addresses are not in it, so an endpoint that leaks is a smaller problem than it
might be.

```json
{
  "id": "whev_hjgktwzmmpdbnyzpmptfk9",
  "type": "shipment.delivered",
  "created_at": "2026-08-05T11:20:04Z",
  "data": {
    "id": "shp_xh5b8nrjxwzr4tfr4brx92",
    "status": "delivered",
    "carrier_code": "wendover",
    "service": "economy",
    "tracking_number": "WDV4471029358",
    "reference": "WEB-10482"
  }
}
```

Answer with any 2xx. Anything else, or a connection we cannot open, and we try again: after 30
seconds, 2 minutes, 10 minutes, 30 minutes, 2 hours, 6 hours, 12 hours and a day. Nine attempts
in all, spread over about two days, and then we stop trying that one. Answer quickly and do your
work afterwards; we wait ten seconds.

## Checking the signature

Every delivery carries a signature over the exact bytes we posted:

```
Quillon-Signature: t=1785928804,v1=6f0c1e1b0b0bb61e0dc63f0f9b6b0a7c9b1f2a4e7d8c0b5a3e2d1c0b9a8f7e6d
```

`t` is unix seconds. `v1` is HMAC-SHA256 over `t`, a full stop, and the request body, keyed with
the endpoint secret. Verify against the raw body, before any JSON parsing: re-encoding changes
the bytes and the signature will not match.

```python
import hashlib
import hmac
import time


def verify(secret: str, body: bytes, header: str, tolerance: int = 300) -> bool:
    parts = dict(piece.split("=", 1) for piece in header.split(","))
    when = int(parts["t"])
    if abs(time.time() - when) > tolerance:
        return False
    expected = hmac.new(
        secret.encode(), f"{when}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

In Flask that is `request.get_data()`; in Django, `request.body`; in Express, the raw body
before `express.json()` has had it.

Refuse anything older than five minutes, and treat a delivery you have seen before as a repeat:
the `id` on the body is stable across retries, so keeping the last few thousand is enough.

## For the carriers: posting a scan

This section is for the four carriers, not for shops. Scans come in on

```
POST /carriers/{carrier_code}/scans
Authorization: Bearer <the secret we issued you>
Content-Type: application/json
```

one scan to a request, matched to the parcel by tracking number. This is the scan that put the
parcel above on a van, four hours before it was delivered:

```json
{
  "tracking_number": "WDV4471029358",
  "code": "out_for_delivery",
  "occurred_at": "2026-08-05T07:11:00Z",
  "location": "London"
}
```

```json
{
  "shipment_id": "shp_xh5b8nrjxwzr4tfr4brx92",
  "status": "out_for_delivery",
  "recorded": true
}
```

`code` is from the table above; `location` and `description` are optional, and without a
description we use our own wording. Posting the same code and `occurred_at` twice records it
once and answers `"recorded": false`, so a feed that replays a batch is safe. A parcel that is
delivered, returned or cancelled answers `409 not_scannable`. Anything else is a problem object
like the rest of the API, and the secret is per carrier: ours refuse each other's.
