"""Exchange rates TO EURO for a price a website shows in another currency (27 Oct 2026: Europcar prices an Israeli driver in dollars).

The server converts, never the assistant: a recipe tool fetches this table when it issues the recipe and carries it in the run's wishes (`wishes["fx"]`), the site's converter applies it, and the
row says what it did ("converted from USD 86.50 at 1 USD = 0.8885 EUR, Bank of Israel representative rates of 2026-10-26"). The rate is the Bank of Israel's representative rate of each currency
in shekel (the same feed as `daily_exchange_rate`), crossed: USD to EUR = (shekel per USD) / (shekel per EUR). A cross rate outside the believable band, a missing row or an unreachable feed gives NO
rate for that currency: the rows then stay in their own currency and `compose` shows them without comparing (no conversion without a rate).
"""

from __future__ import annotations

from typing import Any

from myt_mcp.boi.client import BoiClient, parse_rate

SOURCE = "Bank of Israel representative rates"
CROSS_BAND = (0.5, 1.6)        # euro per USD, GBP or CHF has stayed inside this for years; outside it the feed is broken, not the market
CURRENCIES = ("USD", "GBP", "CHF")
_client: BoiClient | None = None


def _boi() -> BoiClient:
    global _client
    if _client is None:
        _client = BoiClient()
    return _client


async def eur_factors() -> dict[str, Any] | None:
    """{"factors": {"USD": euro per 1 USD, ...}, "date": "YYYY-MM-DD", "age_days": n, "source": ...}, or None when the bank's feed gives no usable euro rate."""
    try:
        rows = await _boi().rates()
        euro = parse_rate(rows["EUR"])
    except Exception:           # any failure of the feed: no rate, never a guess
        return None
    factors: dict[str, float] = {}
    for code in CURRENCIES:
        if code not in rows:
            continue
        try:
            row = parse_rate(rows[code])
        except Exception:
            continue
        factor = row["ils_per_unit"] / euro["ils_per_unit"]
        if CROSS_BAND[0] <= factor <= CROSS_BAND[1]:
            factors[code] = round(factor, 6)
    shekel = 1 / euro["ils_per_unit"]
    if 0.1 <= shekel <= 1.0:
        factors["ILS"] = round(shekel, 6)
    if not factors:
        return None
    return {"factors": factors, "date": euro["published_utc"][:10], "age_days": euro["age_days"], "source": SOURCE}


def to_eur(total: float, currency: str, fx: dict[str, Any] | None) -> tuple[float, str, float | None]:
    """(price, currency, factor): a price in another currency converted with the table's factor (rounded to cents), or unchanged with factor None when there is no rate for it. A euro price is never touched."""
    factor = ((fx or {}).get("factors") or {}).get(currency) if currency != "EUR" else None
    return (round(total * factor, 2), "EUR", factor) if factor else (total, currency, None)


def basis_note(currency: str, total: float, factor: float, fx: dict[str, Any]) -> str:
    """The sentence a converted row carries in its price basis: the original price, the rate and where and when it is from."""
    return f"converted from {currency} {total:,.2f} at 1 {currency} = {factor:.4f} EUR ({fx.get('source')}, {fx.get('date')})"
