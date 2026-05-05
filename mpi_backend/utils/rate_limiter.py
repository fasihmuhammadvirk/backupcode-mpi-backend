"""
In-Memory Rate Limiter - Thread-safe rate limiting for scan operations.

Extracted from routes/extraction_queue.py to follow ADR-0012 (thin routes).
"""

import time
import threading
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class RateLimit:
    """Rate limit configuration"""
    requests: int
    window_seconds: int

    def __post_init__(self):
        if self.requests <= 0:
            raise ValueError("requests must be > 0")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")


class InMemoryRateLimiter:
    """Thread-safe in-memory rate limiter for user scan operations"""

    def __init__(self):
        self._requests: Dict[str, list] = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str, rate_limit: RateLimit) -> tuple[bool, Optional[int]]:
        """Check if request is allowed under rate limit"""
        now = time.time()
        window_start = now - rate_limit.window_seconds

        with self._lock:
            # Clean old requests
            if key in self._requests:
                self._requests[key] = [
                    req_time for req_time in self._requests[key]
                    if req_time > window_start
                ]
            else:
                self._requests[key] = []

            # Check if under limit
            current_count = len(self._requests[key])
            if current_count >= rate_limit.requests:
                # Calculate retry after
                oldest_request = min(self._requests[key])
                retry_after = int(oldest_request + rate_limit.window_seconds - now) + 1
                return False, retry_after

            # Add current request
            self._requests[key].append(now)
            return True, None
