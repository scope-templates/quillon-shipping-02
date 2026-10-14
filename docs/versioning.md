# Versions

The API is versioned by date. There is one current version, **2026-08-01**, and every response
says which version the deployment you are talking to speaks:

```
Quillon-Version: 2026-08-01
```

There is nothing to send and nothing to pin. Everybody is on the version in that header.

## What a new version is for

A dated version is how we make a change that would otherwise break your code:

- a field that used to be there and is not any more
- a field renamed
- a refusal where there used to be an answer
- a `code` that means something different

When one is coming we write to every technical contact on every account six months before the
date, and both versions run side by side while everyone moves. Two have gone out so far, and
neither of them caught anybody out.

Anything that cannot break code we do without a new version, and you get it the day we deploy:

- a new endpoint, with any refusal codes of its own, as `POST /signups` came with
  `email_in_use`
- a new optional field in a request
- a new field in a response, so parse leniently and ignore what you do not know
- a new value in a list we already return, such as another carrier in `GET /v1/carriers`
- better wording in `title` and `detail`

That last one is worth repeating: `code` is what to branch on, in both problem objects and
tracking events. The words next to it are for people.

## What changed

**2026-08-01**

- `GET /v1/shipments/{id}/events` and `POST /v1/shipments/{id}/cancel`.
- `Idempotency-Key` on the mutating POSTs.
- `parcel.weight` became `parcel.weight_grams`, because half the support we did in the first
  year was about kilograms.

**2025-11-01**

- Cursor paging on `GET /v1/shipments`: `{data, next_cursor}` instead of a bare array, with
  `?cursor=` and `?limit=`.
- Problem objects on every refusal, with a stable `code`.

**2025-02-17**

- The first public version: rates, shipments, labels and webhooks.

`GET /v1/carriers` arrived in December 2025, and the carrier we have taken on since turned up in
that list without a new version, which is the point of the second list above. The whole history,
with everything deployed in between, is in `CHANGELOG.md` at the root of this repository.

## Reading the version at runtime

`GET /health` needs no key and says what the host is serving:

```bash
curl https://api.quillonpost.co.uk/health
```

```json
{
  "status": "ok",
  "version": "2026-08-01",
  "build": "2.4.0",
  "shipments": 6039
}
```

`version` is the dated API version and is worth an alert if it ever says something your code was
not written against. `build` is ours and changes most weeks; it is there so support can ask
which box you reached.
