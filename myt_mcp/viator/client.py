"""Viator activity search and details, read from viator.com pages in the automation browser.

Plain HTTP is blocked by Viator's bot protection (DataDome), so pages are opened in the shared
automation Chrome (myt_mcp.browser). Every page embeds its data as JSON (<script id="globalState">);
we read that instead of the visible HTML. Prices follow the browser's Viator currency (set to EUR once).

    /searchResults/all?text=...                      -> search results
    /tours/<dest>/<slug>/d<id>-<code>                -> one activity (options, meeting point, policies)
    /orion/ajax/react/product-price-calendar/<code>  -> bookable dates with their cheapest price
    POST /orion/ajax/product-availability            -> exact price and start times for a date and group
                                                        (the same check as the page's "Check Availability";
                                                        nothing is booked or held)
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from urllib.parse import quote

from myt_mcp.browser import BrowserSession
from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

ORIGIN = "https://www.viator.com"
AVAILABILITY_PATH = "/orion/ajax/product-availability"

READ_STATE_JS = """() => {
    const el = document.getElementById('globalState');
    const body = (document.body && document.body.innerText || '').slice(0, 600).toLowerCase();
    const urls = {};
    document.querySelectorAll('a[href*="/tours/"]').forEach(a => {
        const m = a.href.match(/\\/d\\d+-([A-Za-z0-9_.]+)(?:[\\/?#]|$)/);
        if (m && !urls[m[1]]) urls[m[1]] = a.href.split('?')[0];
    });
    const cur = [...document.querySelectorAll('button[aria-label^="Currency"]')].map(b => b.innerText.trim())[0] || null;
    return {state: el ? el.textContent : null, urls, currency: cur, blocked: /captcha|verify you are human|access denied/.test(body)};
}"""


class ViatorError(IntegrationError):
    pass


class ViatorClient:
    def __init__(self, session: BrowserSession, *, limiter: SiteLimiter | None = None, cache_minutes: float = 10.0):
        self._session = session
        self._limiter = limiter or SiteLimiter("Viator", min_interval=5.0, max_per_hour=60)
        self._cache: TTLCache[Any] = TTLCache(cache_minutes * 60, max_entries=64, track_fetch_time=True)

    async def aclose(self) -> None:
        """The shared browser session is closed by its owner."""

    async def _open(self, url: str) -> dict[str, Any]:
        await self._limiter.acquire()

        async def action(page):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                if "ERR_HTTP_RESPONSE_CODE_FAILURE" in str(e):
                    raise ViatorError("Viator answered with an error page for this request (it may not accept this search text "
                                      "or this link). Try other words.") from None
                raise
            await page.wait_for_timeout(1500)
            return await page.evaluate(READ_STATE_JS)

        result = await self._session.run(ORIGIN, f"{ORIGIN}/", action)
        if result.get("blocked") or not result.get("state"):
            raise ViatorError("Viator showed a human check (captcha) or an empty page. Stopping; open viator.com in the automation browser, "
                              "complete the check if there is one, and try again later.")
        try:
            result["state"] = json.loads(result["state"])
        except ValueError:
            raise ViatorError("Viator's page data had an unexpected format; the site may have changed.") from None
        return result

    async def search(self, text: str, page: int = 1) -> dict[str, Any]:
        """One page (24 results) of a search; page 2 and on use Viator's own paging URL /searchResults/all/<n>."""
        url = f"{ORIGIN}/searchResults/all{'' if page == 1 else f'/{page}'}?text={quote(text.strip())}"
        return await self._cache.get_or_load(("search", text.strip().lower(), page), lambda: self._open(url))

    async def product(self, url: str) -> dict[str, Any]:
        """Activity page data plus its price calendar (bookable dates)."""

        async def load() -> dict[str, Any]:
            page = await self._open(url)
            product = (((page["state"].get("__PRELOADED_DATA__") or {}).get("pageModel") or {}).get("product")) or {}
            code = product.get("productCode")
            if not code:
                raise ViatorError("That Viator page has no activity data; check the link.")
            await self._limiter.acquire()
            cal = await self._session.fetch(ORIGIN, f"{ORIGIN}/", "GET", f"/orion/ajax/react/product-price-calendar/{code}")
            calendar: dict[str, Any] = {}
            if cal["status"] == 200:
                try:
                    calendar = json.loads(cal["text"])
                except ValueError:
                    calendar = {}
            return {"product": product, "calendar": calendar, "currency": page.get("currency"), "csrf": _csrf(page["state"])}

        return await self._cache.get_or_load(("product", url.split("?")[0]), load)

    async def check_availability(self, url: str, day: date, bands: dict[str, int]) -> dict[str, Any]:
        """Viator's own availability check for one date and group (exact options, start times and prices)."""
        key = ("check", url.split("?")[0], day.isoformat(), tuple(sorted(bands.items())))

        async def load() -> dict[str, Any]:
            data = await self.product(url)
            body = {"productCode": data["product"]["productCode"], "searchDate": day.isoformat(),
                    "ageBands": {band: str(n) for band, n in bands.items()}}
            csrf = data.get("csrf")
            for attempt in range(2):
                await self._limiter.acquire()
                r = await self._session.fetch(ORIGIN, f"{ORIGIN}/", "POST", AVAILABILITY_PATH, body, _headers(csrf))
                if r["status"] != 403 or attempt:
                    break
                csrf = _csrf((await self._open(url))["state"])   # the page's security token expired: reload once
            if r["status"] != 200:
                raise ViatorError(f"Viator's availability check answered {r['status']}; try again later or check on the page.")
            try:
                answer = json.loads(r["text"])
            except ValueError:
                raise ViatorError("Viator's availability check returned a page instead of data.") from None
            errors = answer.get("validationErrors")
            if errors:
                raise ViatorError(f"Viator did not accept this check: {json.dumps(errors)[:300]}")
            return answer

        return await self._cache.get_or_load(key, load)


def _csrf(state: dict[str, Any]) -> dict[str, Any]:
    return (state.get("__PRELOADED_DATA__") or {}).get("csrf") or {}


def _headers(csrf: dict[str, Any]) -> dict[str, str]:
    """The headers Viator's own page sends with its requests."""
    headers = {"X-Requested-With": "XMLHttpRequest"}
    if csrf.get("headerName") and csrf.get("token"):
        headers[csrf["headerName"]] = csrf["token"]
    return headers
