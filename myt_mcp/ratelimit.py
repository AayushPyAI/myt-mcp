"""Polite request pacing for third-party sites we read without an official API.

Each site gets one limiter:
  * at most one request every `min_interval` seconds (calls wait their turn, in order);
  * at most `max_per_hour` requests in any rolling hour (further calls are refused with a clear message).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

from myt_mcp.errors import IntegrationError


class RateLimitError(IntegrationError):
    pass


class SiteLimiter:
    def __init__(self, site: str, min_interval: float, max_per_hour: int, clock=time.monotonic, sleep=asyncio.sleep):
        self.site = site
        self.min_interval = min_interval
        self.max_per_hour = max_per_hour
        self._clock, self._sleep = clock, sleep
        self._recent: deque[float] = deque()
        self._last = float("-inf")
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            while self._recent and now - self._recent[0] >= 3600:
                self._recent.popleft()
            if len(self._recent) >= self.max_per_hour:
                wait_min = int((3600 - (now - self._recent[0])) // 60) + 1
                raise RateLimitError(
                    f"{self.site}: the limit of {self.max_per_hour} searches per hour is reached, to protect the account. "
                    f"Try again in about {wait_min} minutes, or reuse results already shown."
                )
            wait = self._last + self.min_interval - now
            if wait > 0:
                await self._sleep(wait)
                now = self._clock()
            self._last = now
            self._recent.append(now)
