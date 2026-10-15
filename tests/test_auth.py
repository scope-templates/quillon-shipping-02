"""Keys: who gets in, who does not, and what a key can see."""

import pytest

from app import API_VERSION, throttle
from app.auth import issue_key
from app.errors import QuillonError
from conftest import CLOSED_KEY, OTHER_KEY, OTHER_SHOP, SHOP


def test_health_answers_without_a_key_and_names_the_version(client):
    answer = client.get("/health")
    assert answer.status_code == 200
    assert answer.json()["status"] == "ok"
    assert answer.json()["version"] == API_VERSION
    assert answer.headers["Quillon-Version"] == API_VERSION


def test_a_call_with_no_key_comes_back_as_a_problem_object(client):
    answer = client.get("/v1/carriers")
    assert answer.status_code == 401
    body = answer.json()
    assert body["code"] == "missing_credentials"
    assert set(body) >= {"type", "title", "status", "detail", "code"}
    assert body["status"] == 401


def test_a_key_we_will_not_take_is_refused_whatever_is_wrong_with_it(client):
    unissued = client.get(
        "/v1/carriers", headers={"Authorization": "Bearer qp_live_nothinglikeit"}
    )
    assert unissued.status_code == 401
    assert unissued.json()["code"] == "invalid_key"

    not_a_key = client.get("/v1/carriers", headers={"Authorization": "Bearer whsec_wrongthing"})
    assert not_a_key.json()["code"] == "invalid_key"

    closed = client.get("/v1/carriers", headers={"Authorization": f"Bearer {CLOSED_KEY}"})
    assert closed.status_code == 401
    assert closed.json()["code"] == "account_closed"


def test_a_test_key_and_a_live_key_see_their_own_parcels(client, live, sandbox):
    on_live = client.get("/v1/shipments", headers=live)
    on_test = client.get("/v1/shipments", headers=sandbox)
    assert [row["mode"] for row in on_live.json()["data"]] == ["live"] * 5
    assert on_test.json()["data"] == []


def test_the_minute_lets_exactly_what_it_says_through(client, sandbox, monkeypatch):
    monkeypatch.setitem(throttle.LIMITS, "test", 3)
    throttle.clear()

    answers = [client.get("/v1/carriers", headers=sandbox) for _ in range(4)]
    assert [answer.status_code for answer in answers] == [200, 200, 200, 429]
    assert [answer.headers["X-RateLimit-Remaining"] for answer in answers] == ["2", "1", "0", "0"]
    assert answers[-1].json()["code"] == "rate_limited"
    assert answers[-1].headers["X-RateLimit-Limit"] == "3"
    assert int(answers[-1].headers["X-RateLimit-Reset"]) > 0


def test_a_key_we_cannot_place_is_counted_as_a_stranger(client, monkeypatch):
    """A made-up qp_live_ key is not worth a live allowance; it counts against the address."""
    monkeypatch.setattr(throttle, "ANONYMOUS_LIMIT", 2)
    throttle.clear()
    made_up = {"Authorization": "Bearer qp_live_nothinglikeitatallxx"}

    first = client.get("/v1/carriers", headers=made_up)
    assert first.status_code == 401
    assert first.headers["X-RateLimit-Limit"] == "2"

    client.get("/v1/carriers", headers=made_up)
    other = {"Authorization": "Bearer qp_test_alsomadeupxxxxxxxxxxxx"}
    third = client.get("/v1/carriers", headers=other)
    assert third.status_code == 429
    assert third.json()["code"] == "rate_limited"


def test_a_live_key_is_allowed_what_its_plan_allows(client, live, sandbox):
    throttle.clear()
    on_standard = client.get("/v1/carriers", headers=live)
    assert on_standard.headers["X-RateLimit-Limit"] == "300"
    on_payg = client.get("/v1/carriers", headers={"Authorization": f"Bearer {OTHER_KEY}"})
    assert on_payg.headers["X-RateLimit-Limit"] == "120"
    # A test key has its own allowance, whatever the plan.
    assert client.get("/v1/carriers", headers=sandbox).headers["X-RateLimit-Limit"] == "120"
    assert throttle.limit_for("live", "volume") == 1000


def test_a_plan_has_as_many_live_keys_as_it_includes(conn):
    # Netherby pays as it goes, which is one live key, and it has it.
    with pytest.raises(QuillonError) as refused:
        issue_key(conn, OTHER_SHOP, "live", "Checkout")
    assert refused.value.code == "key_limit_reached"
    assert refused.value.status == 409
    assert issue_key(conn, OTHER_SHOP, "test", "Integration").startswith("qp_test_")

    # Wistow is on standard, which is three; it has one.
    made = [issue_key(conn, SHOP, "live", label) for label in ("Checkout", "Warehouse")]
    assert all(key.startswith("qp_live_") for key in made)
    with pytest.raises(QuillonError):
        issue_key(conn, SHOP, "live", "Staging")

    conn.execute("UPDATE subscriptions SET plan = 'volume' WHERE customer_id = ?", (SHOP,))
    assert issue_key(conn, SHOP, "live", "Staging").startswith("qp_live_")
