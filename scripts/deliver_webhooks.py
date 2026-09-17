"""Works through the webhook queue: posts what is due, signs it, writes down how it went.

Runs on a timer on the box in Bristol, a minute apart. Nothing in a request ever posts to a
shop directly, so a slow endpoint slows nobody down but itself.

    python scripts/deliver_webhooks.py            # everything due now, then stop
    python scripts/deliver_webhooks.py --loop      # the same, once a minute, until killed
    python scripts/deliver_webhooks.py --limit 50  # a batch
    python scripts/deliver_webhooks.py --dry-run   # say what would go, post nothing
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import webhooks  # noqa: E402
from app.db import connect, prepare  # noqa: E402

TIMEOUT_SECONDS = 10.0
BATCH = 200
SLEEP_SECONDS = 60


def post_one(client: httpx.Client, delivery: dict) -> httpx.Response:
    payload = delivery["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    body = webhooks.body_bytes(payload)
    return client.post(
        delivery["url"],
        content=body,
        headers={
            "Content-Type": "application/json",
            webhooks.SIGNATURE_HEADER: webhooks.sign(delivery["secret"], body),
        },
    )


def run(limit: int = BATCH, dry_run: bool = False) -> int:
    conn = prepare(connect())
    try:
        queued = webhooks.due(conn)[:limit]
        if not queued:
            print("nothing due")
            return 0
        sent = held = 0
        with httpx.Client(timeout=TIMEOUT_SECONDS) as client:
            for delivery in queued:
                attempts = delivery["attempts"] + 1
                if dry_run:
                    print(f"would post {delivery['id']} to {delivery['url']}")
                    continue
                try:
                    answer = post_one(client, delivery)
                except httpx.ConnectError:
                    webhooks.record_failure(conn, delivery["id"], attempts, "connection_refused")
                    held += 1
                    continue
                except httpx.HTTPError as problem:
                    webhooks.record_failure(
                        conn, delivery["id"], attempts, type(problem).__name__
                    )
                    held += 1
                    continue
                if 200 <= answer.status_code < 300:
                    webhooks.record_success(conn, delivery["id"], attempts)
                    sent += 1
                else:
                    webhooks.record_failure(
                        conn,
                        delivery["id"],
                        attempts,
                        f"{answer.status_code} from endpoint",
                    )
                    held += 1
        print(f"{len(queued)} due, {sent} taken, {held} to try again")
        return 0
    finally:
        conn.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Post what is due on the webhook queue.")
    parser.add_argument("--limit", type=int, default=BATCH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--loop", action="store_true", help=f"keep going, {SLEEP_SECONDS} seconds apart"
    )
    args = parser.parse_args(argv)
    if not args.loop:
        return run(limit=args.limit, dry_run=args.dry_run)
    while True:
        try:
            run(limit=args.limit, dry_run=args.dry_run)
        except KeyboardInterrupt:
            return 0
        except Exception as problem:  # a bad batch is not worth stopping the timer for
            print(f"batch failed: {problem}")
        time.sleep(SLEEP_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
