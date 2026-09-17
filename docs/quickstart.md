# Quickstart

Three calls get a parcel out of your door: price it, book it, print the label. Everything below
works against a `qp_test_` key, so you can run all of it before you go live.

The base URL is `https://api.quillonpost.co.uk`. Every call needs your key on the
`Authorization` header.

## 1. Price the parcel

```bash
curl https://api.quillonpost.co.uk/v1/rates/quotes \
  -H "Authorization: Bearer $QUILLON_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "from_postcode": "BS1 4DJ",
    "to_postcode": "EC2A 4NE",
    "weight_grams": 1800,
    "dimensions_cm": {"length_cm": 32, "width_cm": 24, "height_cm": 10}
  }'
```

Seven carrier and service combinations will take that parcel to EC2A. Abridged to the first
three and the last:

```json
{
  "quotes": [
    {
      "id": "qt_y3xxbxp6fmjtf34fpjprnt",
      "carrier_code": "wendover",
      "carrier_name": "Wendover",
      "service": "economy",
      "price_pence": 420,
      "estimated_days": 3,
      "expires_at": "2026-08-14T10:34:07Z"
    },
    {
      "id": "qt_ghv86qdm8rkqjnggptz49g",
      "carrier_code": "northgate",
      "carrier_name": "Northgate Express",
      "service": "standard",
      "price_pence": 540,
      "estimated_days": 2,
      "expires_at": "2026-08-14T10:34:07Z"
    },
    {
      "id": "qt_djvnp2f7cqx343q32r44c5",
      "carrier_code": "kestrel",
      "carrier_name": "Kestrel Parcels",
      "service": "standard",
      "price_pence": 585,
      "estimated_days": 2,
      "expires_at": "2026-08-14T10:34:07Z"
    },
    {
      "id": "qt_gsrpjqyq92fk3ftghsk7f8",
      "carrier_code": "bluecoat",
      "carrier_name": "Bluecoat Couriers",
      "service": "before_noon",
      "price_pence": 1280,
      "estimated_days": 1,
      "expires_at": "2026-08-14T10:34:07Z"
    }
  ],
  "zone": "london",
  "chargeable_weight_grams": 1800
}
```

Cheapest first. Show the shopper whichever you like; each quote holds for thirty minutes.

## 2. Book it

Send the quote id back and we take the price that was quoted, whatever the card says by then.

```bash
curl https://api.quillonpost.co.uk/v1/shipments \
  -H "Authorization: Bearer $QUILLON_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: order-10482" \
  -d '{
    "quote_id": "qt_y3xxbxp6fmjtf34fpjprnt",
    "reference": "WEB-10482",
    "recipient": {
      "name": "Joanne Bex",
      "line1": "18 Ravensbourne Terrace",
      "city": "London",
      "postcode": "EC2A 4NE",
      "phone": "07700 900412"
    },
    "parcel": {
      "weight_grams": 1800,
      "dimensions_cm": {"length_cm": 32, "width_cm": 24, "height_cm": 10},
      "description": "Two glazed bowls"
    }
  }'
```

```json
{
  "id": "shp_wyzn2k6jvbvztw6mrmnfnx",
  "mode": "test",
  "status": "created",
  "carrier_code": "wendover",
  "service": "economy",
  "tracking_number": "WDV6826213650",
  "price_pence": 420,
  "reference": "WEB-10482",
  "quote_id": "qt_y3xxbxp6fmjtf34fpjprnt",
  "created_at": "2026-08-14T10:04:11Z",
  "collected_at": null,
  "delivered_at": null,
  "cancelled_at": null
}
```

Abridged: `sender`, `recipient` and `parcel` come back on the shipment as well, every field of
an address present and the ones you left out set to `null`.

The sender is the dispatch address on your account. Send a `sender` object if this parcel goes
out from somewhere else.

`Idempotency-Key` is worth the trouble: a checkout that retries sends the same key and gets the
same parcel back instead of booking a second one. See
[pagination-and-errors.md](pagination-and-errors.md).

## 3. Print the label

```bash
curl -X POST \
  https://api.quillonpost.co.uk/v1/shipments/shp_wyzn2k6jvbvztw6mrmnfnx/label \
  -H "Authorization: Bearer $QUILLON_KEY"
```

```json
{
  "url": "https://api.quillonpost.co.uk/labels/lbl_mxt4g3gm6fnx2q5w3xr8w7.pdf",
  "format": "pdf",
  "expires_at": "2026-08-15T10:06:52Z",
  "tracking_number": "WDV6826213650"
}
```

The link needs no key, so you can hand it straight to a printer, and it works for a day. Ask
again after that and you get a fresh one. On a test key the page comes back with SAMPLE across
it; no depot will take one.

## Then what

- Follow the parcel: [tracking-and-webhooks.md](tracking-and-webhooks.md).
- Stop one before it is collected: [shipments.md](shipments.md).
- What a refusal looks like: [errors.md](errors.md).
- The interactive reference is at `/docs` on the API host, and the spec is
  `openapi/quillon-post.json` in the repository.
