"""Aspire Lounges (Swissport): lounges per airport and their live prices, from the JSON service the website uses.

Read-only: only the "which lounges" pages and the price check are called, never the booking or payment calls.

    GET  www.aspirelounges.com/airports/<airport>/                 -> the lounges at that airport (links)
    GET  www.aspirelounges.com/airport-lounges/<lounge>/           -> lounge id, name (with IATA code), description
    POST eqtr-api-live.aspirelounges.com/api/availability/rates    -> entry/exit time and ticket prices for a flight time

The site is behind Cloudflare, so when the automation browser is configured requests go through it
(BrowserTransport); otherwise plain HTTPS (HttpTransport). A human check stops the request either way.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

import httpx

from myt_mcp.browser import BrowserSession
from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

SITE = "https://www.aspirelounges.com"
API = "https://eqtr-api-live.aspirelounges.com"
RETRY_WAIT_SECONDS = 6.0
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
DAY = 24 * 3600

_AIRPORT_LINK = re.compile(r"/airports/([a-z0-9\-]+)/")
_LOUNGE_LINK = re.compile(r"/airport-lounges/([a-z0-9\-]+)/")
_LOUNGE_ID = re.compile(r"loungeID:\s*'(\d+)'")
_TITLE = re.compile(r"<title>\s*(?:Aspire Lounges \|\s*)?(.*?)\s*</title>", re.S)
_IATA = re.compile(r"\(([A-Z]{3})\)")
_DESCRIPTION = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.I)
_CHALLENGE = ("Just a moment", "cf-chl", "Attention Required")


class AspireError(IntegrationError):
    pass


@dataclass
class Reply:
    status: int
    text: str


class Transport(Protocol):
    async def send(self, method: str, url: str, body: dict[str, Any] | None = None) -> Reply: ...

    async def aclose(self) -> None: ...


class HttpTransport:
    def __init__(self, http: httpx.AsyncClient | None = None, timeout: float = 30.0):
        self._http = http or httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})

    async def send(self, method: str, url: str, body: dict[str, Any] | None = None) -> Reply:
        try:
            resp = await self._http.request(method, url, json=body, headers={"Accept": "application/json"} if body else None)
        except httpx.TimeoutException:
            raise AspireError("Aspire Lounges did not answer in time. Try again in a minute.") from None
        except httpx.HTTPError as e:
            raise AspireError(f"Could not reach Aspire Lounges ({type(e).__name__}).") from None
        return Reply(resp.status_code, resp.text)

    async def aclose(self) -> None:
        await self._http.aclose()


class BrowserTransport:
    """fetch() from an aspirelounges.com tab in the automation browser (the website calls its API the same way)."""

    def __init__(self, session: BrowserSession):
        self._session = session

    async def send(self, method: str, url: str, body: dict[str, Any] | None = None) -> Reply:
        r = await self._session.fetch(SITE, f"{SITE}/", method, url, body)
        return Reply(r["status"], r["text"])

    async def aclose(self) -> None:
        """The shared browser session is closed by its owner."""


class FallbackTransport:
    """Plain HTTP first (the website's own API answers it); the automation browser only when HTTP fails or is refused."""

    def __init__(self, primary: Transport, fallback: Transport):
        self._primary, self._fallback = primary, fallback

    async def send(self, method: str, url: str, body: dict[str, Any] | None = None) -> Reply:
        try:
            reply = await self._primary.send(method, url, body)
            if reply.status not in (401, 403, 429) and reply.status < 500:
                return reply
        except IntegrationError:
            pass
        return await self._fallback.send(method, url, body)

    async def aclose(self) -> None:
        await self._primary.aclose()
        await self._fallback.aclose()


class AspireClient:
    def __init__(self, transport: Transport | None = None, *, limiter: SiteLimiter | None = None, cache_minutes: float = 10.0):
        self._transport = transport or HttpTransport()
        self._limiter = limiter or SiteLimiter("Aspire", min_interval=5.0, max_per_hour=40)
        self._pages: TTLCache[Any] = TTLCache(DAY, max_entries=128)          # airport list, lounge pages
        self._rates: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=128, track_fetch_time=True)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def _send(self, method: str, url: str, body: dict[str, Any] | None = None) -> Reply:
        resp = None
        for attempt in (1, 2):
            await self._limiter.acquire()
            try:
                resp = await self._transport.send(method, url, body)
                break
            except IntegrationError as e:
                if "failed in the browser" not in str(e):
                    raise
                if attempt == 1:   # the connection dropped or was refused: one more try after a pause
                    await asyncio.sleep(RETRY_WAIT_SECONDS)
                    continue
                raise AspireError("Aspire did not answer the price request (the connection was refused or dropped). This is often "
                                  "temporary: try again in a minute, or check the price on the Aspire website. The reason is not "
                                  "known, so do not guess one and do not estimate a price.") from None
        if resp.status in (403, 429) or any(m in resp.text[:3000] for m in _CHALLENGE):
            self._limiter.trip()
            raise AspireError("Aspire Lounges showed a human check or refused the request. Stopping; try again later or check on the website.")
        if resp.status >= 400:
            raise AspireError(f"Aspire Lounges could not answer ({resp.status}).")
        return resp

    async def airports(self) -> list[str]:
        """Airport page names, e.g. 'tel-aviv-ben-gurion-airport'."""
        async def load() -> list[str]:
            text = (await self._send("GET", f"{SITE}/")).text
            slugs = sorted(set(_AIRPORT_LINK.findall(text)))
            if not slugs:
                raise AspireError("Could not read the list of Aspire airports; the website may have changed.")
            return slugs

        return await self._pages.get_or_load("airports", load)

    async def lounges(self, airport: str) -> list[dict[str, Any]]:
        """The Aspire lounges at one airport: id, name, airport code, description, link."""
        async def load() -> list[dict[str, Any]]:
            text = (await self._send("GET", f"{SITE}/airports/{airport}/")).text
            found = []
            for slug in sorted(set(_LOUNGE_LINK.findall(text))):
                page = (await self._send("GET", f"{SITE}/airport-lounges/{slug}/")).text
                lounge_id = _LOUNGE_ID.search(page)
                if not lounge_id:
                    continue
                title = html.unescape((_TITLE.search(page) or [None, slug])[1])
                iata = _IATA.search(title)
                description = _DESCRIPTION.search(page)
                found.append({
                    "lounge_id": int(lounge_id[1]),
                    "name": title,
                    "airport_code": iata[1] if iata else None,
                    "description": html.unescape(description[1]) if description else None,
                    "url": f"{SITE}/airport-lounges/{slug}/",
                })
            return found

        return await self._pages.get_or_load(("lounges", airport), load)

    async def rates(self, lounge_id: int, flight_time: datetime) -> dict[str, Any]:
        """Lounge entry/exit time and ticket prices (EUR) for a flight leaving at `flight_time` (local time)."""
        body = {"ArrivalDate": flight_time.strftime("%Y-%m-%dT%H:%M:00"), "Terminal": "-1", "LoungeId": str(lounge_id),
                "LanguageCode": "en", "Currency": "EUR", "affiliateKey": ""}

        async def load() -> dict[str, Any]:
            resp = await self._send("POST", f"{API}/api/availability/rates", body)
            try:
                data = json.loads(resp.text)
            except ValueError:
                raise AspireError("Aspire's price check returned a page instead of data; the site may have changed.") from None
            if not isinstance(data, dict):
                raise AspireError("Aspire's price check had an unexpected format.")
            return data

        return await self._rates.get_or_load((lounge_id, body["ArrivalDate"]), load)
