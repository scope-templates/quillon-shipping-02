"""Issues a key on an account, which is how a shop gets its live key when it signs.

    python scripts/issue_key.py cus_mhchwqpk49v99ybntqzhd4 live Production

Live keys go up to the number the account's plan includes. The key is printed once; send it to
the shop and do not keep it anywhere else.
"""

import argparse
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import issue_key  # noqa: E402
from app.db import connect, prepare  # noqa: E402
from app.errors import QuillonError  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Issue a key on an account.")
    parser.add_argument("customer_id")
    parser.add_argument("mode", choices=("test", "live"))
    parser.add_argument("label", nargs="?", default="Production")
    args = parser.parse_args(argv)

    with closing(prepare(connect())) as conn:
        found = conn.execute("SELECT 1 FROM customers WHERE id = ?", (args.customer_id,))
        if found.fetchone() is None:
            print(f"No shop of ours with the id {args.customer_id}.")
            return 1
        try:
            print(issue_key(conn, args.customer_id, args.mode, args.label))
        except QuillonError as refused:
            print(refused.detail)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
