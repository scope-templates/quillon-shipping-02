"""The committed spec, the committed history, and the headers on every answer."""

import json
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from app import API_VERSION, throttle
from app.billing import CUSTOMER_STATUS
from app.db import connect, prepare
from app.rates import is_postcode
from app.ids import read_stamp
from app.seed import A_TIME, SEED_FILE, dated_from, days_forward, load_seed, read_seed

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_seed  # noqa: E402
import export_openapi  # noqa: E402


def test_the_committed_spec_is_what_the_app_describes():
    committed = (ROOT / "openapi" / "quillon-post.json").read_text(encoding="utf-8")
    assert committed == export_openapi.as_text(export_openapi.document())

    spec = json.loads(committed)
    assert spec["info"]["title"] == "Quillon Post API"
    assert spec["info"]["version"] == API_VERSION
    assert "/v1/shipments/{shipment_id}/cancel" in spec["paths"]


def test_the_committed_history_is_what_the_script_builds():
    assert SEED_FILE.read_text(encoding="utf-8") == build_seed.as_text(build_seed.build())


def test_the_history_loads_into_an_empty_store(tmp_path):
    conn = prepare(connect(tmp_path / "loaded.sqlite"))
    written = load_seed(conn)
    history = read_seed()
    assert written["customers"] == len(history["customers"]) == 140
    assert written["shipments"] == len(history["shipments"])
    assert written["tracking_events"] == len(history["tracking_events"])
    assert written["subscriptions"] == 140
    assert written["billing_events"] == len(history["billing_events"])

    counted = conn.execute(
        "SELECT status, COUNT(*) AS how_many FROM shipments GROUP BY status"
    ).fetchall()
    assert dict((row["status"], row["how_many"]) for row in counted)["delivered"] > 4000

    # Every shop has a subscription, and the customer status is the one its subscription gives.
    pairs = conn.execute(
        "SELECT c.status AS customer, s.status AS subscription FROM customers c "
        "JOIN subscriptions s ON s.customer_id = c.id"
    ).fetchall()
    assert len(pairs) == 140
    assert all(CUSTOMER_STATUS[row["subscription"]] == row["customer"] for row in pairs)

    # Loading twice leaves the shop that was already there alone.
    assert load_seed(conn)["customers"] == 0
    conn.close()


def test_the_history_ends_the_day_before_the_store_was_opened(tmp_path):
    committed = read_seed()
    oldest = min(row["created_at"] for row in committed["shipments"])
    newest = max(row["created_at"] for row in committed["shipments"])

    opened = datetime(2027, 3, 18, 9, 40, tzinfo=timezone.utc)
    with closing(prepare(connect(tmp_path / "opened.sqlite"))) as conn:
        load_seed(conn, opened=opened)
        first, last = conn.execute(
            "SELECT MIN(created_at), MAX(created_at) FROM shipments"
        ).fetchone()
    assert last[:10] == "2027-03-17"
    assert read_stamp(last) - read_stamp(first) == read_stamp(newest) - read_stamp(oldest)

    # Opened before six in the morning, the history ends a day earlier, so that nothing in it
    # happened after the store was opened.
    early = datetime(2027, 3, 18, 3, 0, tzinfo=timezone.utc)
    assert days_forward(early) == days_forward(opened) - 1


def test_every_time_in_the_history_moves_by_the_same_days():
    committed = read_seed()
    days = days_forward(datetime(2027, 3, 18, 9, 40, tzinfo=timezone.utc))
    shifted = dated_from(committed, days)

    def times(value, out):
        if isinstance(value, dict):
            for inner in value.values():
                times(inner, out)
        elif isinstance(value, list):
            for inner in value:
                times(inner, out)
        elif isinstance(value, str) and A_TIME.match(value):
            out.append(value)
        return out

    before, after = times(committed, []), times(shifted, [])
    assert before and len(before) == len(after)
    assert {(read_stamp(b) - read_stamp(a)).days for a, b in zip(before, after)} == {days}


def test_every_address_in_the_history_has_a_postcode_we_would_quote_on():
    history = read_seed()
    postcodes = {shop["dispatch_address"]["postcode"] for shop in history["customers"]}
    for row in history["shipments"]:
        postcodes.add(row["recipient"]["postcode"])
        if row.get("sender"):
            postcodes.add(row["sender"]["postcode"])
    assert postcodes
    assert [code for code in postcodes if not is_postcode(code)] == []


def test_every_answer_carries_the_version_and_what_is_left_of_the_rate_limit(client, live):
    throttle.clear()
    answer = client.get("/v1/carriers", headers=live)
    assert answer.headers["Quillon-Version"] == API_VERSION
    assert answer.headers["X-RateLimit-Limit"] == str(throttle.LIMITS["live"])
    assert answer.headers["X-RateLimit-Remaining"] == str(throttle.LIMITS["live"] - 1)

    second = client.get("/v1/carriers", headers=live)
    assert second.headers["X-RateLimit-Remaining"] == str(throttle.LIMITS["live"] - 2)

    refused = client.get("/v1/shipments/shp_nothing", headers=live)
    assert refused.status_code == 404
    assert refused.headers["X-RateLimit-Limit"] == str(throttle.LIMITS["live"])
