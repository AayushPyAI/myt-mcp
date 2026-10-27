"""Exchange rates to euro: the Bank of Israel representative rates crossed, with a believable band and no guessing."""

import httpx
import pytest

import myt_mcp.fx as fx
from myt_mcp.boi.client import BoiClient
from myt_mcp.ratelimit import SiteLimiter


def _feed(rows):
    def handler(request):
        return httpx.Response(200, json={"exchangeRates": rows})
    return BoiClient(transport=httpx.MockTransport(handler), limiter=SiteLimiter("test", min_interval=0, max_per_hour=100))


def _row(key, rate, unit=1):
    return {"key": key, "currentExchangeRate": rate, "currentChange": 0.1, "unit": unit, "lastUpdate": "2026-10-26T08:00:00.0000000"}


@pytest.mark.anyio
async def test_the_cross_rates_are_the_shekel_rates_divided_and_the_shekel_is_inverted(monkeypatch):
    monkeypatch.setattr(fx, "_client", _feed([_row("EUR", 3.5), _row("USD", 3.1), _row("GBP", 4.0), _row("CHF", 3.75)]))
    out = await fx.eur_factors()
    assert out["factors"] == {"USD": round(3.1 / 3.5, 6), "GBP": round(4.0 / 3.5, 6), "CHF": round(3.75 / 3.5, 6), "ILS": round(1 / 3.5, 6)}
    assert out["date"] == "2026-10-26" and out["source"] == "Bank of Israel representative rates" and out["age_days"] >= 0


@pytest.mark.anyio
async def test_a_cross_rate_outside_the_believable_band_or_a_missing_row_gives_no_rate_for_that_currency(monkeypatch):
    monkeypatch.setattr(fx, "_client", _feed([_row("EUR", 3.5), _row("USD", 3.1), _row("GBP", 9.9)]))      # 9.9 shekel is a plausible quote, but 9.9 / 3.5 euro per pound is not
    out = await fx.eur_factors()
    assert "USD" in out["factors"] and "GBP" not in out["factors"] and "CHF" not in out["factors"]


@pytest.mark.anyio
async def test_no_euro_row_an_unreachable_feed_or_a_broken_format_gives_no_rates_at_all(monkeypatch):
    monkeypatch.setattr(fx, "_client", _feed([_row("USD", 3.1)]))
    assert await fx.eur_factors() is None
    down = BoiClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)), limiter=SiteLimiter("test", min_interval=0, max_per_hour=100))
    monkeypatch.setattr(fx, "_client", down)
    assert await fx.eur_factors() is None
    broken = BoiClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"nope": 1})), limiter=SiteLimiter("test", min_interval=0, max_per_hour=100))
    monkeypatch.setattr(fx, "_client", broken)
    assert await fx.eur_factors() is None
