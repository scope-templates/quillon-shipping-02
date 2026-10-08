# Working on Quillon Post

Everything we change starts as a ticket in the tracker, with a key like `QLN-123`: a bug, a
thing a shop has asked for, a page of the docs that is wrong.

- The branch and every commit carry the key, the branch as `qln-123-what-it-is` and the commit
  message starting with it (`QLN-123 Hold a quote for an hour`), so the tracker
  links the work to the ticket by itself.
- One ticket, one change. A bug you find while working on something else gets a ticket of its
  own, with what breaks and how to see it, rather than a drive-by fix in the branch you are on.
- If a shop can run into it before it is fixed, it goes under Known issues at the top of
  `CHANGELOG.md` with its key, and a `FIXME(QLN-123)` goes at the spot in the code. It comes off
  the list in the changelog entry for the deploy that fixes it.
- Run the tests before you push; CI runs the same on Python 3.12:

```
python -m pip install -r requirements.txt
python -m pytest
```

A change to a route or a model means running `python scripts/export_openapi.py` as well, or
the test that compares the committed spec with the app will fail.
