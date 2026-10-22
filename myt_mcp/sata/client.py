"""SATA flight prices (Azores Airlines S4 and SATA Air Açores SP), read from SATA's own booking site.

SATA's search service only answers the booking page itself (each request carries a token from the page's
invisible reCAPTCHA), so it is never called directly. Instead the booking page is opened in the automation
browser with the search in its link, exactly as the "Search" button on azoresairlines.pt does, and we read
the flight list the page receives. If SATA refuses or shows a check, we stop.

    book.azoresairlines.pt/booking/dl?step=flights&search=LIS.PDL.2026-11-10*PDL.LIS.2026-11-17&adults=2...
        -> the page calls api-book.azoresairlines.pt/ibe/pricedAvailability -> flights, fares, group totals
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any
from urllib.parse import urlencode

from myt_mcp.browser import BrowserSession
from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

ORIGIN = "https://book.azoresairlines.pt"
SEARCH_API = "/ibe/pricedAvailability"
_CHECK = re.compile(r"captcha|verify you are human|unusual (?:traffic|activity)|access denied", re.I)


class SataError(IntegrationError):
    pass


def search_link(origin: str, destination: str, departure: date, return_date: date | None,
                adults: int, children: int, infants: int) -> str:
    search = f"{origin}.{destination}.{departure.isoformat()}"
    if return_date:
        search += f"*{destination}.{origin}.{return_date.isoformat()}"
    params = {"step": "flights", "pointOfSale": "PT", "adults": adults, "lang": "en", "search": search}
    if children:
        params["children"] = children
    if infants:
        params["infants"] = infants
    return f"{ORIGIN}/booking/dl?{urlencode(params, safe='*')}"


def _is_flight_search(response: Any) -> bool:
    return SEARCH_API in response.url and '"solutions":true' in (response.request.post_data or "")


class SataClient:
    def __init__(self, session: BrowserSession, *, limiter: SiteLimiter | None = None, cache_minutes: float = 10.0,
                 wait_seconds: float = 40.0):
        self._session = session
        self._limiter = limiter or SiteLimiter("SATA", min_interval=5.0, max_per_hour=60)
        self._cache: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=64, track_fetch_time=True)
        self._wait_ms = wait_seconds * 1000

    async def aclose(self) -> None:
        """The shared browser session is closed by its owner."""

    async def search(self, origin: str, destination: str, departure: date, return_date: date | None,
                     adults: int, children: int, infants: int) -> dict[str, Any]:
        link = search_link(origin, destination, departure, return_date, adults, children, infants)

        async def action(page) -> tuple[int, str, str]:
            try:
                async with page.expect_response(_is_flight_search, timeout=self._wait_ms) as info:
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
            status, text, page_text = await self._session.run(ORIGIN, "about:blank", action)
            if status == 0:
                if _CHECK.search(page_text):
                    self._limiter.trip()
                    raise SataError("SATA's site showed a human check. Stopping; check the fare on azoresairlines.pt.")
                raise SataError("SATA's booking page did not show flights in time. The route may not exist, or the site is slow; try again or check azoresairlines.pt.")
            if status in (401, 403, 429):
                self._limiter.trip()
                raise SataError(f"SATA refused the search ({status}). Stopping; wait a while or check azoresairlines.pt.")
            if status in (400, 500):
                raise SataError(f"SATA could not run this search ({status}). The airport code is probably not one SATA serves "
                                "(check it), or the site is having trouble; try again in a few minutes.")
            if status >= 400:
                raise SataError(f"SATA's search failed ({status}). Try again later.")
            try:
                answer = json.loads(text)
            except ValueError:
                raise SataError("SATA's search returned a page instead of data; the site may have changed.") from None
            if not isinstance(answer, dict):
                raise SataError("SATA's search answer had an unexpected format.")
            return answer

        return await self._cache.get_or_load(link, load)
