"""The rate limit: a fixed window a minute long, counted per key, held in memory on one box."""

import threading
import time
from typing import Dict, Optional, Tuple

WINDOW_SECONDS = 60
LIMITS = {"live": 600, "test": 120}
ANONYMOUS_LIMIT = 60

LIMIT_HEADER = "X-RateLimit-Limit"
REMAINING_HEADER = "X-RateLimit-Remaining"
RESET_HEADER = "X-RateLimit-Reset"

_counts: Dict[str, Tuple[int, int]] = {}
_lock = threading.Lock()


def limit_for(mode: str) -> int:
    return LIMITS.get(mode, ANONYMOUS_LIMIT)


def window_of(at: float) -> int:
    return int(at // WINDOW_SECONDS)


def take(bucket: str, limit: int, at: Optional[float] = None) -> Tuple[bool, int, int]:
    """Count one call: whether it is inside the limit, what is left, when the window turns."""
    moment = time.time() if at is None else at
    window = window_of(moment)
    with _lock:
        seen_window, used = _counts.get(bucket, (window, 0))
        if seen_window != window:
            seen_window, used = window, 0
        used += 1
        _counts[bucket] = (seen_window, used)
    resets_at = (window + 1) * WINDOW_SECONDS
    return used <= limit, max(limit - used, 0), int(resets_at)


def clear() -> None:
    with _lock:
        _counts.clear()
