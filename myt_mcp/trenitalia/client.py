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

from urllib.parse import urlencode

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
                 search_cache_minutes: float = 10.0, timeout: float = 30.0, browser: Any = None):
        self._browser = browser          # the server's automation Chrome: used only when the plain HTTP request is refused or fails (a block, a network error)
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

    async def _http_status(self, method: str, path: str, kwargs: dict[str, Any]) -> tuple[int, str]:
        resp = await self._http.request(method, path, **kwargs)
        return resp.status_code, resp.text

    async def _browser_status(self, method: str, path: str, kwargs: dict[str, Any]) -> tuple[int, str]:
        """The same request, made by the page of www.lefrecce.it in the automation Chrome (its own cookies and network)."""
        url = BASE_URL + path + (("?" + urlencode(kwargs["params"])) if kwargs.get("params") else "")
        got = await self._browser.fetch("https://www.lefrecce.it", "https://www.lefrecce.it/", method, url, kwargs.get("json"), None)
        return int(got["status"]), str(got["text"])

    async def _request(self, method: str, path: str, *, limiter: SiteLimiter, **kwargs: Any) -> Any:
        await limiter.acquire()
        status: int | None = None
        text = ""
        failure: TrenitaliaError | None = None
        try:
            status, text = await self._http_status(method, path, kwargs)
        except httpx.TimeoutException:
            failure = TrenitaliaError("Trenitalia did not answer in time. Try again in a minute.")
        except httpx.HTTPError as e:
            failure = TrenitaliaError(f"Could not reach Trenitalia ({type(e).__name__}).")
        if self._browser is not None and (failure is not None or status in (403, 429)):
            try:                       # HTTP first, the automation Chrome second
                status, text = await self._browser_status(method, path, kwargs)
                failure = None
            except IntegrationError:
                pass                   # keep the HTTP answer's own message below
        if failure is not None or status is None:
            raise failure or TrenitaliaError("Trenitalia did not answer.")
        if status in (403, 429):
            raise TrenitaliaError(f"Trenitalia refused the request ({status}). Wait a while before trying again.")
        if status >= 500:
            raise TrenitaliaError(f"Trenitalia is having problems ({status}). Try again later.")
        if status == 400 and path.startswith("/ticket"):
            raise TrenitaliaError("Trenitalia rejected this search (400). There are two possible causes and this answer does not say which: "
                                  "(1) the date is beyond its published timetable (trains were shown about 11 months ahead, not 14); "
                                  "(2) Trenitalia cannot sell these two stations as one ticket (for example Fiumicino Aeroporto to Firenze, "
                                  "rejected on every date, even in March 2027). Do not tell the operator which one it is: retry the SAME date "
                                  "with the city station (Roma Termini instead of Fiumicino Aeroporto). If that works, the date is fine and the "
                                  "airport leg is a separate transfer (not priced by this tool).")
        if status >= 400:
            raise TrenitaliaError(f"Trenitalia could not run this search ({status}): {text[:160]}")
        try:
            return json.loads(text)
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
