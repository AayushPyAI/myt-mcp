"""Polite request pacing for third-party sites we read without an official API.

Each site gets one limiter:
  * at most one request every `min_interval` seconds (calls wait their turn, in order);
  * at most `max_per_hour` requests in any rolling hour (further calls are refused with a clear message);
  * a cool-down after a block: when a site shows a human check, a captcha, 403 or 429 the client calls `trip()` and every call for the next
    30 minutes is refused at once, so we do not keep knocking on a door that has just closed (and never try to get around the check).
"""

from __future__ import annotations

import asyncio
import math
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
        self._blocked_until = float("-inf")

    def trip(self, minutes: float = 30.0) -> None:
        """The site blocked us: refuse calls to it for `minutes`."""
        self._blocked_until = self._clock() + minutes * 60

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            if now < self._blocked_until:
                raise RateLimitError(f"{self.site}: the site showed a block or a human check a moment ago, so searches are paused for about {max(1, math.ceil((self._blocked_until - now) / 60))} more minutes "
                                     "to protect the account and the connection. Check the price on the site by hand, or try again later; never work around the check.")
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
