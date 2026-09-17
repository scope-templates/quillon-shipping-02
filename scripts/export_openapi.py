"""Writes openapi/quillon-post.json out of the running app.

Callum links integrators at this file, so it is committed and it is expected to be current.
Run it after changing a route or a model; `--check` says whether the committed copy still
matches, which is what the test suite asks it.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "openapi" / "quillon-post.json"


def document() -> dict:
    return app.openapi()


def as_text(spec: dict) -> str:
    return json.dumps(spec, indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Export the spec.")
    parser.add_argument("--check", action="store_true", help="compare against the committed file")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)

    text = as_text(document())
    target = Path(args.out)
    if args.check:
        if not target.exists():
            print(f"{target} is not there")
            return 1
        if target.read_text(encoding="utf-8") != text:
            print(f"{target} is not what the app describes; run scripts/export_openapi.py")
            return 1
        print(f"{target} matches")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
