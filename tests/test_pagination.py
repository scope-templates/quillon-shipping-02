"""Walking a list a page at a time."""


def test_the_cursor_walks_the_whole_list_once(client, live):
    seen = []
    cursor = None
    for _ in range(5):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = client.get("/v1/shipments", headers=live, params=params).json()
        seen.extend(row["id"] for row in page["data"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    assert len(seen) == len(set(seen)) == 5
    whole = client.get("/v1/shipments", headers=live).json()
    assert seen == [row["id"] for row in whole["data"]]


def test_a_list_narrows_to_one_status(client, live):
    page = client.get("/v1/shipments", headers=live, params={"status": "created"}).json()
    assert {row["status"] for row in page["data"]} == {"created"}
    assert page["next_cursor"] is None

    wrong = client.get("/v1/shipments", headers=live, params={"status": "lost"})
    assert wrong.status_code == 422
    assert wrong.json()["code"] == "validation_failed"


def test_a_page_we_cannot_serve_is_refused_rather_than_guessed_at(client, live):
    assert client.get("/v1/shipments", headers=live, params={"limit": 0}).status_code == 422
    assert client.get("/v1/shipments", headers=live, params={"limit": 500}).status_code == 422
    assert client.get("/v1/shipments", headers=live, params={"limit": 100}).status_code == 200

    made_up = client.get("/v1/shipments", headers=live, params={"cursor": "made-up"})
    assert made_up.status_code == 422
    assert made_up.json()["code"] == "invalid_cursor"
