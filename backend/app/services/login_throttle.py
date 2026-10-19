"""
Login attempt limiting — slows down password guessing.

After too many failed logins within a window, further attempts for that username
(or from that client address) are refused until the window passes. A successful
login clears the username's count.

State is kept in memory, which suits the single-instance deployment; with several
instances each would count separately (still a large reduction in guessing speed).
"""

import threading
import time

WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_USERNAME = 5
# Higher, so a shared office connection is not locked out by one person's typos
MAX_FAILURES_PER_ADDRESS = 20

_lock = threading.Lock()
_failures = {}  # key -> list of failure timestamps


def _recent(key, now):
    stamps = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
    if stamps:
        _failures[key] = stamps
    else:
        _failures.pop(key, None)
    return stamps


def _keys(username, address):
    return (f"user:{(username or '').strip().lower()}", MAX_FAILURES_PER_USERNAME), \
           (f"addr:{address or 'unknown'}", MAX_FAILURES_PER_ADDRESS)


def seconds_until_allowed(username, address):
    """0 if a login attempt may proceed, otherwise how long until it may."""
    now = time.monotonic()
    wait = 0
    with _lock:
        for key, limit in _keys(username, address):
            stamps = _recent(key, now)
            if len(stamps) >= limit:
                wait = max(wait, WINDOW_SECONDS - (now - stamps[0]))
    return int(wait) + 1 if wait else 0


def record_failure(username, address):
    now = time.monotonic()
    with _lock:
        for key, _ in _keys(username, address):
            _failures.setdefault(key, []).append(now)


def record_success(username):
    with _lock:
        _failures.pop(_keys(username, None)[0][0], None)


def reset():
    """Clear all counts (tests)."""
    with _lock:
        _failures.clear()
