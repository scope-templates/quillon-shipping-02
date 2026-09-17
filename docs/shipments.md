# Shipments

A shipment is one parcel on one carrier. It is created, it is collected, it moves, and it
arrives. This page covers booking one, reading it back, listing them and stopping one.

## Booking

`POST /v1/shipments`

Two ways to say what it should go on:

- **From a quote.** Send `quote_id`. You are charged the price on that quote, which holds for
  thirty minutes from the moment we gave it to you. This is the one to use at a checkout, so
  that the shopper pays what they were shown.
- **Off the card.** Send `carrier_code` and `service` together. We price the parcel as the card
  stands at that moment. This is the one to use in a back office where nobody has been quoted.

The rest of the body:

| Field | Needed | What it is |
| --- | --- | --- |
| `recipient` | yes | Name, address, postcode. `phone` and `email` help the carrier and get the shopper a text. |
| `parcel` | yes | `weight_grams`, `dimensions_cm` and an optional `description` for customs and for your own eyes. |
| `sender` | no | Where it goes out from. Left out, we use the dispatch address on your account. |
| `reference` | no | Your order number. We keep it unique inside your account and mode, so you can find a parcel by it. |

```bash
curl https://api.quillonpost.co.uk/v1/shipments \
  -H "Authorization: Bearer $QUILLON_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-10482" \
  -d '{
    "carrier_code": "northgate",
    "service": "next_day",
    "reference": "WEB-10482",
    "recipient": {
      "name": "Joanne Bex",
      "line1": "18 Ravensbourne Terrace",
      "city": "London",
      "postcode": "EC2A 4NE"
    },
    "parcel": {
      "weight_grams": 1800,
      "dimensions_cm": {"length_cm": 32, "width_cm": 24, "height_cm": 10}
    }
  }'
```

You get the whole shipment back, with `status: "created"`, a `tracking_number` you can put in
the confirmation email, and the `price_pence` we will bill.

What it refuses:

- `rate_unavailable` — that carrier and service will not take that parcel to that postcode.
  Quote it first and you will see what will.
- `quote_expired`, `quote_not_found` — the quote is older than thirty minutes, or belongs to
  another account. Ask for the rates again.
- `reference_in_use` — that reference is already on one of your shipments. The detail names it.
- `validation_failed` — something in the body will not do; the detail says which field.

## Reading one back

`GET /v1/shipments/{id}` gives the same object, up to date. The fields that move are `status`,
`collected_at`, `delivered_at` and `cancelled_at`; everything else is as you sent it.

A shipment belongs to the account that booked it and to the mode it was booked in. Another
account asking for it gets `not_found`, not `403`, because it is not theirs to know about, and
so does a live key asking for a parcel booked on the test key beside it.

## Listing them

`GET /v1/shipments` is newest first, twenty-five to a page.

| Parameter | What it does |
| --- | --- |
| `status` | One of the statuses below. |
| `cursor` | The `next_cursor` from the last page. |
| `limit` | 1 to 100. The default is 25. |

```bash
curl "https://api.quillonpost.co.uk/v1/shipments?status=held&limit=50" \
  -H "Authorization: Bearer $QUILLON_KEY"
```

Cursor rules are in [pagination-and-errors.md](pagination-and-errors.md).

## Statuses

| Status | What has happened |
| --- | --- |
| `created` | Booked. The label exists; nobody has picked it up. |
| `collected` | A driver has it. |
| `in_transit` | It is moving between depots. |
| `out_for_delivery` | It is on a van this morning. |
| `delivered` | It is there. `delivered_at` is set. |
| `held` | Something has stopped it: nobody in, the address is queried, or it is sitting in a depot. |
| `returned` | It has come back to you. |
| `cancelled` | You stopped it before collection. |

## Stopping one

`POST /v1/shipments/{id}/cancel`

Only while the parcel is `created`. Once a driver has it, it belongs to the carrier and the
answer is `409 not_cancellable` with a detail that tells the shopper something useful:

```json
{
  "type": "https://quillonpost.co.uk/docs/errors#not_cancellable",
  "title": "The parcel has gone too far to cancel",
  "status": 409,
  "detail": "This parcel is in transit and the carrier has it. Ask the recipient to refuse the delivery, and it will come back to you.",
  "code": "not_cancellable"
}
```

A cancelled shipment gets a `cancelled` scan, drops its label link, and is not invoiced. Send
`Idempotency-Key` and a retried cancel gives the same answer instead of a refusal.

## Labels

`POST /v1/shipments/{id}/label` gives a link to a PDF and the time it runs out, a day later.
Ask again for a fresh one. There is no label on a cancelled shipment: that is
`409 label_unavailable`.

The PDF is 420 by 595 points, which prints on a thermal label printer as it stands and on A4
with the printer set to fit. The link carries no key, so hand it to whatever prints for you.
