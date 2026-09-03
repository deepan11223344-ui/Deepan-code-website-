"""
In-process token-bucket rate limiter for the web API.

Single-process safe (threading.Lock). For multi-replica deployments put
this behind Redis; the check() signature is deliberately backend-shaped.
Buckets: per-IP (login/auth abuse), per-user (chat/WS), global WS accepts.
"""

import threading
import time
from collections import defaultdict

_policies = {
    "login": (10, 900),     # 10 attempts / 15 min per key (account lockout at 5 bites first)
    "chat": (30, 60),       # 30 turns / min per user
    "ws": (10, 60),         # 10 socket accepts / min per IP
    "api": (120, 60),       # 120 REST calls / min per key
    "refresh": (20, 300),   # 20 refreshes / 5 min per key
}

_hits: dict = defaultdict(list)
_lock = threading.Lock()


def check(policy: str, key: str) -> bool:
    """True if allowed (and recorded). False when the bucket is exhausted."""
    limit, window = _policies.get(policy, (60, 60))
    now = time.time()
    with _lock:
        items = [t for t in _hits[(policy, key)] if now - t < window]
        if len(items) >= limit:
            _hits[(policy, key)] = items
            return False
        items.append(now)
        _hits[(policy, key)] = items
        return True


def reset() -> None:
    """Tests only."""
    with _lock:
        _hits.clear()
