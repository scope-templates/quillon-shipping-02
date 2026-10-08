# Error codes

Every refusal is a problem object served as `application/problem+json`:

```json
{
  "type": "https://quillonpost.co.uk/docs/errors#rate_unavailable",
  "title": "No carrier will take that parcel",
  "status": 422,
  "detail": "Nothing on our rate card will take that parcel to IV23 2PL. Check the weight and the longest side, and the service if you asked for one.",
  "code": "rate_unavailable"
}
```

`code` is the part to branch on: it never changes meaning, and the `type` points at the section
below. `title` is the general case and `detail` is your particular request; both may be
reworded. See [pagination-and-errors.md](pagination-and-errors.md) for what is worth retrying.

## `missing_credentials`

**401.** No `Authorization` header on the request. Send `Authorization: Bearer qp_live_...`.

## `invalid_key`

**401.** There was a key and we could not place it: rolled, mistyped, or a webhook secret pasted
in by mistake. Secrets start with `whsec_` and never go on this header.

## `account_closed`

**401.** The key is one of ours but the account behind it is closed, so nothing on it works.
Write to support@quillonpost.co.uk if that is a surprise.

## `invalid_carrier_secret`

**401.** On the carrier scan feed only: the secret on the request is not the one we issued for
that carrier. Shops never see this.

## `not_found`

**404.** No shipment, endpoint or label link of that name on this account. A parcel booked on a
test key is not there for a live key, and another account's parcel is not there at all.

## `method_not_allowed`

**405.** Right path, wrong verb. `POST /v1/shipments/{id}` instead of `GET`, most often.

## `validation_failed`

**422.** Something in the body or the query will not do, and the `detail` names the field: a
postcode that is not a postcode, a `limit` outside 1 to 100, a status we do not have, a carrier
and service sent without each other, a webhook URL that is not https.

## `invalid_cursor`

**422.** The `cursor` is not one we handed out. Pass back `next_cursor` exactly as it came, or
leave it off for the first page.

## `rate_unavailable`

**422.** Nothing on the rate card will carry that parcel to that postcode: over 30 kg, longer
than 120 cm on a side, or a service that does not go there or does not take that weight. The
weight is the chargeable weight, the greater of what the parcel weighs and what its size comes
to, which is length by width by height in centimetres divided by 5,000, in kilos. A box 80 by 60
by 50 cm counts as 48 kg however little is in it, and is refused. Quote it without naming a
service and you will see what will take it.

## `quote_not_found`

**422.** No quote of that id on this account, in this mode.

## `quote_expired`

**422.** The quote is older than thirty minutes. Ask for the rates again; the price may have
moved.

## `idempotency_conflict`

**409.** That `Idempotency-Key` was used on a different body. The `detail` says which call it
was used on and when. Use a fresh key for a different request.

## `reference_in_use`

**409.** That `reference` is already on one of your shipments; the `detail` names it. References
are unique per account and per mode, so a test parcel and a live parcel can share one.

## `not_cancellable`

**409.** The parcel is past `created` and the carrier has it. The `detail` is written to be
passed on to the shopper.

## `not_scannable`

**409.** On the carrier scan feed only: the parcel is delivered, returned or cancelled and takes
no more scans.

## `label_unavailable`

**409.** The shipment was cancelled, so there is no label to print and the old link has stopped.

## `rate_limited`

**429.** More than the minute's allowance on this key. Back off until the time in
`X-RateLimit-Reset`. See [authentication.md](authentication.md).

## `unexpected`

**5xx.** Our fault. Retry with an `Idempotency-Key` so the retry cannot book a second parcel; if
it goes on, send us the time and we will look.
