"""Israir flights over plain HTTP (the requests its own search page makes; no account, key or browser):

    GET  /api/allPossibleDestinations?siteId=isra2023          -> the ~60 cities Israir sells flights to, with their ids
    POST /api/search/FLIGHTS?origin=<json>&destination=<json>&startDate=DD/MM/YYYY&adults=N&children=<ages>&...
         -> the flights of that day (one way) with the fare per passenger type, in USD

Israir sells scheduled and charter flights between Tel Aviv and those cities only. Block seats an agency holds
("batch" flights) are not in this public search.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from typing import Any

import httpx

from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.israir.parse import TLV_ORIGIN_ID
from myt_mcp.ratelimit import SiteLimiter

ORIGIN = "https://www.israir.co.il"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9", "Referer": f"{ORIGIN}/he-IL/reservation/search/flights-abroad/results",
}
SITE_ID = "isra2023"
DESTINATIONS_TTL = 12 * 3600


class IsrairError(IntegrationError):
    pass


class IsrairClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, limiter: SiteLimiter | None = None, cache_minutes: float = 10.0):
        self._transport = transport
        self._limiter = limiter or SiteLimiter("Israir", min_interval=5.0, max_per_hour=30)
        self._cities: TTLCache[dict[str, int]] = TTLCache(DESTINATIONS_TTL, max_entries=1)
        self._cache: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=64, track_fetch_time=True)

    async def aclose(self) -> None:
        """Every request opens and closes its own connection."""

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(headers=HEADERS, timeout=40, transport=self._transport)

    async def cities(self) -> dict[str, int]:
        """city code -> Israir's id, for every city it sells flights to (Tel Aviv included)."""
        async def load() -> dict[str, int]:
            await self._limiter.acquire()
            async with self._http() as http:
                try:
                    r = await http.get(f"{ORIGIN}/api/allPossibleDestinations", params={"siteId": SITE_ID}, headers={"Accept": "application/json"})
                    found = r.json()["data"]["destinations"] if r.status_code == 200 else None
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    found = None
            if not found:
                raise IsrairError("Israir's list of destinations could not be read; try again later or check the website.")
            return {d["cityCode"]: d["ltravelId"] for d in found if d.get("cityCode") and d.get("ltravelId")}

        return await self._cities.get_or_load("cities", load)

    async def search(self, from_city: str, to_city: str, day: date, adults: int, child_ages: tuple[int, ...] = ()) -> dict[str, Any]:
        cities = await self.cities()
        key = (from_city, to_city, day.isoformat(), adults, child_ages)

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            origin = {"ltravelId": TLV_ORIGIN_ID if from_city == "TLV" else cities[from_city], "airportCode": from_city, "airportName": from_city, "cityCode": from_city,
                      "cityName": from_city, "countryCode": from_city, "countryName": from_city, "countryId": None, "priority": 0, "country": False}
            destination = {"type": "ltravelId", "destinationType": "CITY", "cityCode": to_city, "ltravelId": cities[to_city], "countryCode": None, "countryId": None}
            infants = [a for a in child_ages if a < 2]
            children = [a for a in child_ages if a >= 2]
            now = datetime.now(timezone.utc)
            params: dict[str, Any] = {
                "origin": json.dumps(origin, ensure_ascii=False, separators=(",", ":")), "destination": json.dumps(destination, separators=(",", ":")),
                "startDate": day.strftime("%d/%m/%Y"), "adults": adults, "searchTime": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "sessionMetadata": json.dumps({"clientKey": {"clientId": f"{uuid.uuid4()}-{int(now.timestamp() * 1000)}"}, "useMockData": False, "debug": False}, separators=(",", ":")),
                "siteId": SITE_ID, **({"children": ",".join(map(str, children))} if children else {}), **({"infants": ",".join(map(str, infants))} if infants else {}),
            }
            async with self._http() as http:
                try:
                    r = await http.post(f"{ORIGIN}/api/search/FLIGHTS", params=params, headers={"Content-Type": "application/json"}, json={"ignoredResults": 0, "siteId": SITE_ID})
                except httpx.HTTPError as e:
                    raise IsrairError(f"Israir could not be reached ({type(e).__name__}); try again later or check the website.") from None
            if r.status_code in (401, 403, 429):
                raise IsrairError(f"Israir refused the search ({r.status_code}). Stopping; wait a while or check the website.")
            if r.status_code != 200:
                raise IsrairError(f"Israir's search answered {r.status_code}; try again later or check the website.")
            try:
                answer = r.json()
            except ValueError:
                raise IsrairError("Israir's search returned a page instead of data (a waiting room or human check?). Stopping; open the website yourself.") from None
            if not isinstance(answer, dict) or answer.get("status") != "Success":
                raise IsrairError("Israir's search answer had an unexpected format; the site may have changed.")
            return answer

        return await self._cache.get_or_load(key, load)
