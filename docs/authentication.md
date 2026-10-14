# Authentication

Every call except `GET /health`, the label links, `POST /signups` and the two feeds that come
in from outside, the carriers' scans and the billing provider's events, which each use a secret
of their own, needs a key:

```
Authorization: Bearer qp_live_8zkdbmhybs5zpfwzwz5kzqvt
```

Keys are issued per account, not per person. A signup on the website comes with one test key;
Ada sets up the live ones when you sign, and you can write to support@quillonpost.co.uk if you
want another.

## Test and live

A key says which world it is in:

| Prefix | What it does |
| --- | --- |
| `qp_test_` | Books parcels that no van ever collects. Labels come back marked SAMPLE. Nothing is invoiced. |
| `qp_live_` | Books real parcels with a real carrier, and appears on your invoice. |

The two worlds do not mix, on every endpoint. A shipment booked on a test key cannot be read,
listed, labelled or cancelled with a live key: the id comes back `not_found`. Quotes work the
same way, and a `reference` is unique within a mode, so the same order number can sit on a test
parcel and a live one. A test parcel gets its `label_created` scan and then stays in `created`,
because nobody is going to collect it; cancel it when you have finished with it.

Rates, carriers and the problem objects are identical either way, so the only thing to change on
the day you go live is the key.

## Where to keep it

The key is the whole of the credential; there is no second half. Keep it on the server, out of
the browser and out of your repository. Ask us to roll one and we issue the new key first, so
you can swap it over before the old one stops.

If a key stops working you get a problem object rather than a bare 401 body:

```json
{
  "type": "https://quillonpost.co.uk/docs/errors#invalid_key",
  "title": "That API key is not one of ours",
  "status": 401,
  "detail": "We do not recognise that key. It may have been rolled from the back office.",
  "code": "invalid_key"
}
```

Three codes come back on 401. `missing_credentials` means there was no `Authorization` header at
all. `invalid_key` means there was one and we could not place it: rolled, mistyped, or the
webhook secret pasted in by mistake — secrets start with `whsec_` and are never sent on this
header. `account_closed` means the key is one of ours but the account behind it is shut, and no
key on it will work until somebody here opens it again.

## More than one shop

If you run several shops out of one account, use one key each and set a `reference` on every
shipment so your own order numbers come back with it. If the shops should not see each other's
parcels, tell us and we will set up separate accounts; a key only ever sees its own account.

## How many calls

Rate limits are counted per key, in windows of a minute:

| Key | Requests a minute |
| --- | --- |
| `qp_live_` | 600 |
| `qp_test_` | 120 |

A `/v1` call with no key at all, or a key we cannot place, is counted against the address it
came from and allowed 60 a minute.

Every `/v1` response carries the count, including the refusals. `GET /health` and the label
links are not counted and do not carry the headers.

```
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 573
X-RateLimit-Reset: 1788080460
```

Over the line you get `429` with code `rate_limited`. Back off until the time in
`X-RateLimit-Reset`, which is in unix seconds. If you need more than 600, write to us: it is
usually cheaper for both of us to look at what you are polling.
