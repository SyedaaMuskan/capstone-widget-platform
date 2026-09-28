"""In-memory token-bucket rate limiter (thread-safe). Allows bursts, refills steadily."""
from __future__ import annotations

import math
import threading
import time
from typing import Callable


class TokenBucketLimiter:
    def __init__(self, capacity: float, refill_per_sec: float, max_keys: int = 50_000, clock: Callable[[], float] = time.monotonic):
        self.capacity = float(capacity)
        self.refill = float(refill_per_sec)
        self.max_keys = max_keys
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.get(key, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                allowed, retry = True, 0
            else:
                self._buckets[key] = (tokens, now)
                allowed = False
                retry = math.ceil((1 - tokens) / self.refill) if self.refill > 0 else 60
            if len(self._buckets) > self.max_keys:
                self._prune(now)
            return allowed, retry

    def _prune(self, now: float) -> None:
        """Drop buckets that have fully refilled (equivalent to fresh ones)."""
        full_after = self.capacity / self.refill if self.refill > 0 else 3600
        for k in [k for k, (_, last) in self._buckets.items() if now - last > full_after]:
            del self._buckets[k]
        if len(self._buckets) > self.max_keys:  # still huge: evict oldest half
            for k, _ in sorted(self._buckets.items(), key=lambda kv: kv[1][1])[: len(self._buckets) // 2]:
                del self._buckets[k]
