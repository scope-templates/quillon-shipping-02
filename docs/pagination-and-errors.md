# Pagination, idempotency and errors

The three things that work the same way on every endpoint.

## Pagination

Lists come back newest first in an envelope:

```json
{
  "data": [{ "id": "shp_xh5b8nrjxwzr4tfr4brx92" }],
  "next_cursor": "MjAyNi0wOC0wM1QwOToxNDowMFp8c2hwX3hoNWI4bnJqeHd6cjR0ZnI0YnJ4OTI"
}
```

Pass `next_cursor` back as `?cursor=` for the page after it. When `next_cursor` is `null` you
are at the end.

```bash
curl "https://api.quillonpost.co.uk/v1/shipments?limit=50" \
  -H "Authorization: Bearer $QUILLON_KEY"

curl "https://api.quillonpost.co.uk/v1/shipments?limit=50&cursor=MjAyNi0wOC0wM1QwOToxNDowMFp8c2hwX3hoNWI4bnJqeHd6cjR0ZnI0YnJ4OTI" \
  -H "Authorization: Bearer $QUILLON_KEY"
```

The rules:

- `limit` is between 1 and 100. Leave it off and you get 25.
- A cursor is ours to make and yours to pass back. Build one yourself and you get
  `invalid_cursor`; the format is not part of the API.
- A cursor is a place in the list, not a page number. Parcels booked while you are paging
  appear at the front, where you have already been, so you will not see them and you will not
  see anything twice.
- Filters go with the cursor. Start a page with `?status=held`, and keep `status=held` on every
  page after it.

## Idempotency

`Idempotency-Key` on `POST /v1/shipments`, `POST /v1/shipments/{id}/cancel` and
`POST /v1/webhooks`. Anything up to 255 characters; your order number is a good one.

- **Same key, same body.** You get the first answer back, exactly as it was, with
  `Quillon-Idempotent-Replay: true` on it. One parcel, one label, one invoice line.
- **Same key, different body.** `409 idempotency_conflict`. Something in your code is reusing a
  key it should not.
- **No key.** Two calls are two parcels. That is not a bug in your code, it is two parcels.

Keys are kept per account, so nobody else's choice of key collides with yours, and they are kept
for a day and then dropped. A retry a day later is a new request, which is the right answer: by
then the shopper has usually given up and ordered again.

## Errors

Every refusal is a problem object, with the same five fields, served as
`application/problem+json`:

```json
{
  "type": "https://quillonpost.co.uk/docs/errors#rate_unavailable",
  "title": "No carrier will take that parcel",
  "status": 422,
  "detail": "Nothing on our rate card will take that parcel to IV23 2PL. Check the weight and the longest side, and the service if you asked for one.",
  "code": "rate_unavailable"
}
```

Branch on `code`. It is stable: a code never changes what it means. A new code on a route you
already call only arrives with a new dated version; a new route can bring codes of its own within
a version, as `POST /signups` brought `email_in_use`. `title` is the general case, `detail` is
your particular request, and both may be reworded.

Every code, with a section each, is in [errors.md](errors.md). The short version:

| Code | Status | What it means |
| --- | --- | --- |
| `missing_credentials` | 401 | No `Authorization` header. |
| `invalid_key` | 401 | The key is not one we will take. |
| `account_closed` | 401 | The key is ours; the account behind it is shut. |
| `not_found` | 404 | No such shipment, endpoint or label on this account. |
| `method_not_allowed` | 405 | Right path, wrong verb. |
| `validation_failed` | 422 | The body or a parameter will not do. The detail names the field. |
| `invalid_cursor` | 422 | That `cursor` is not one we handed out. |
| `rate_unavailable` | 422 | Nothing on the card will take that parcel to that postcode. |
| `quote_not_found` | 422 | No such quote on this account. |
| `quote_expired` | 422 | The quote is older than thirty minutes. |
| `idempotency_conflict` | 409 | That key was used on a different body. |
| `reference_in_use` | 409 | That reference is on another of your shipments. |
| `email_in_use` | 409 | On `POST /signups`: that email address already has an account. |
| `not_cancellable` | 409 | The carrier has the parcel. |
| `label_unavailable` | 409 | The shipment was cancelled. |
| `rate_limited` | 429 | Too many calls this minute. See [authentication.md](authentication.md). |
| `unexpected` | 5xx | Our fault. Retry; if it goes on, send us the time and we will look. |

`not_scannable` and `invalid_carrier_secret` belong to the carrier scan feed, and
`invalid_billing_secret` to the billing provider's feed; none of the three reaches a shop.

### What to retry

`rate_limited` and the 5xx family, with a `Idempotency-Key` on the call so a retry cannot book a
second parcel. Nothing in the 4xx family is worth retrying unchanged: the same request will be
refused the same way.
