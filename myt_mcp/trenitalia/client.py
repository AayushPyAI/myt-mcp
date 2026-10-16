"""Trenitalia train search through the JSON service behind trenitalia.com (lefrecce.it).

Undocumented, so it can change; keep to one search per operator request.

    GET  /locations/search?name=Firenze&limit=5  -> stations (id, name)
    POST /ticket/solutions                       -> trains, classes and fares for one search
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import httpx

from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

BASE_URL = "https://www.lefrecce.it/Channels.Website.BFF.WEB/website"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
STATIONS_TTL = 24 * 3600
PAGE_SIZE = 10      # Trenitalia answers at most 10 trains per request, whatever `limit` says; `offset` gives the next ones


class TrenitaliaError(IntegrationError):
    pass


class TrenitaliaClient:
    def __init__(self, *, http: httpx.AsyncClient | None = None, limiter: SiteLimiter | None = None,
                 search_cache_minutes: float = 10.0, timeout: float = 30.0):
        self._http = http or httpx.AsyncClient(
            base_url=BASE_URL, timeout=timeout,
            headers={"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"},
        )
        # Searches are paced by `limiter`; station lookups are tiny, cached for a day, and get a lighter limiter.
        self._limiter = limiter or SiteLimiter("Trenitalia", min_interval=3.0, max_per_hour=60)
        self._lookup_limiter = SiteLimiter("Trenitalia stations", min_interval=0.5, max_per_hour=300)
        self._stations: TTLCache[list[dict[str, Any]]] = TTLCache(STATIONS_TTL, max_entries=256)
        self._searches: TTLCache[dict[str, Any]] = TTLCache(search_cache_minutes * 60, max_entries=64, track_fetch_time=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, *, limiter: SiteLimiter, **kwargs: Any) -> Any:
        await limiter.acquire()
        try:
            resp = await self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise TrenitaliaError("Trenitalia did not answer in time. Try again in a minute.") from None
        except httpx.HTTPError as e:
            raise TrenitaliaError(f"Could not reach Trenitalia ({type(e).__name__}).") from None
        if resp.status_code in (403, 429):
            raise TrenitaliaError(f"Trenitalia refused the request ({resp.status_code}). Wait a while before trying again.")
        if resp.status_code >= 500:
            raise TrenitaliaError(f"Trenitalia is having problems ({resp.status_code}). Try again later.")
        if resp.status_code == 400 and path.startswith("/ticket"):
            raise TrenitaliaError("Trenitalia rejected this search (400). Usually the date is too far ahead for its timetable "
                                  "(about 6 months at most), or the two stations cannot be connected. Try a nearer date or check trenitalia.com.")
        if resp.status_code >= 400:
            raise TrenitaliaError(f"Trenitalia could not run this search ({resp.status_code}): {resp.text[:160]}")
        try:
            return resp.json()
        except ValueError:
            raise TrenitaliaError("Trenitalia returned a page instead of data; the site may have changed.") from None

    async def find_stations(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        key = (query.strip().lower(), limit)

        async def load() -> list[dict[str, Any]]:
            data = await self._request("GET", "/locations/search", limiter=self._lookup_limiter,
                                       params={"name": query.strip(), "limit": limit})
            if not isinstance(data, list):
                raise TrenitaliaError("Trenitalia's station list had an unexpected format; the site may have changed.")
            return [{"id": s["id"], "name": s.get("displayName") or s.get("name")} for s in data if isinstance(s, dict) and s.get("id")]

        return await self._stations.get_or_load(key, load)

    async def search(self, origin_id: int, destination_id: int, departure: datetime, adults: int,
                     children: int = 0, limit: int = PAGE_SIZE, offset: int = 0,
                     frecce_only: bool = False, regional_only: bool = False) -> dict[str, Any]:
        body = {
            "departureLocationId": origin_id,
            "arrivalLocationId": destination_id,
            "departureTime": departure.strftime("%Y-%m-%dT%H:%M:00.000"),
            "adults": adults,
            "children": children,
            "criteria": {"frecceOnly": frecce_only, "regionalOnly": regional_only, "noChanges": False,
                         "order": "DEPARTURE_DATE", "limit": limit, "offset": offset},
            "advancedSearchRequest": {"bestFare": False},
        }

        async def load() -> dict[str, Any]:
            try:
                data = await self._request("POST", "/ticket/solutions", limiter=self._limiter, json=body)
            except TrenitaliaError as e:
                # Trenitalia answers 400 "no travel solutions" when a train-type filter matches nothing (e.g. regional trains not
                # published yet for a far date). For a filtered search that is an empty result, not an error.
                if (frecce_only or regional_only) and "rejected this search (400)" in str(e):
                    return {"solutions": []}
                raise
            if not isinstance(data, dict):
                raise TrenitaliaError("Trenitalia's answer had an unexpected format; the site may have changed.")
            return data

        return await self._searches.get_or_load(json.dumps(body, sort_keys=True), load)

    async def search_many(self, origin_id: int, destination_id: int, departure: datetime, adults: int,
                          children: int = 0, count: int = PAGE_SIZE, frecce_only: bool = False,
                          regional_only: bool = False) -> dict[str, Any]:
        """The first `count` trains from `departure`: one request per 10 trains (each paced and cached like a normal search),
        stopping at the first short page, which means the day has no more trains."""
        merged: dict[str, Any] | None = None
        for offset in range(0, count, PAGE_SIZE):
            page = await self.search(origin_id, destination_id, departure, adults, children, limit=PAGE_SIZE, offset=offset,
                                     frecce_only=frecce_only, regional_only=regional_only)
            if merged is None:
                merged = {**page, "solutions": list(page.get("solutions") or [])}
            else:
                merged["solutions"].extend(page.get("solutions") or [])
            if len(page.get("solutions") or []) < PAGE_SIZE:
                break
        return merged or {"solutions": []}
