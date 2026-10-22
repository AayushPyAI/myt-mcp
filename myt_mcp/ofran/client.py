"""Ofran car rental search through the JSON endpoints its own website uses (undocumented, may
change; keep to one search per operator request):

    GET  /api/locations                -> ~1,600 pick-up points
    POST /api/get_full_dynamic_result  -> live offers for one search
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from myt_mcp.cache import TTLCache
from myt_mcp.ofran.locations import Location, LocationIndex, parse_locations
from myt_mcp.ofran.transport import OfranError, Transport
from myt_mcp.ratelimit import SiteLimiter

LOCATIONS_TTL = 12 * 3600  # the list is ~700 KB and rarely changes


class OfranClient:
    def __init__(self, transport: Transport, *, limiter: SiteLimiter | None = None, search_cache_minutes: float = 10.0):
        self._transport = transport
        self._index_cache: TTLCache[LocationIndex] = TTLCache(LOCATIONS_TTL, max_entries=1)
        # Scraping rules: the same search within the cache window is answered from memory, and every
        # request that does reach Ofran is paced and counted by the limiter.
        self._search_cache: TTLCache[list[Any]] = TTLCache(search_cache_minutes * 60, max_entries=64, track_fetch_time=True)
        self._limiter = limiter or SiteLimiter("Ofran", min_interval=5.0, max_per_hour=60)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def _index(self) -> LocationIndex:
        async def load() -> LocationIndex:
            await self._limiter.acquire()
            index = LocationIndex(parse_locations(await self._transport.request("GET", "/api/locations")))
            if not len(index):
                raise OfranError("Ofran's location list came back empty; its site may have changed.")
            return index

        return await self._index_cache.get_or_load("locations", load)

    async def find_locations(self, query: str, limit: int = 8) -> list[Location]:
        return (await self._index()).match(query, limit)

    async def search(self, pickup: Location, dropoff: Location, pickup_date: date, dropoff_date: date,
                     pickup_time: str, dropoff_time: str, driver_age: int | None = None) -> list[Any]:
        body = {
            "CountryId": pickup.country_id,
            "PickupIataId": pickup.iata_id,
            "PickupDate": pickup_date.strftime("%d.%m.%Y"),
            "PickupHour": pickup_time,
            "DropoffIataId": dropoff.iata_id,
            "DropoffDate": dropoff_date.strftime("%d.%m.%Y"),
            "DropoffHour": dropoff_time,
            "Age": str(driver_age) if driver_age else "",
            "GoTos": {"Countries": []},
        }
        return await self._search_cache.get_or_load(json.dumps(body, sort_keys=True), lambda: self._search(body))

    async def _search(self, body: dict[str, Any]) -> list[Any]:
        await self._limiter.acquire()
        try:
            data = await self._transport.request("POST", "/api/get_full_dynamic_result", body)
        except OfranError as e:
            if "human check" in str(e) or "403" in str(e):          # a captcha or a refusal: pause Ofran, the agent account must not be flagged
                self._limiter.trip()
            raise
        if not isinstance(data, dict):
            raise OfranError("Ofran's search answer had an unexpected format; its site may have changed.")
        if data.get("errors"):
            raise OfranError(f"Ofran could not run this search: {str(data['errors'])[:200]}")
        result = data.get("result")
        if result is None:
            return []
        if not isinstance(result, list):
            raise OfranError("Ofran's search answer had an unexpected format; its site may have changed.")
        return result
