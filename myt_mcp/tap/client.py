"""TAP Air Portugal flight prices, read from TAP's own booking page.

TAP's availability service (booking.flytap.com/bfm/rest/booking/availability/search) answers plain HTTP clients with
"ACCESS DENIED", so it is not called directly. Like the "Search" button on flytap.com, the booking page is opened in the
automation browser with the search in its link, and the answer the page receives is read. TAP's fare calendar
(www.flytap.com/api/calendar) does answer plain HTTP and is used by tap_fare_calendar. The page's market decides the currency
(PT -> EUR). If TAP shows a check or refuses, we stop.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlencode

import httpx

from myt_mcp.browser import BrowserSession
from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

BOOKING = "https://booking.flytap.com"
SITE = "https://www.flytap.com"
AVAILABILITY = "/bfm/rest/booking/availability/search"
_CHECK = re.compile(r"captcha|verify you are human|unusual (?:traffic|activity)|access denied|blocked by our security", re.I)
CALENDAR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*", "Content-Type": "application/json", "Origin": SITE, "Referer": f"{SITE}/en-us", "Accept-Language": "en-US,en;q=0.9",
}
MARKET_CURRENCY = {"PT": "EUR"}


class TapError(IntegrationError):
    pass


def search_link(origin: str, destination: str, day: date, adults: int, children: int, infants: int, market: str = "PT") -> str:
    params = {"market": market, "language": "en", "origin": origin, "destination": destination, "flexibleDates": "false", "flightType": "single",
              "adt": adults, "chd": children, "inf": infants, "yth": 0, "depDate": day.strftime("%d.%m.%Y"), "headerfooterhidden": "false", "x_tap_source": "WEB"}
    return f"{BOOKING}/booking/flights/deeplink?{urlencode(params)}"


def _is_availability(response: Any) -> bool:
    return AVAILABILITY in response.url and response.request.method == "POST"


class TapClient:
    def __init__(self, session: BrowserSession, *, limiter: SiteLimiter | None = None, cache_minutes: float = 10.0, wait_seconds: float = 60.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._session = session
        self._transport = transport
        self._limiter = limiter or SiteLimiter("TAP", min_interval=5.0, max_per_hour=20)
        self._cache: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=64, track_fetch_time=True)
        self._calendars: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=64, track_fetch_time=True)
        self._wait_ms = wait_seconds * 1000

    async def aclose(self) -> None:
        """The shared browser session is closed by its owner."""

    async def search(self, origin: str, destination: str, day: date, adults: int, children: int, infants: int) -> dict[str, Any]:
        link = search_link(origin, destination, day, adults, children, infants)

        async def action(page) -> tuple[int, str, str]:
            try:
                async with page.expect_response(_is_availability, timeout=self._wait_ms) as info:
                    await page.goto(link, wait_until="domcontentloaded", timeout=self._wait_ms)
                response = await info.value
                return response.status, await response.text(), ""
            except Exception as e:
                if type(e).__name__ != "TimeoutError":
                    raise
                body = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 2000)")
                return 0, "", body

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            status, text, page_text = await self._session.run(BOOKING, "about:blank", action)
            if status == 0:
                if _CHECK.search(page_text):
                    self._limiter.trip()
                    raise TapError("TAP's site showed a human check or refused the page. Stopping; check the fare on flytap.com.")
                raise TapError("TAP's booking page did not show flights in time. The route may not exist, or the site is slow; try again or check flytap.com.")
            if status in (401, 403, 429) or _CHECK.search(text[:3000]):
                self._limiter.trip()
                raise TapError(f"TAP refused the search ({status}). Stopping; wait a while or check flytap.com.")
            if status >= 400:
                raise TapError(f"TAP's search failed ({status}). The airport code may not be one TAP flies, or the site is having trouble; try again later.")
            try:
                answer = json.loads(text)
            except ValueError:
                raise TapError("TAP's search returned a page instead of data; the site may have changed.") from None
            if not isinstance(answer, dict) or "data" not in answer:
                raise TapError("TAP's search answer had an unexpected format; the site may have changed.")
            return answer

        return await self._cache.get_or_load(link, load)

    async def calendar(self, origin: str, destination: str, year: int, month: int) -> dict[str, Any]:
        """The lowest one-way economy price of each day of a month (per adult, USD), from TAP's fare calendar; plain HTTP."""
        key = (origin, destination, year, month)

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            body = {"cabinClass": "E", "destination": destination, "market": "US", "month": str(month), "origin": origin, "paxType": "ADT",
                    "payWithMiles": False, "starAlliance": False, "tripType": "O", "year": str(year)}
            try:
                async with httpx.AsyncClient(headers=CALENDAR_HEADERS, timeout=40, follow_redirects=True, transport=self._transport) as http:
                    await http.get(f"{SITE}/en-us", headers={"Accept": "text/html", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"})
                    r = await http.post(f"{SITE}/api/calendar?functionName=calendar", json=body)
            except httpx.HTTPError as e:
                raise TapError(f"TAP could not be reached ({type(e).__name__}); try again later or check flytap.com.") from None
            if r.status_code in (401, 403, 429):
                raise TapError(f"TAP refused the request ({r.status_code}). Stopping; wait a while or check flytap.com.")
            if r.status_code != 200:
                raise TapError(f"TAP's fare calendar answered {r.status_code}; try again later or check flytap.com.")
            try:
                answer = r.json()
                days = answer["data"]["bestPriceForDates"]
            except (ValueError, KeyError, TypeError):
                raise TapError("TAP's fare calendar had an unexpected format; the site may have changed.") from None
            return {"days": days}

        return await self._calendars.get_or_load(key, load)
