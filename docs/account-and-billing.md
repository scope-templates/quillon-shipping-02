# Account and billing

Your key can tell you about the account it belongs to: the plan, where the subscription stands,
and how the month is going. The rest of this page is how a shop comes to have an account, and,
for the billing provider, how it tells us what has happened to one.

## Your account

`GET /v1/account` is the account behind the key, and only that account.

```bash
curl https://api.quillonpost.co.uk/v1/account \
  -H "Authorization: Bearer $QUILLON_KEY"
```

```json
{
  "id": "cus_wq7tbkx4mdz2hy9vcnrfgp",
  "name": "Wistow Provisions",
  "platform": "cartwell",
  "mode": "live",
  "plan": "standard",
  "status": "active",
  "current_period_start": "2026-08-04T10:00:00Z",
  "current_period_end": "2026-09-04T10:00:00Z",
  "trial_ends_at": null,
  "this_month": {
    "month": "2026-08",
    "parcels": 41,
    "spend_pence": 18235,
    "last_booked_at": "2026-08-29T09:05:00Z"
  }
}
```

`this_month` is the calendar month in UTC, counted on the mode of the key. On a live key it is
your live parcels and what they cost at your plan's prices, before the monthly fee; on a test key
it is your test parcels, which are never invoiced. A parcel cancelled before collection is in
none of the three numbers.

| Status | What it means |
| --- | --- |
| `trialling` | Signed up from the website, on pay as you go, with test keys. `trial_ends_at` is thirty days on from the signup; nothing stops at that date, and the trial ends when a plan starts. The date stays on the account after that, as the day the trial was due to end. |
| `active` | On a plan and paid up. |
| `past_due` | The last invoice was not paid. Everything keeps working while the card is tried again; write to us if it is the card that needs changing. |
| `cancelled` | The account is closed, and every key on it answers `401 account_closed`. |

## Plans

| Plan | A month | Off the card on every parcel |
| --- | --- | --- |
| `payg` | nothing | nothing |
| `standard` | £12 | 5% |
| `volume` | £45 | 12% |

The rate card is the list price and it is the same for every shop. The plan takes its share off
each line when a parcel is quoted or booked, rounded to the nearest 5p as the card is, so
`price_pence` on a quote and on a shipment is already your price. An invoice is the month's fee
and the live parcels booked since the last invoice. To move plan, write to
support@quillonpost.co.uk.

Pay as you go has no period: `current_period_start` and `current_period_end` are null on it, and
its invoice, which is the parcels alone, changes nothing but the status. A plan with a fee runs a
month at a time from the start, or from the invoice that paid for the month.

## Signing up

The form on the website posts to `POST /signups`, which needs no key.

```bash
curl https://api.quillonpost.co.uk/signups \
  -H "Content-Type: application/json" \
  -d '{
    "shop_name": "Saltmarsh Woollens",
    "contact_email": "hello@saltmarshwoollens.co.uk",
    "platform": "marketside",
    "city": "Saltmarsh"
  }'
```

```json
{
  "customer": {
    "id": "cus_k3ntv8xhq2mzdbr7wpcg4f",
    "name": "Saltmarsh Woollens",
    "platform": "marketside",
    "city": "Saltmarsh",
    "contact_email": "hello@saltmarshwoollens.co.uk",
    "status": "trialling",
    "created_at": "2026-08-12T14:02:11Z"
  },
  "subscription": {
    "plan": "payg",
    "status": "trialling",
    "monthly_fee_pence": 0,
    "current_period_start": null,
    "current_period_end": null,
    "trial_ends_at": "2026-09-11T14:02:11Z",
    "started_at": "2026-08-12T14:02:11Z",
    "cancelled_at": null
  },
  "key": "qp_test_c7wq2hmz9bvkx4tdnr8fgsp3"
}
```

**The key is shown once, here.** It is a `qp_test_` key and it works straight away, against
everything in the [quickstart](quickstart.md). Live keys are set up by hand when the shop signs.
An email address that already has an account, in any mix of capitals, is `409 email_in_use`.

## For the billing provider: posting an event

This section is for the billing provider, not for shops. Events come in on

```
POST /billing/events
Billing-Secret: <the secret we set up with you>
Content-Type: application/json
```

one event to a request, matched to the shop by our customer id. This is a shop that has paid
as it went since the spring moving up to standard:

```json
{
  "type": "subscription.plan_changed",
  "customer_id": "cus_wq7tbkx4mdz2hy9vcnrfgp",
  "occurred_at": "2026-08-12T10:04:31Z",
  "data": {"from_plan": "payg", "plan": "standard"}
}
```

```json
{
  "id": "bev_hq8xr2kd9wzmtc4vpbn7gs",
  "customer_id": "cus_wq7tbkx4mdz2hy9vcnrfgp",
  "plan": "standard",
  "status": "active",
  "moved": true
}
```

What an event does depends on where the subscription stands when it arrives:

| Subscription is | Event | What it does |
| --- | --- | --- |
| `trialling` | `subscription.started` | Puts the shop on the plan in `data.plan`, `active`, and on a plan with a fee a period of a month from `occurred_at`. That moment is `started_at`, and it is kept for good. |
| `trialling` | `subscription.cancelled` | `cancelled`, and the account is closed. |
| `active` or `past_due` | `subscription.plan_changed` | Moves the shop to the plan in `data.plan` and its fee. Between two plans with a fee the period stays as it was; moving to pay as you go ends it, and moving off it starts one from `occurred_at`. |
| `active` or `past_due` | `invoice.paid` | `active`, and on a plan with a fee a new period of a month from `occurred_at`. |
| `active` or `past_due` | `invoice.payment_failed` | `past_due`. The shop's keys go on working. |
| `active` or `past_due` | `subscription.cancelled` | `cancelled`, and the account is closed: every key on it answers `account_closed`. |
| `cancelled` | `subscription.started` | The shop has come back: `active` again on the plan in `data.plan`, with a new period on a plan with a fee, and its keys work again. |

Anything else is kept and moves nothing: a trialling shop is not invoiced, a running
subscription does not start a second time, and a cancelled one waits for a start.

Every event is kept as it came, with whatever is in `data`, and has an id of ours. An event whose
`occurred_at` is before the latest one we hold for that shop is kept and moves nothing too;
`"moved": false` says so. `occurred_at` needs its zone, as in `2026-08-12T10:04:31Z`, and we keep
it in UTC.

An unknown customer id is `404 not_found`, an event type not in the table is
`422 validation_failed`, and a start or a plan change without a plan we sell is the same. The
secret is `BILLING_SECRET` at our end, and without one set the feed is closed and answers
`401 invalid_billing_secret`.
