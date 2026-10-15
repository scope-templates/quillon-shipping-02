"""The store: one sqlite file, opened per request, schema put up when the service starts."""

import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Dict, Iterator, Optional

from app.billing import give_missing_subscriptions
from app.ids import now, stamp

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "data" / "quillon.sqlite"

# How long an idempotency key and a label link are worth keeping.
KEEP_HOURS = 24

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    platform      TEXT NOT NULL,
    city          TEXT NOT NULL,
    contact_email TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    dispatch_address TEXT,
    label_logo    TEXT,
    technical_contact_name  TEXT,
    technical_contact_email TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    key          TEXT PRIMARY KEY,
    customer_id  TEXT NOT NULL REFERENCES customers(id),
    mode         TEXT NOT NULL,
    label        TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_used_at TEXT
);
CREATE INDEX IF NOT EXISTS api_keys_by_customer ON api_keys(customer_id);

-- One for each shop. Moved on by what the billing provider posts to /billing/events. Pay as you
-- go has no period, so both period columns are empty on it.
CREATE TABLE IF NOT EXISTS subscriptions (
    customer_id          TEXT NOT NULL UNIQUE REFERENCES customers(id),
    plan                 TEXT NOT NULL,
    status               TEXT NOT NULL,
    monthly_fee_pence    INTEGER NOT NULL,
    current_period_start TEXT,
    current_period_end   TEXT,
    trial_ends_at        TEXT,
    started_at           TEXT NOT NULL,
    cancelled_at         TEXT
);

CREATE TABLE IF NOT EXISTS carriers (
    code              TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    collection_cutoff TEXT NOT NULL,
    tracking_prefix   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS carrier_services (
    carrier_code TEXT NOT NULL REFERENCES carriers(code),
    service      TEXT NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT NOT NULL,
    max_grams    INTEGER NOT NULL,
    PRIMARY KEY (carrier_code, service)
);

CREATE TABLE IF NOT EXISTS rate_cards (
    carrier_code   TEXT NOT NULL,
    service        TEXT NOT NULL,
    zone           TEXT NOT NULL,
    max_grams      INTEGER NOT NULL,
    price_pence    INTEGER NOT NULL,
    estimated_days INTEGER NOT NULL,
    PRIMARY KEY (carrier_code, service, zone, max_grams)
);

CREATE TABLE IF NOT EXISTS quotes (
    id             TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL,
    mode           TEXT NOT NULL,
    carrier_code   TEXT NOT NULL,
    service        TEXT NOT NULL,
    price_pence    INTEGER NOT NULL,
    estimated_days INTEGER NOT NULL,
    from_postcode  TEXT NOT NULL,
    to_postcode    TEXT NOT NULL,
    weight_grams   INTEGER NOT NULL,
    dimensions_cm  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    expires_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shipments (
    id               TEXT PRIMARY KEY,
    customer_id      TEXT NOT NULL,
    mode             TEXT NOT NULL,
    carrier_code     TEXT NOT NULL,
    service          TEXT NOT NULL,
    status           TEXT NOT NULL,
    tracking_number  TEXT NOT NULL,
    reference        TEXT,
    quote_id         TEXT,
    price_pence      INTEGER NOT NULL,
    sender           TEXT NOT NULL,
    recipient        TEXT NOT NULL,
    parcel           TEXT NOT NULL,
    label_token      TEXT,
    label_expires_at TEXT,
    created_at       TEXT NOT NULL,
    collected_at     TEXT,
    delivered_at     TEXT,
    cancelled_at     TEXT
);
CREATE INDEX IF NOT EXISTS shipments_by_customer
    ON shipments(customer_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS shipments_by_status
    ON shipments(customer_id, status, created_at DESC, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS shipments_by_label
    ON shipments(label_token) WHERE label_token IS NOT NULL;
-- Not unique: parcels booked before June 2026 can share a reference, so the check that keeps
-- them apart is in the router rather than here.
CREATE INDEX IF NOT EXISTS shipments_by_reference
    ON shipments(customer_id, mode, reference) WHERE reference IS NOT NULL;

CREATE TABLE IF NOT EXISTS tracking_events (
    id          TEXT PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    code        TEXT NOT NULL,
    description TEXT NOT NULL,
    location    TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tracking_by_shipment
    ON tracking_events(shipment_id, occurred_at, id);

CREATE TABLE IF NOT EXISTS webhook_endpoints (
    id          TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    url         TEXT NOT NULL,
    events      TEXT NOT NULL,
    secret      TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    disabled_at TEXT
);
CREATE INDEX IF NOT EXISTS endpoints_by_customer
    ON webhook_endpoints(customer_id, created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id              TEXT PRIMARY KEY,
    endpoint_id     TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    shipment_id     TEXT,
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL,
    attempts        INTEGER NOT NULL,
    last_error      TEXT,
    created_at      TEXT NOT NULL,
    last_attempt_at TEXT,
    next_attempt_at TEXT,
    delivered_at    TEXT
);
CREATE INDEX IF NOT EXISTS deliveries_due
    ON webhook_deliveries(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS deliveries_by_endpoint
    ON webhook_deliveries(endpoint_id, created_at DESC);

-- Everything the billing provider has posted, kept as it came, whether it moved anything or not.
CREATE TABLE IF NOT EXISTS billing_events (
    id          TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    type        TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload     TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS billing_events_by_customer
    ON billing_events(customer_id, occurred_at, id);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    customer_id   TEXT NOT NULL,
    key           TEXT NOT NULL,
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    body_hash     TEXT NOT NULL,
    status_code   INTEGER NOT NULL,
    response_body TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (customer_id, key)
);
"""


def path() -> Path:
    """Where the store lives. DATABASE_PATH wins if it is set."""
    return Path(os.environ.get("DATABASE_PATH") or DEFAULT_PATH)


def connect(where: Optional[Path] = None) -> sqlite3.Connection:
    target = Path(where) if where else path()
    if target.parent and str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 4000")
    return conn


# Columns added to a table after it was first made, put on a store older than them.
ADDED_COLUMNS = (
    ("customers", "label_logo", "TEXT"),
    ("customers", "technical_contact_name", "TEXT"),
    ("customers", "technical_contact_email", "TEXT"),
)


def prepare(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(SCHEMA)
    for table, column, kind in ADDED_COLUMNS:
        if column not in {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    give_missing_subscriptions(conn)
    return conn


def is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0


def prune(conn: sqlite3.Connection, older_than_hours: int = KEEP_HOURS) -> Dict[str, int]:
    """Idempotency keys and label links are good for a day; older ones are dropped."""
    cutoff = stamp(now() - timedelta(hours=older_than_hours))
    keys = conn.execute("DELETE FROM idempotency_keys WHERE created_at < ?", (cutoff,)).rowcount
    labels = conn.execute(
        "UPDATE shipments SET label_token = NULL, label_expires_at = NULL "
        "WHERE label_expires_at IS NOT NULL AND label_expires_at < ?",
        (cutoff,),
    ).rowcount
    return {"idempotency_keys": max(keys, 0), "label_tokens": max(labels, 0)}


def open_store() -> None:
    """Called once when the service starts: schema up, history in if it is bare, old rows out."""
    from app.seed import load_seed

    conn = prepare(connect())
    try:
        if is_empty(conn):
            load_seed(conn)
        prune(conn)
    finally:
        conn.close()


def get_conn() -> Iterator[sqlite3.Connection]:
    """A connection of its own for one request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
