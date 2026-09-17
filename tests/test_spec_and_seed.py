"""The committed spec, the committed history, and the headers on every answer."""

import json
import sys
from pathlib import Path

from app import API_VERSION, throttle
from app.db import connect, prepare
from app.rates import is_postcode
from app.seed import SEED_FILE, load_seed, read_seed

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

    counted = conn.execute(
        "SELECT status, COUNT(*) AS how_many FROM shipments GROUP BY status"
    ).fetchall()
    assert dict((row["status"], row["how_many"]) for row in counted)["delivered"] > 4000

    # Loading twice leaves the shop that was already there alone.
    assert load_seed(conn)["customers"] == 0
    conn.close()


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
