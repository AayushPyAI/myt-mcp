"""GetYourGuide activity details, read through the automation browser.

Claude's own GetYourGuide connector only draws cards in the chat (Claude gets no data from it), so this client
reads both: the search, and for one activity link what the cards do not give:

    search page (www.getyourguide.com/s/?q=...) -> the visitor id the page's own requests carry
    POST travelers-api.getyourguide.com/user-interface/landing-pages/srp/blocks
        -> one page (24) of results with the "from" price in EUR, rating, reviews, free cancellation and the day's
           availability; in GetYourGuide's popularity order, as the site's own "Show more" does

    activity page (www.getyourguide.com/<place>/<slug>-t<id>/)
        -> traveller categories and age limits, highlights, includes, cancellation sentence
    POST travelers-api.getyourguide.com/user-interface/activity-details-page/blocks?date_from=<day>
        -> the options available that day with start times, the exact group price, meeting point, cancellation
           (the same request the page makes when a date is picked; nothing is booked or held)

Plain HTTP is not used: the page's own session and headers are needed, so requests run inside the page.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date
from typing import Any
from urllib.parse import urlencode

import httpx

from myt_mcp.browser import BrowserSession
from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.gyg.parse import activity_id_from_url, activity_info, state_from_script
from myt_mcp.ratelimit import SiteLimiter

ORIGIN = "https://www.getyourguide.com"
API = "https://travelers-api.getyourguide.com/user-interface/activity-details-page/blocks"
URL_PATTERN = re.compile(r"^https://www\.getyourguide\.com/[^?#\s]*-t(\d+)/?(?:[?#].*)?$")
CONFIGURATOR = "bookingAssistantConfiguratorContentIdentifier"

READ_PAGE_JS = """() => {
    const s = [...document.scripts].find(s => s.textContent.includes('window.__INITIAL_STATE__'));
    const h1 = document.querySelector('h1');
    return {script: s ? s.textContent : null, title: h1 ? h1.innerText.trim() : null,
            body: (document.body && document.body.innerText || '').slice(0, 600).toLowerCase()};
}"""


SEARCH_PAGE_JS = """() => {
    const s = [...document.scripts].find(s => s.textContent.includes('window.__INITIAL_STATE__'));
    const m = s && s.textContent.match(/"visitorId"\\s*:\\s*"([A-Z0-9]{8,})"/);
    return {visitor_id: m ? m[1] : null, body: (document.body && document.body.innerText || '').slice(0, 600).toLowerCase()};
}"""
SRP_API = "https://travelers-api.getyourguide.com/user-interface/landing-pages/srp/blocks"
HUMAN_CHECK = re.compile(r"captcha|verify you are human|access denied|unusual traffic")


class GygError(IntegrationError):
    pass


log = logging.getLogger("myt_mcp.gyg")
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
                "Accept": "application/json", "Origin": ORIGIN, "Referer": f"{ORIGIN}/", "Accept-Language": "en-US,en;q=0.9"}


def clean_url(url: str) -> str:
    """The activity link without tracking parameters, with EUR prices requested."""
    base = url.split("?")[0].split("#")[0]
    return f"{base}?currency=EUR"


class GygClient:
    def __init__(self, session: BrowserSession, *, limiter: SiteLimiter | None = None, cache_minutes: float = 10.0,
                 http_first: bool = False, transport: httpx.AsyncBaseTransport | None = None):
        self._session = session
        self._http_first, self._transport = http_first, transport
        self._limiter = limiter or SiteLimiter("GetYourGuide", min_interval=5.0, max_per_hour=60)
        self._pages: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=32, track_fetch_time=True)
        self._answers: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=64, track_fetch_time=True)
        self._searches: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=32, track_fetch_time=True)

    async def aclose(self) -> None:
        """The shared browser session is closed by its owner."""

    async def search(self, query: str, day: date | None, pages: int) -> dict[str, Any]:
        """`pages` pages (24 results each) of GetYourGuide's own search, in its own (popularity) order.
        {"answers": [...], "stopped": reason or None}; a failure after the first page keeps what was read."""
        key = (" ".join(query.lower().split()), day.isoformat() if day else None, pages)

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            params = {"q": query.strip(), **({"date_from": day.isoformat(), "date_to": day.isoformat()} if day else {})}
            payload = {"contentIdentifier": "srp-activity-grid", "sortingSelected": "popularity", "filtersUpdated": [], "selectedSortingOrderValue": "popularity",
                       "additionalParams": {"q": query.strip(), "rawUserQuery": query.strip()}, "injectedCardsCount": 0, "templateMatcherRuleId": "search.basic",
                       **({"datesSelected": {"fromDate": day.isoformat(), "toDate": day.isoformat()}} if day else {})}
            if self._http_first:
                # the search service answers plain HTTP (only the activity pages are behind a browser check); fall back to the browser if it does not
                headers = {"accept-currency": "EUR", "visitor-platform": "desktop", "x-gyg-app-type": "Web", "visitor-id": uuid.uuid4().hex.upper()[:26]}
                try:
                    return await self._read_pages(self._http_post, f"{SRP_API}?{urlencode(params)}", payload, headers, pages)
                except IntegrationError as e:
                    log.info("GetYourGuide search over HTTP failed (%s); using the browser", e)

            async def action(page):
                try:
                    await page.goto(f"{ORIGIN}/s/?{urlencode(params)}", wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    if "ERR_HTTP_RESPONSE_CODE_FAILURE" in str(e):
                        raise GygError("GetYourGuide answered with an error page for this search.") from None
                    raise
                await page.wait_for_timeout(2500)
                return await page.evaluate(SEARCH_PAGE_JS)

            read = await self._session.run(ORIGIN, f"{ORIGIN}/", action)
            if HUMAN_CHECK.search(read.get("body") or ""):
                raise GygError("GetYourGuide showed a human check. Stopping; open the search in the browser yourself.")
            if not read.get("visitor_id"):
                raise GygError("GetYourGuide's search page had an unexpected format; the site may have changed.")
            headers = {"accept-currency": "EUR", "visitor-platform": "desktop", "x-gyg-app-type": "Web", "visitor-id": read["visitor_id"]}
            return await self._read_pages(self._browser_post, f"{SRP_API}?{urlencode(params)}", payload, headers, pages)

        return await self._searches.get_or_load(key, load)

    async def _http_post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(headers=HTTP_HEADERS, timeout=40, transport=self._transport) as http:
                r = await http.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise GygError(f"GetYourGuide could not be reached over HTTP ({type(e).__name__}).") from None
        return {"status": r.status_code, "text": r.text}

    async def _browser_post(self, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        return await self._session.fetch(ORIGIN, f"{ORIGIN}/", "POST", url, body, headers)

    async def _read_pages(self, post, url: str, payload: dict[str, Any], headers: dict[str, str], pages: int) -> dict[str, Any]:
        """Page 1..`pages` of the search; a failure after the first page keeps what was read."""
        answers: list[dict[str, Any]] = []
        for number in range(1, pages + 1):
            if number > 1:
                await self._limiter.acquire()
            try:
                answers.append(await self._srp_page(post, url, {"payload": {**payload, "page": number}}, headers))
            except IntegrationError as e:
                if number == 1:
                    raise
                return {"answers": answers, "stopped": f"page {number} could not be read ({e}); the answer covers pages 1-{number - 1}."}
            if not any(isinstance(b, dict) and b.get("type") == "loadMore" for b in answers[-1].get("content") or []):
                break   # no "Show more" after this page: it was the last one
        return {"answers": answers, "stopped": None}

    async def _srp_page(self, post, url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        r = await post(url, body, headers)
        if r["status"] in (401, 403, 429):
            raise GygError(f"GetYourGuide refused the search ({r['status']}). Stopping; wait a while or check the site.")
        if r["status"] != 200:
            raise GygError(f"GetYourGuide's search answered {r['status']}; try again later or check the site.")
        try:
            answer = json.loads(r["text"])
        except ValueError:
            raise GygError("GetYourGuide's search returned a page instead of data; the site may have changed.") from None
        if not isinstance(answer, dict) or "content" not in answer:
            raise GygError("GetYourGuide's search answer had an unexpected format; the site may have changed.")
        return answer

    async def page(self, url: str) -> dict[str, Any]:
        """Activity info (id, title, traveller categories, highlights, includes, cancellation) for a link."""
        wanted = activity_id_from_url(url)

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            target = clean_url(url)

            async def action(page):
                try:
                    await page.goto(target, wait_until="domcontentloaded", timeout=45000)
                except Exception as e:
                    if "ERR_HTTP_RESPONSE_CODE_FAILURE" in str(e):
                        raise GygError("GetYourGuide answered with an error page for this link; check the activity link.") from None
                    raise
                await page.wait_for_timeout(2500)
                return await page.evaluate(READ_PAGE_JS)

            read = await self._session.run(ORIGIN, f"{ORIGIN}/", action)
            if not read.get("script"):
                if re.search(r"captcha|verify you are human|access denied|unusual traffic", read.get("body") or ""):
                    raise GygError("GetYourGuide showed a human check. Stopping; open the activity in the browser yourself.")
                raise GygError("That GetYourGuide page has no activity data; check the link.")
            try:
                info = activity_info(state_from_script(read["script"]))
            except (ValueError, KeyError):
                raise GygError("GetYourGuide's page data had an unexpected format; the site may have changed.") from None
            info["title"] = read.get("title") or info.get("title")
            if not info["categories"]:
                raise GygError(f"GetYourGuide has no activity with id {info.get('activity_id') or wanted} (its page says "
                               f"{info['title']!r}). Use the activity link from the GetYourGuide connector; do not guess links.")
            if wanted and info.get("activity_id") != wanted:
                raise GygError(f"The page is activity {info.get('activity_id')}, not {wanted} from the link.")
            return info

        return await self._pages.get_or_load(("page", wanted), load)

    async def availability(self, url: str, info: dict[str, Any], day: date, participants: list[dict[str, int]]) -> dict[str, Any]:
        """The availability answer for one date and group (a server-driven UI tree)."""
        key = (info["activity_id"], day.isoformat(), tuple((p["categoryId"], p["count"]) for p in participants))

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            body = {
                "events": [
                    {"event": {"type": "datesSelected", "emitterId": CONFIGURATOR, "payload": {"fromDate": day.isoformat(), "isManualSelection": True}}},
                    {"event": {"type": "bookingAssistantInputsChanged", "emitterId": CONFIGURATOR,
                               "payload": {"participants": participants, "language": "", "selectedDate": day.isoformat(),
                                           "hasButtonBeenClickedWithValidForm": True}}},
                ],
                "payload": {"activityId": info["activity_id"], "templateName": "ActivityDetails", "contentIdentifier": CONFIGURATOR,
                            "participantsLanguage": "en-US", "hasButtonBeenClickedWithValidForm": False, "reviewsExperiments": []},
            }
            headers = {"accept-currency": "EUR", "visitor-platform": "desktop", "x-gyg-app-type": "Web"}
            if info.get("visitor_id"):
                headers["visitor-id"] = info["visitor_id"]
            r = await self._session.fetch(ORIGIN, f"{ORIGIN}/", "POST", f"{API}?date_from={day.isoformat()}", body, headers)
            if r["status"] in (401, 403, 429):
                raise GygError(f"GetYourGuide refused the availability check ({r['status']}). Stopping; wait a while or check the page.")
            if r["status"] != 200:
                raise GygError(f"GetYourGuide's availability check answered {r['status']}; try again later or check the page.")
            try:
                answer = json.loads(r["text"])
            except ValueError:
                raise GygError("GetYourGuide's availability check returned a page instead of data; the site may have changed.") from None
            if not isinstance(answer, dict) or "content" not in answer:
                raise GygError("GetYourGuide's availability answer had an unexpected format; the site may have changed.")
            return answer

        return await self._answers.get_or_load(key, load)
