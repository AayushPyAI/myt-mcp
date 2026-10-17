"""Kiwitaxi private transfers over plain HTTP (the same three requests the website's search form makes):

    GET /en/search/autocomplete?searchSession=<id the page makes up>&input=<text>[&pairId=<from place id>] -> places
    GET /en/product-search-v2?search_session=...&place_from_id=...&place_to_id=...&date_start=YYYY-MM-DD&passenger_count=N
        -> 302 to the route's results page, which lists the vehicle classes with their prices

No account, key or browser is used. The site only answers requests that look like a browser navigation, so those
headers are sent. Prices are asked in EUR through the site's currency cookie.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import date
from typing import Any

import httpx

from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.kiwitaxi.parse import parse_results, place_matches
from myt_mcp.ratelimit import SiteLimiter

ORIGIN = "https://kiwitaxi.com"
PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Referer": f"{ORIGIN}/", "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}
JSON_HEADERS = {"Accept": "application/json", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}
HUMAN_CHECK = re.compile(r"captcha|verify you are human|access denied|unusual traffic", re.I)


class KiwitaxiError(IntegrationError):
    pass


class KiwitaxiClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, limiter: SiteLimiter | None = None, cache_minutes: float = 10.0):
        self._transport = transport
        self._limiter = limiter or SiteLimiter("Kiwitaxi", min_interval=5.0, max_per_hour=30)
        self._cache: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=64, track_fetch_time=True)

    async def aclose(self) -> None:
        """Every search opens and closes its own connection."""

    async def places(self, http: httpx.AsyncClient, session: str, text: str, pair_id: str | None = None) -> list[dict[str, Any]]:
        params = {"language": "en", "searchSession": session, "input": text, **({"pairId": pair_id} if pair_id else {})}
        r = await http.get(f"{ORIGIN}/en/search/autocomplete", params=params, headers=JSON_HEADERS)
        if r.status_code != 200:
            raise KiwitaxiError(f"Kiwitaxi's place search answered {r.status_code}; try again later or check the website.")
        try:
            found = r.json()
        except ValueError:
            raise KiwitaxiError("Kiwitaxi's place search returned a page instead of data; the site may have changed.") from None
        return [p for p in found if isinstance(p, dict) and p.get("id") and p.get("title")] if isinstance(found, list) else []

    @staticmethod
    def _choose(places: list[dict[str, Any]], typed: str, pick: int, name: str, pick_name: str) -> dict[str, Any]:
        """The suggestion asked for. Without an explicit pick, the first suggestion that really resembles what was typed:
        Kiwitaxi's own first suggestion can be another town, and a transfer priced between the wrong places is worse than none."""
        if pick:
            return places[pick]
        for place in places:
            if place_matches(typed, place):
                return place
        found = "; ".join(f"{p['title']} ({p.get('address') or 'no address'})" for p in places[:4])
        raise KiwitaxiError(f"Kiwitaxi suggested {found} for {name} {typed!r}, none of which looks like it, so no price was read. "
                            f"Try the airport code or a street address with the town, or check the suggestions and pass {pick_name} = 1, 2, 3.")

    async def search(self, from_text: str, to_text: str, day: date, passengers: int, from_pick: int = 0, to_pick: int = 0) -> dict[str, Any]:
        key = (" ".join(from_text.lower().split()), " ".join(to_text.lower().split()), day.isoformat(), passengers, from_pick, to_pick)

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            async with httpx.AsyncClient(headers=PAGE_HEADERS, follow_redirects=False, timeout=30, transport=self._transport) as http:
                try:
                    await http.get(f"{ORIGIN}/en/", follow_redirects=True)                       # cookies, as a first visit
                    http.cookies.set("userCurrencyCode", "EUR", domain="kiwitaxi.com")
                    session = str(uuid.uuid4())
                    origins = await self.places(http, session, from_text)
                    if len(origins) <= from_pick:
                        raise KiwitaxiError(f"Kiwitaxi knows no place for {from_text!r}; try another name (airport name or code, or a street address with the city).")
                    origin = self._choose(origins, from_text, from_pick, "from_place", "from_match")
                    await asyncio.sleep(0.4)
                    destinations = await self.places(http, session, to_text, origin["id"])
                    if len(destinations) <= to_pick:
                        raise KiwitaxiError(f"Kiwitaxi knows no place for {to_text!r}; try another name (hotel name or a street address with the city).")
                    destination = self._choose(destinations, to_text, to_pick, "to_place", "to_match")
                    params = {"search_session": session, "from": origin["title"], "place_from_id": origin["id"], "place_from_address": origin.get("address") or "",
                              "to": destination["title"], "place_to_id": destination["id"], "place_to_address": destination.get("address") or "",
                              "all_passenger_count": passengers, "passenger_count": passengers, "date_start": day.isoformat()}
                    await asyncio.sleep(0.4)
                    r = await http.get(f"{ORIGIN}/en/product-search-v2", params=params)
                    if r.status_code in (301, 302, 303) and r.headers.get("location"):
                        await asyncio.sleep(0.4)
                        r = await http.get(f"{ORIGIN}{r.headers['location']}" if r.headers["location"].startswith("/") else r.headers["location"], follow_redirects=True)
                except httpx.HTTPError as e:
                    raise KiwitaxiError(f"Kiwitaxi could not be reached ({type(e).__name__}); try again later or check the website.") from None
            if HUMAN_CHECK.search(r.text[:3000]) and "car-class-card" not in r.text:
                raise KiwitaxiError("Kiwitaxi showed a human check. Stopping; open the search in the browser yourself.")
            if r.status_code not in (200, 404):
                raise KiwitaxiError(f"Kiwitaxi's results page answered {r.status_code}; try again later or check the website.")
            parsed = parse_results(r.text) if r.status_code == 200 else {"route": {k: None for k in ("from", "to", "to_address", "date", "passengers", "driving_time")}, "offers": []}
            return {**parsed, "url": str(r.url).split("#")[0],
                    "chosen_from": origin, "chosen_to": destination,
                    "other_from": [p["title"] for p in origins[:5] if p is not origin],
                    "other_to": [p["title"] for p in destinations[:5] if p is not destination]}

        return await self._cache.get_or_load(key, load)
