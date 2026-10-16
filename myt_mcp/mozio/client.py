"""Mozio transfer prices, read from Mozio's own search page.

mozio.com's search page calls api.mozio.com (create a search, then poll it). That API wants a key that only the website's own
code carries, so we do not call it ourselves: the search page is opened in the automation browser with the search in its link
(the same link the "Find rides" button builds) and the answers the page receives are read. If Mozio shows a human check or
refuses, we stop.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date, time
from typing import Any
from urllib.parse import urlencode

from myt_mcp.browser import BrowserSession
from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

SITE = "https://www.mozio.com"
API = "api.mozio.com/v2/search"
_CHECK = re.compile(r"captcha|verify you are human|unusual (?:traffic|activity)|access denied|blocked by our security", re.I)


class MozioError(IntegrationError):
    pass


def search_link(start: str, end: str, day: date, pickup: time, passengers: int, currency: str = "EUR") -> str:
    """A 3-letter code is an airport (as the site writes it); anything else is an address or a place name."""
    def place(text: str) -> tuple[str, str]:
        text = text.strip()
        return (text.upper(), text.upper()) if re.fullmatch(r"[A-Za-z]{3}", text) else (text, text)

    (s_name, s_addr), (e_name, e_addr) = place(start), place(end)
    params = {"start_name": s_name, "start_address": s_addr, "end_name": e_name, "end_address": e_addr,
              "pickup_datetime": f"{day.strftime('%m/%d/%Y')} {pickup.strftime('%I:%M %p')}", "mode": "one_way", "num_passengers": passengers, "currency": currency}
    return f"{SITE}/v2/en-us/search?{urlencode(params)}"


class MozioClient:
    def __init__(self, session: BrowserSession, *, limiter: SiteLimiter | None = None, cache_minutes: float = 10.0, wait_seconds: float = 45.0):
        self._session = session
        self._limiter = limiter or SiteLimiter("Mozio", min_interval=5.0, max_per_hour=30)
        self._cache: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=64, track_fetch_time=True)
        self._wait = wait_seconds

    async def aclose(self) -> None:
        """The shared browser session is closed by its owner."""

    async def search(self, start: str, end: str, day: date, pickup: time, passengers: int, currency: str = "EUR") -> dict[str, Any]:
        link = search_link(start, end, day, pickup, passengers, currency)

        async def action(page) -> dict[str, Any]:
            polls: list[dict[str, Any]] = []
            statuses: list[int] = []

            async def read(response) -> None:
                if API not in response.url:
                    return
                statuses.append(response.status)
                if response.request.method == "GET":
                    try:
                        polls.append(await response.json())
                    except Exception:
                        pass

            def on_response(response) -> None:
                asyncio.ensure_future(read(response))

            page.on("response", on_response)
            try:
                await page.goto(link, wait_until="domcontentloaded", timeout=self._wait * 1000)
                waited = 0.0
                while waited < self._wait and not (polls and polls[-1].get("more_coming") is False):
                    await asyncio.sleep(1)
                    waited += 1
                    if statuses and statuses[0] >= 400:
                        break
                await asyncio.sleep(0.3)   # the last poll's body may still be arriving
                body = "" if polls else await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 2000)")
            finally:
                page.remove_listener("response", on_response)
            return {"polls": polls, "statuses": statuses, "page_text": body}

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            got = await self._session.run(SITE, "about:blank", action)
            if got["statuses"] and got["statuses"][0] in (401, 403, 429):
                raise MozioError(f"Mozio refused the search ({got['statuses'][0]}). Stopping; wait a while or check mozio.com.")
            if got["statuses"] and got["statuses"][0] >= 400:
                raise MozioError(f"Mozio's search failed ({got['statuses'][0]}). A place may not be one Mozio knows; try a clearer address or try again later.")
            if not got["polls"]:
                if _CHECK.search(got["page_text"]):
                    raise MozioError("Mozio's site showed a human check or refused the page. Stopping; check the price on mozio.com.")
                raise MozioError("Mozio's search page did not show prices in time. Try again, or check mozio.com.")
            return {"polls": got["polls"], "url": link}

        return await self._cache.get_or_load(link, load)

