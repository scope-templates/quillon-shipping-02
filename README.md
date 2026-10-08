# Quillon Post

We are a parcel company in Bristol that sells an API instead of a website. A shop's checkout
asks us what a parcel will cost, books it, downloads the label and follows it to the door, and
behind that we put it on whichever of our four carriers suits the size, the postcode and the
day; the shop never has to know which. Tomasz and I started it in 2024 because we had both spent
too long writing the same carrier integration twice, Ada looks after the shops and Callum writes
the docs and the Python client. A hundred and forty shops are wired up to us and about sixty of
them sent something last month; six thousand parcels went through us in the year to September, a
third of them from one shop. With the quoting and the tracking on top of that it comes to a few
hundred calls a day, which is small enough that the four of us can run the whole thing.

## What is in it

`app/` is the service. Four resources, and what each one will not do:

- **Rates.** `POST /v1/rates/quotes` prices one parcel against every carrier that will take it,
  cheapest first, and holds each quote for half an hour. It works out the zone from the
  destination postcode and the chargeable weight from the box, so a big light parcel is priced
  the way it will be invoiced. If nothing on the card will carry it — over thirty kilos by
  weight or by size, longer than 120 cm on a side, or a service that does not go where you are
  sending it — that is a refusal with `rate_unavailable` rather than a guess.
- **Shipments.** `POST /v1/shipments` books the parcel, from a quote id or from a carrier and
  service named outright, and gives back an id, a tracking number and the price we will bill.
  `GET /v1/shipments/{id}` reads one back and `GET /v1/shipments` pages through them newest
  first. It refuses a `reference` that is already on one of the account's parcels, a quote older
  than half an hour, and anything belonging to another account, which it treats as not being
  there at all. `POST /v1/shipments/{id}/label` gives a link to a PDF that prints, good for a
  day; there is none for a cancelled parcel. `POST /v1/shipments/{id}/cancel` stops a parcel
  while it is still `created` and refuses once a driver has it. `GET /v1/shipments/{id}/events`
  is the carrier's scans, oldest first.
- **Webhooks.** `POST /v1/webhooks` registers an https URL and hands back the signing secret
  once. Deliveries are signed, queued, and retried on a ladder that gives up after nine
  attempts; `scripts/deliver_webhooks.py` is what works through the queue. `DELETE` stops an
  endpoint and empties what was still waiting for it.
- **Carriers.** `GET /v1/carriers` is the four carriers and their services, so nobody has to
  hard-code them.

The carriers come in the other way. `POST /carriers/{code}/scans` is the feed they post to, one
scan at a time, on a shared secret out of the environment (`CARRIER_SECRET_NORTHGATE` and the
rest). A scan appends a tracking event, moves the parcel on unless it would move it backwards,
and queues `tracking.updated` for anybody listening. It is not on `/v1` and no shop sees it.

Every call carries a key, `qp_test_` or `qp_live_`, and only ever sees its own account and its
own mode: a live key asking for a parcel booked on the test key beside it gets `not_found`.
Every response carries `Quillon-Version`, and every `/v1` response what is left of the rate
limit. Every refusal is a problem object `{type, title, status, detail, code}` and the `code` is
the part to branch on.

The pieces underneath: `app/rates.py` is the zones, the bands and the card; `app/tracking.py` is
the scan codes and what may still be stopped; `app/idempotency.py`, `app/pagination.py`,
`app/auth.py`, `app/throttle.py` and `app/errors.py` are the things every endpoint shares;
`app/labels.py` builds the PDF; `app/webhooks.py` signs and queues; `app/db.py` and
`app/seed.py` open the store and fill it.

## Running locally

```
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

It keeps everything in one sqlite file at `data/quillon.sqlite`, made on the first run;
`DATABASE_PATH` puts it somewhere else. The first start on an empty file loads the bundled
history, so there is a year of parcels and a hundred and forty shops to look at straight away —
pick a key out of `api_keys` and you are away.

`PUBLIC_BASE_URL` sets the host we put in label links, for when this is behind something, and
`CARRIER_SECRET_<CODE>` is what a carrier has to send to post a scan. Without one set, that
carrier's feed is closed.

`python scripts/deliver_webhooks.py --loop` is the other half of a running service: it works
through the delivery queue a minute at a time.

The interactive reference is at <http://127.0.0.1:8000/docs> and `GET /health` needs no key.

## Tests

```
python -m pytest
```

The suite runs against a database of its own with a small world in it: three shops, their keys
and half a dozen parcels, built in `conftest.py`. The carriers and the rate card come from
`app/rates.py`, so a price in a test is a price we would really charge. Two of them are slower
than the rest: one builds the whole bundled history and compares it with the committed file, and
one loads that file into an empty database.

One is marked as an expected failure. It shows one of the known issues at the top of
`CHANGELOG.md`, carries that ticket's key in its reason, and is strict, so the fix that makes it
pass has to take the marker off. How we work, ticket keys and all, is in `CONTRIBUTING.md`.

## The data

`data/seed.json` is the year to the first of September 2026: 140 shops, 218 keys, 6,039 parcels,
and the ninety days of scans still in retention, with the webhook endpoints and deliveries that
go with them. November and January are the busy months and one shop is a third of the volume.

It is built by `python scripts/build_seed.py`, which runs off a fixed seed and writes the same
bytes every time; `--check` tells you whether the file still matches the script. The service
loads it the first time it opens an empty database.

## Docs and clients

Public docs are in `docs/`. The spec is `openapi/quillon-post.json`, exported by
`scripts/export_openapi.py`. The Python client library is `clients/python`, version 1.3.0,
published to PyPI as `quillonpost`.
