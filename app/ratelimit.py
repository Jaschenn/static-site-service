"""In-memory rate limiting for API endpoints."""
import time
from collections import defaultdict

from fastapi import HTTPException, Request


class RateLimiter:
    """IP-based rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    async def __call__(self, request: Request):
        ip = request.client.host if request.client else "unknown"
        self._check(ip)

    def _check(self, key: str):
        now = time.time()
        self._requests[key] = [t for t in self._requests[key] if t > now - self.window]
        if len(self._requests[key]) >= self.max_requests:
            raise HTTPException(status_code=429, detail="请求太频繁，请稍后再试")
        self._requests[key].append(now)

    def check_key(self, key: str):
        """Rate-limit by an arbitrary key (e.g. email)."""
        self._check(key)
