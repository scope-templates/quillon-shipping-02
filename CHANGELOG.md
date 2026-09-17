# Changelog

What we have deployed, newest first. Dated headings in bold are API versions: one is current at
a time, a new one is announced to every technical contact six months before the date, and both
run side by side while everyone moves. Everything else here went out to everybody on the day it
was deployed.

## **2026-08-01** — API version

- `GET /v1/shipments/{id}/events`: the carrier's scans, oldest first, with the status the parcel
  is in now. Twelve codes, listed in `docs/tracking-and-webhooks.md`.
- `POST /v1/shipments/{id}/cancel`: stops a parcel while it is still `created`. After that it is
  `409 not_cancellable`, and the detail says what to tell the shopper.
- `Idempotency-Key` on `POST /v1/shipments`, `POST /v1/shipments/{id}/cancel` and
  `POST /v1/webhooks`. Same key and same body gives the first answer back with
  `Quillon-Idempotent-Replay: true`; same key and a different body is `409 idempotency_conflict`.
- `parcel.weight` is now `parcel.weight_grams`. The old name was grams too; the new one says so.
- New statuses `held` and `returned`, which used to both come back as `in_transit`.

## 2026-07-22

- Bluecoat Couriers added, with `next_day` and `before_noon` inside the M25.
- Volumetric weight on the quote: `chargeable_weight_grams` in the answer, so a big light box
  is priced the way it will be invoiced.

## 2026-06-09

- `reference` is unique inside an account and mode, and a repeat is `409 reference_in_use`
  rather than a second parcel with the same order number on it. Parcels booked before today can
  still share one, which is why the index on it is not a unique one.
- Rate limits raised to 600 a minute on a live key.

## 2026-04-02

- The dispatch address on the account stands in when a shipment is booked without a `sender`.
- Label links last a day rather than an hour.

## 2026-02-18

- Webhook deliveries are retried on a longer ladder: nine attempts over about two days, and the
  last error is kept against the delivery so support can see what the endpoint said.

## 2025-12-08

- `GET /v1/carriers` returns the carriers on the account and the services each one sells.
- `401` on a key belonging to a closed account is `account_closed` rather than `invalid_key`,
  after a fortnight of support answering the same question.

## **2025-11-01** — API version

- `GET /v1/shipments` pages with `?cursor=` and `?limit=` and answers `{data, next_cursor}`.
  It used to answer with a bare array of everything.
- Every refusal is a problem object `{type, title, status, detail, code}` served as
  `application/problem+json`. Before this the bodies were `{"error": "..."}` and the wording was
  the only thing to go on.
- `Quillon-Version` on every response.

## 2025-09-15

- Rate-limit headers `X-RateLimit-Limit`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`.

## 2025-06-30

- Webhook signatures: `Quillon-Signature: t=<unix>,v1=<hmac_sha256>`, keyed with the endpoint
  secret. Endpoints created before this were rolled by hand and the secrets sent to each shop.
- Deliveries carry the parcel in short rather than the whole shipment, so an endpoint that leaks
  does not leak an address book.

## **2025-02-17** — API version

- The first public version: `POST /v1/rates/quotes`, `POST /v1/shipments`,
  `GET /v1/shipments/{id}`, `GET /v1/shipments`, `POST /v1/shipments/{id}/label`,
  `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{id}` and `GET /health`.
- `POST /carriers/{code}/scans`, which is where the carriers put their scans. Off `/v1`, on a
  secret per carrier, and no shop has ever needed to know it is there.
