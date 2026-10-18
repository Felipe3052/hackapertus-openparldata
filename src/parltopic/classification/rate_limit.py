"""Process-local request-start limiter shared across pooled clients and retries."""

import math
import threading
import time
from collections import deque


class StartLimiter:
    def __init__(self, requests_per_minute: float = 30, clock=None, sleep=None):
        self.rpm = requests_per_minute
        if not math.isfinite(self.rpm) or self.rpm < 0:
            raise ValueError("RPM must be finite and nonnegative; zero disables admission")
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self.lock = threading.Lock()
        self.starts = deque()
        self.next_start = 0.0

    def wait(self) -> float:
        started = self.clock()
        if not self.rpm:
            return 0.0
        with self.lock:
            while True:
                now = self.clock()
                while self.starts and now - self.starts[0] >= 60:
                    self.starts.popleft()
                delay = max(0, self.next_start - now)
                if len(self.starts) >= max(1, math.floor(self.rpm)):
                    delay = max(delay, self.starts[0] + 60 - now)
                if delay <= 0:
                    break
                self.sleep(delay)
            now = self.clock()
            self.starts.append(now)
            self.next_start = now + 60 / self.rpm
        return self.clock() - started


_shared_lock = threading.Lock()
_limiters: dict[tuple[str, str, float], StartLimiter] = {}


def shared_limiter(base_url: str, api_key: str, rpm: float) -> StartLimiter:
    # Credentials scope the in-memory quota; never log or serialize this cache key.
    # A cache miss must create only one limiter even when clients start concurrently.
    with _shared_lock:
        key = (base_url, api_key, rpm)
        if key not in _limiters:
            _limiters[key] = StartLimiter(rpm)
        return _limiters[key]
