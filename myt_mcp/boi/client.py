"""Bank of Israel representative exchange rates over plain HTTP (the bank's own public feed, no key, no login):

    GET https://boi.org.il/PublicApi/GetExchangeRates
        -> {"exchangeRates": [{"key": "EUR", "currentExchangeRate": 3.4769, "currentChange": -0.05, "unit": 1, "lastUpdate": "..."}, ...]}

The rate is "shekel per `unit` of the currency". The bank publishes one per business day. Bank Hapoalim's exchange-rate page shows the same
number in its "Yatzig" (representative) column (checked 17 Oct 2026: EUR 3.47690 and USD 3.08900, equal to this feed).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from myt_mcp.cache import TTLCache
from myt_mcp.errors import IntegrationError
from myt_mcp.ratelimit import SiteLimiter

URL = "https://boi.org.il/PublicApi/GetExchangeRates"
PAGE = "https://www.boi.org.il/en/economic-roles/financial-markets/exchange-rates/"
PLAUSIBLE_ILS_PER_UNIT = (1.0, 10.0)      # a rate outside this is a broken feed, not a market move (EUR, USD, GBP, CHF are all inside)


class BoiError(IntegrationError):
    pass


class BoiClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, limiter: SiteLimiter | None = None, cache_minutes: float = 15.0):
        self._transport = transport
        self._limiter = limiter or SiteLimiter("Bank of Israel", min_interval=5.0, max_per_hour=30)
        self._cache: TTLCache[dict[str, Any]] = TTLCache(cache_minutes * 60, max_entries=4, track_fetch_time=True)

    async def aclose(self) -> None:
        """Every request opens and closes its own connection."""

    async def rates(self) -> dict[str, dict[str, Any]]:
        """{"EUR": {...}, "USD": {...}}: the feed's rows by currency code."""

        async def load() -> dict[str, Any]:
            await self._limiter.acquire()
            try:
                async with httpx.AsyncClient(timeout=20, transport=self._transport, headers={"Accept": "application/json"}) as http:
                    r = await http.get(URL)
            except httpx.HTTPError as e:
                raise BoiError(f"The Bank of Israel feed could not be reached ({type(e).__name__}); try again later or read the rate on {PAGE}.") from None
            if r.status_code != 200:
                raise BoiError(f"The Bank of Israel feed answered {r.status_code}; try again later or read the rate on {PAGE}.")
            try:
                rows = r.json()["exchangeRates"]
                return {row["key"]: row for row in rows if isinstance(row, dict) and row.get("key")}
            except (ValueError, KeyError, TypeError):
                raise BoiError("The Bank of Israel feed returned an unexpected format; the feed may have changed. Read the rate on the bank's page.") from None

        return await self._cache.get_or_load("rates", load)


def parse_rate(row: dict[str, Any], today: datetime | None = None) -> dict[str, Any]:
    """One currency row -> shekel per ONE unit of the currency, with the publication time and a staleness check."""
    try:
        raw, unit = float(row["currentExchangeRate"]), float(row.get("unit") or 1)
        published = datetime.fromisoformat(str(row["lastUpdate"])[:19]).replace(tzinfo=timezone.utc)      # the feed writes UTC with 7 fraction digits
    except (KeyError, TypeError, ValueError):
        raise BoiError(f"The Bank of Israel row for {row.get('key')!r} is missing its rate or its date.") from None
    per_unit = raw / unit
    low, high = PLAUSIBLE_ILS_PER_UNIT
    if unit <= 0 or not low <= per_unit <= high:
        raise BoiError(f"The Bank of Israel rate for {row.get('key')} ({per_unit:.4f} shekel) is outside the believable range {low}-{high}; it was not used.")
    now = today or datetime.now(timezone.utc)
    return {"ils_per_unit": round(per_unit, 6), "published_utc": published.isoformat(timespec="minutes"), "age_days": (now - published).days,
            "change_pct_vs_previous": round(float(row["currentChange"]), 3) if row.get("currentChange") is not None else None, "unit_quoted": unit, "rate_as_quoted": raw}
