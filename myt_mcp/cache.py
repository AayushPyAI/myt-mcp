"""Small async TTL cache: concurrent callers for the same key share one load.

Caches holding prices are created with `track_fetch_time=True`: every value they hand out reports when it
was really fetched (myt_mcp.checks), so answers served from cache still show the true check time."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Generic, TypeVar

from myt_mcp.checks import record_fetch

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(self, ttl_seconds: float, max_entries: int = 32, *, track_fetch_time: bool = False):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self.track_fetch_time = track_fetch_time
        self._data: OrderedDict[Hashable, tuple[float, float, V]] = OrderedDict()   # monotonic, wall clock, value
        self._locks: dict[Hashable, asyncio.Lock] = {}

    def _fresh(self, key: Hashable) -> tuple[bool, V | None]:
        hit = self._data.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            self._data.move_to_end(key)
            if self.track_fetch_time:
                record_fetch(hit[1])
            return True, hit[2]
        return False, None

    def invalidate(self, key: Hashable) -> None:
        """Drop one cached entry, e.g. after a write that makes it stale."""
        self._data.pop(key, None)

    async def get_or_load(self, key: Hashable, loader: Callable[[], Awaitable[V]]) -> V:
        found, value = self._fresh(key)
        if found:
            return value  # type: ignore[return-value]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            found, value = self._fresh(key)  # another caller may have loaded it meanwhile
            if found:
                return value  # type: ignore[return-value]
            value = await loader()  # a failed load is not cached
            self._data[key] = (time.monotonic(), time.time(), value)
            if self.track_fetch_time:
                record_fetch(self._data[key][1])
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                old, _ = self._data.popitem(last=False)
                self._locks.pop(old, None)
            return value

    def clear(self) -> None:
        self._data.clear()
