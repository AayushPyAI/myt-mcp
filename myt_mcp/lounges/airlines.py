"""Lounge access sold by two airlines, read from their public pages (plain HTTPS, no login, checked 24 Oct 2026):

    Azores Airlines  azoresairlines.pt/en/information/before-boarding/lounges  one section per airport: "<Airport> | <IATA> <lounge> ... Prices for access to the lounge: ... - €38.00
                     Price for TOP fare - €35.00 ... Stay limited to a maximum of 3 hours. (Schedule 6:00 a.m. - 10:00 p.m.*)"
    TAP Air Portugal flytap.com/en-pl/at-the-airport/lounges  "prices starting from 28 EUR" (varies with the channel, the purchase date and the route) and the lounges TAP runs
                     ("TAP Premium Lounge Tejo Location ... Opening hours ... Capacity ... seats")

Both are airline channels: the Azores price is sold with an Azores Airlines flight booking and the TAP price with a TAP booking, so every row is a comparison (not quotable).
"""

from __future__ import annotations

import html
import re
from typing import Any

import httpx

from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

AZORES_URL = "https://azoresairlines.pt/en/information/before-boarding/lounges"
TAP_URL = "https://www.flytap.com/en-pl/at-the-airport/lounges"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127 Safari/537.36"
DAY = 24 * 3600
_CHALLENGE = ("Just a moment", "cf-chl", "Attention Required", "Access Denied", "Pardon Our Interruption")
_HEADER = re.compile(r"((?:[A-Z][A-Za-zÀ-ÿ'.\-]*\s){0,3}Airport) \| ([A-Z]{3}) ")
_NAME = re.compile(r"(.*?\bLounge\b(?: ANA)?(?: \| \w+)?)")        # the lounge's name ends at the word Lounge ("ANA Lounge", "Primeclass Lounge", "Lounge ANA | Vinci")
_MONEY = re.compile(r"€\s?(\d+(?:\.\d\d)?)")
_TAP_LOUNGE = re.compile(r"(TAP Premium Lounge[A-Za-zÀ-ÿ' \-]*?) Location (.+?) Opening hours (.+?) Capacity (.+?) seats")
_TAP_FROM = re.compile(r"prices starting from (\d+(?:[.,]\d+)?) EUR")


class AirlineLoungesError(IntegrationError):
    pass


def _text(page: str) -> str:
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def parse_azores(text: str) -> list[dict[str, Any]]:
    """One entry per airport section. A field the section does not say stays None."""
    marks = list(_HEADER.finditer(text))
    out = []
    for n, m in enumerate(marks):
        body = text[m.end(): marks[n + 1].start() if n + 1 < len(marks) else len(text)]
        body = body.lstrip("| ").strip()
        found = _NAME.match(body)
        name = (found.group(1) if found else " ".join(body.split()[:4])).strip(" |")
        prices = _MONEY.findall(body.split("Prices for access", 1)[1]) if "Prices for access" in body else []
        stay = re.search(r"maximum of (\d+) hours?", body)
        schedule = re.search(r"\(Schedule ([^)]*)\)", body)
        entry = re.search(r"Entry to the lounge is only permitted ([^ ]+) before", body)
        children = re.search(r"(Free access for children[^.]*)\.", body)
        extension = re.search(r"\*(As of .{0,260})", body)
        out.append({"airport": m.group(1), "iata": m.group(2), "lounge": name[:60], "price_website_eur": float(prices[0]) if prices else None,
                    "price_top_fare_eur": float(prices[1]) if len(prices) > 1 else None, "max_stay_hours": int(stay.group(1)) if stay else None,
                    "schedule": schedule.group(1).strip() if schedule else None, "entry_allowed_before_departure": entry.group(1) if entry else None,
                    "children": children.group(1) if children else None, "refunds": "not allowed except flight cancellation or schedule change" if "Refunds not allowed" in body else None,
                    "schedule_change": extension.group(1).strip() if extension else None, "url": AZORES_URL})
    return out


def parse_tap(text: str) -> dict[str, Any]:
    """TAP's 'from' price and the lounges TAP itself runs (the page's partner list is not read)."""
    price = _TAP_FROM.search(text)
    own, seen = [], set()
    for m in _TAP_LOUNGE.finditer(text):
        if m.group(1).strip() in seen:
            continue
        seen.add(m.group(1).strip())
        own.append({"lounge": m.group(1).strip(), "location": m.group(2).strip(), "opening_hours": m.group(3).strip(), "capacity": f"{m.group(4).strip()} seats", "url": TAP_URL})
    return {"from_price_eur": float(price.group(1).replace(",", ".")) if price else None, "own_lounges": own,
            "price_note": "Prices may vary depending on the purchase channel, the time of advance purchase, the trip date, and the origin and destination (TAP's own words)." if price else None}


# the words TAP's own lounge entries use for a place: IATA code -> a word in their "Location" text
TAP_PLACE = {"LIS": "Lisbon", "ORY": "Orly"}


def azores_rows(sections: list[dict[str, Any]], iata: str) -> list[dict[str, Any]]:
    return [s for s in sections if s["iata"] == iata]


def tap_rows(data: dict[str, Any], iata: str) -> list[dict[str, Any]]:
    word = TAP_PLACE.get(iata)
    return [l for l in data["own_lounges"] if word and word.lower() in f"{l['location']} {l['lounge']}".lower()]


def offer_azores(row: dict[str, Any], iata: str) -> dict[str, Any]:
    price = row["price_website_eur"]
    return {"group": f"{iata} lounges", "source": "Azores Airlines", "name": f"{row['lounge']} ({row['airport']})", "price_total": price, "currency": "EUR",
            "price_basis": "per person, Azores Airlines' own price for lounge access sold with an Azores Airlines flight booking (not a price for a TAP ticket, not multiplied for the group)",
            "quotable": False, "supplier": "Azores Airlines", "link": row["url"],
            "details": {"terminal": None, "entry_window": ((f"entry only {row['entry_allowed_before_departure']} before departure; schedule {row['schedule']}" if row["entry_allowed_before_departure"] else row["schedule"]) or "")
                        + (" (the page says the hours change from 1 January 2026: see notice)" if row["schedule_change"] else "") or None,
                        "stay": f"maximum {row['max_stay_hours']} hours" if row["max_stay_hours"] else None,
                        "adult_price": f"{price:g} EUR per person" + (f" ({row['price_top_fare_eur']:g} EUR with a TOP fare)" if row["price_top_fare_eur"] else "") if price is not None else None,
                        "child_price": row["children"], "refund_change": row["refunds"], "notice": row["schedule_change"]}}


def offer_tap(row: dict[str, Any], iata: str, from_price: float | None) -> dict[str, Any]:
    return {"group": f"{iata} lounges", "source": "TAP Air Portugal", "name": f"{row['lounge']} ({row['location']})", "price_total": from_price, "currency": "EUR" if from_price is not None else None,
            "price_basis": "'from' price per person, TAP's own words: it varies with the channel, the purchase date, the trip date and the route (not multiplied for the group)",
            "quotable": False, "supplier": "TAP Air Portugal", "link": row["url"],
            "details": {"terminal": row["location"], "entry_window": f"opening hours {row['opening_hours']}", "stay": None,
                        "adult_price": f"from {from_price:g} EUR per person" if from_price is not None else None, "child_price": None, "capacity": row["capacity"]}}


class AirlineLoungesClient:
    def __init__(self, http: httpx.AsyncClient | None = None, *, limiter: SiteLimiter | None = None, timeout: float = 30.0):
        self._http = http or httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA})
        self._limiter = limiter or SiteLimiter("Airline lounge pages", min_interval=6.0, max_per_hour=20)
        self._pages: TTLCache[Any] = TTLCache(DAY, max_entries=8, track_fetch_time=True)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, url: str, who: str) -> str:
        await self._limiter.acquire()
        try:
            resp = await self._http.get(url)
        except httpx.TimeoutException:
            raise AirlineLoungesError(f"{who} did not answer in time. Try again in a minute.") from None
        except httpx.HTTPError as e:
            raise AirlineLoungesError(f"Could not reach {who} ({type(e).__name__}).") from None
        if resp.status_code in (403, 429) or any(m in resp.text[:3000] for m in _CHALLENGE):
            self._limiter.trip()
            raise AirlineLoungesError(f"{who} showed a human check or refused the request. Stopping; try again later or check the website.")
        if resp.status_code >= 400:
            raise AirlineLoungesError(f"{who} could not answer ({resp.status_code}).")
        return _text(resp.text)

    async def azores(self) -> list[dict[str, Any]]:
        async def load() -> list[dict[str, Any]]:
            sections = parse_azores(await self._get(AZORES_URL, "Azores Airlines"))
            if not sections:
                raise AirlineLoungesError("Could not read the Azores Airlines lounge sections; the page may have changed.")
            return sections

        return await self._pages.get_or_load("azores", load)

    async def tap(self) -> dict[str, Any]:
        async def load() -> dict[str, Any]:
            data = parse_tap(await self._get(TAP_URL, "TAP Air Portugal"))
            if data["from_price_eur"] is None and not data["own_lounges"]:
                raise AirlineLoungesError("Could not read the TAP lounge page; it may have changed.")
            return data

        return await self._pages.get_or_load("tap", load)
