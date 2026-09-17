# Changelog

This package follows semantic versioning. Dates are the day it went to PyPI.

## 1.3.0 — 2026-04-14

- `carriers()` returns the carriers on the account and the services each one sells.
- `list_shipments()` takes `limit` as well as `status` and `cursor`.
- `QuillonError` carries `title` and the whole problem object on `.body`.
- Dropped Python 3.8. The minimum is 3.9.

## 1.2.0 — 2025-11-05

- `list_shipments()` for the cursor-paged list the API started answering with this month.
- `quote()` takes `service` to price one service instead of all of them.
- `dimensions_cm` accepts three numbers as well as the dictionary the API uses.
- `QuillonClient` works as a context manager and closes the connection pool on the way out.

## 1.1.1 — 2025-07-21

- Fixed a crash when the API answered with an empty body on 204.
- `base_url` no longer minds a trailing slash.

## 1.1.0 — 2025-06-03

- `session` takes an `httpx.Client` of your own, for proxies and timeouts.

## 1.0.0 — 2025-02-19

- First release: `quote()`, `create_shipment()`, `get_shipment()` and `label()`.
