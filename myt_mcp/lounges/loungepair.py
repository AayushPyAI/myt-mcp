"""LoungePair (loungepair.com): one-time lounge passes for many airports, read from its public pages.

Read-only, plain HTTPS, no login (checked 24 Oct 2026: 200, no challenge):

    GET  www.loungepair.com/at/<IATA>/                              -> the lounges of that airport (links)
    GET  www.loungepair.com/at/<IATA>/<lounge>/?currency=EUR        -> name, terminal, opening hours, "starts from" price, FlexiPass fee, notices

The page shows only the LOWEST price per person ("starts from"); the price for a date, time and group is inside the booking widget (not read), so
every row is a comparison, never a quote. The page's currency follows the visitor's country unless `?currency=EUR` is asked for.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from typing import Any

import httpx

from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

SITE = "https://www.loungepair.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
DAY = 24 * 3600
MAX_LOUNGES = 6
BOARDING_MINUTES = 45
_CHALLENGE = ("Just a moment", "cf-chl", "Attention Required")
_NAME = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_FROM = re.compile(r"starts from\s*(\S+?)\s*([A-Z]{3}) per person")
_FLEXI = re.compile(r"FlexiPass \(\+(\S+?)\s*([A-Z]{3})\)")
_HOURS = re.compile(r"(\d\d:\d\d - \d\d:\d\d daily|24 hours daily)")
_TERMINAL = re.compile(r"(Terminal \d+[A-Za-z]?(?:,? Concourse [A-Z])?)")
_IMPORTANT = re.compile(r"Important information\s*(.*?)\s*About this lounge", re.S)
_CHILDREN = re.compile(r"(Children under \d+ years? old can enter[^.]*\.\s*Children aged \d+ and over[^.]*\.)")


class LoungePairError(IntegrationError):
    pass


def _text(page: str) -> str:
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def parse_airport(page: str, iata: str) -> list[str]:
    """Lounge paths on an airport page, e.g. /at/LIS/lisbon-portela-airport-terminal-1-ana-airport-lounge/."""
    return list(dict.fromkeys(re.findall(rf'href="(/at/{iata}/[^"?/]+/)(?:\?[^"]*)?"', page)))[:MAX_LOUNGES]


def parse_lounge(page: str, path: str) -> dict[str, Any]:
    """What one lounge page says. A field the page does not show stays None; nothing is guessed."""
    text = _text(page)
    name = _NAME.search(page)
    price = _FROM.search(text)
    flexi = _FLEXI.search(text)
    important = _IMPORTANT.search(text)
    hours, terminal, children = _HOURS.search(text), _TERMINAL.search(text), _CHILDREN.search(text)
    notice = important.group(1).strip() if important else None
    return {
        "name": html.unescape(re.sub(r"<[^>]+>", "", name.group(1))).strip() if name else None,
        "terminal": terminal.group(1) if terminal else None,
        "opening_hours": hours.group(1) if hours else None,
        "from_price_per_person": float(price.group(1).lstrip("€$£₹").replace(",", "")) if price else None,
        "currency": price.group(2) if price else None,
        "flexipass_extra": float(flexi.group(1).lstrip("€$£₹").replace(",", "")) if flexi else None,
        "important_information": notice,
        "closed": bool(notice and re.search(r"closed", notice, re.I)),
        "children": children.group(1) if children else None,
        "url": f"{SITE}{path}",
    }


def hours_note(hours: str | None, flight_at: datetime | None) -> str | None:
    """When the flight time is known: the latest minute to leave for the gate, and whether the opening hours cover it."""
    if not flight_at:
        return None
    leave = flight_at - timedelta(minutes=BOARDING_MINUTES)
    note = f"Leave the lounge for the gate by {leave:%H:%M}, {BOARDING_MINUTES} minutes before the {flight_at:%H:%M} departure (boarding closes earlier): the usable stay is shorter than the opening hours suggest."
    window = re.match(r"(\d\d:\d\d) - (\d\d:\d\d) daily", hours or "")
    if window and not window.group(1) <= f"{leave:%H:%M}" <= window.group(2):
        note += f" The lounge is open {hours}, which does NOT cover {leave:%H:%M}."
    elif not hours:
        note += " The opening hours were not shown on the page."
    return note


def offer_row(lounge: dict[str, Any], iata: str, flight_at: datetime | None) -> dict[str, Any]:
    """A ready row for compose_answer(offers=...): pass it as it is, never multiply or reword the price (it is a per-person 'from' price)."""
    price, currency = lounge.get("from_price_per_person"), lounge.get("currency")
    hours = lounge.get("opening_hours")
    return {"group": f"{iata} lounges" + (f", flight {flight_at:%d %b %Y %H:%M}" if flight_at else ""), "source": "LoungePair",
            "name": ", ".join(x for x in (lounge.get("name"), lounge.get("terminal")) if x), "price_total": price, "currency": currency,
            "price_basis": "'from' price PER PERSON, the lowest at any date (not for this flight, not multiplied for the group)", "quotable": False,
            "supplier": "LoungePair", "link": lounge.get("url"),
            "details": {"terminal": lounge.get("terminal"), "entry_window": f"opening hours {hours}" if hours else None, "stay": None,
                        "adult_price": f"from {price:g} {currency} per person" if price is not None else None,
                        "child_price": "under 2 free; 2 and over a full pass (the page's rule)" if lounge.get("children") else None,
                        "flexipass_extra": f"{lounge['flexipass_extra']:g} {currency} per person" if lounge.get("flexipass_extra") is not None else None,
                        "notice": lounge.get("important_information")}}


class LoungePairClient:
    def __init__(self, http: httpx.AsyncClient | None = None, *, limiter: SiteLimiter | None = None, timeout: float = 25.0):
        self._http = http or httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})
        self._limiter = limiter or SiteLimiter("LoungePair", min_interval=6.0, max_per_hour=30)
        self._pages: TTLCache[list[dict[str, Any]]] = TTLCache(DAY, max_entries=64, track_fetch_time=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, url: str) -> str:
        await self._limiter.acquire()
        try:
            resp = await self._http.get(url)
        except httpx.TimeoutException:
            raise LoungePairError("LoungePair did not answer in time. Try again in a minute.") from None
        except httpx.HTTPError as e:
            raise LoungePairError(f"Could not reach LoungePair ({type(e).__name__}).") from None
        if resp.status_code in (403, 429) or any(m in resp.text[:3000] for m in _CHALLENGE):
            self._limiter.trip()
            raise LoungePairError("LoungePair showed a human check or refused the request. Stopping; try again later or check the website.")
        if resp.status_code == 404:
            return ""
        if resp.status_code >= 400:
            raise LoungePairError(f"LoungePair could not answer ({resp.status_code}).")
        return resp.text

    async def lounges(self, iata: str) -> list[dict[str, Any]]:
        iata = iata.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", iata):
            raise LoungePairError("Give the 3-letter IATA code of the airport (LIS, TLV, FCO...).")

        async def load() -> list[dict[str, Any]]:
            paths = parse_airport(await self._get(f"{SITE}/at/{iata}/"), iata)
            return [parse_lounge(await self._get(f"{SITE}{p}?currency=EUR"), p) for p in paths]

        return await self._pages.get_or_load(iata, load)
