"""Bank of Israel daily exchange rate: the feed parser, the HTTP client and the tool (real feed shape, 16 Oct 2026)."""

import json
from datetime import datetime, timezone

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.boi.client import BoiClient, BoiError, parse_rate
from myt_mcp.config import Settings
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

FEED = {"exchangeRates": [
    {"key": "USD", "currentExchangeRate": 3.089, "currentChange": -0.4511762810183693, "unit": 1, "lastUpdate": "2026-10-16T09:22:04.9223221Z"},
    {"key": "EUR", "currentExchangeRate": 3.4769, "currentChange": -0.05174346738724236, "unit": 1, "lastUpdate": "2026-10-16T09:22:04.9223221Z"},
    {"key": "JPY", "currentExchangeRate": 1.9557, "currentChange": -0.549, "unit": 100, "lastUpdate": "2026-10-16T09:22:04.9223221Z"},
]}
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)


def client_for(payload=FEED, status=200):
    def handler(request):
        assert request.url.path == "/PublicApi/GetExchangeRates"
        return httpx.Response(status, json=payload) if status == 200 else httpx.Response(status, text="nope")
    return BoiClient(transport=httpx.MockTransport(handler), limiter=SiteLimiter("Bank of Israel", 0, 1000))


def test_rate_per_one_unit_and_age():
    eur = parse_rate(FEED["exchangeRates"][1], NOW)
    assert eur["ils_per_unit"] == 3.4769 and eur["age_days"] == 0 and eur["published_utc"].startswith("2026-10-16T09:22")
    assert eur["change_pct_vs_previous"] == -0.052


def test_a_rate_quoted_per_100_units_is_made_per_one(monkeypatch):
    import myt_mcp.boi.client as boi
    monkeypatch.setattr(boi, "PLAUSIBLE_ILS_PER_UNIT", (0.001, 10.0))
    assert parse_rate(FEED["exchangeRates"][2], NOW)["ils_per_unit"] == 0.019557


@pytest.mark.parametrize("row", [
    {"key": "EUR", "currentExchangeRate": 34.769, "unit": 1, "lastUpdate": "2026-10-16T09:22:04Z"},       # a decimal point lost
    {"key": "EUR", "currentExchangeRate": 0.0, "unit": 1, "lastUpdate": "2026-10-16T09:22:04Z"},
    {"key": "EUR", "unit": 1, "lastUpdate": "2026-10-16T09:22:04Z"},                                       # no rate
    {"key": "EUR", "currentExchangeRate": 3.4, "unit": 1, "lastUpdate": "not a date"},
])
def test_a_broken_row_is_refused(row):
    with pytest.raises(BoiError):
        parse_rate(row, NOW)


async def test_client_reads_the_feed_and_reports_problems():
    assert set(await client_for().rates()) == {"USD", "EUR", "JPY"}
    with pytest.raises(BoiError, match="answered 503"):
        await client_for(status=503).rates()
    with pytest.raises(BoiError, match="unexpected format"):
        await client_for({"oops": []}).rates()


async def call(client, **args):
    settings = Settings()
    async with Client(create_server(settings, Services(settings, boi=client))) as c:
        return await c.call_tool("daily_exchange_rate", args)


async def test_tool_gives_the_rate_where_to_enter_it_and_changes_nothing(monkeypatch):
    import myt_mcp.tools.rates as rates
    monkeypatch.setattr(rates, "parse_rate", lambda row: parse_rate(row, NOW))
    r = await call(client_for(), currency="eur", myt_current_rate=3.53)
    d = r.structured_content
    assert not r.is_error and d["currency"] == "EUR" and d["ils_per_1"] == 3.4769 and "warning" not in d
    assert "Fixing the exchange rate" in d["enter_in_myt_at"] and "Nothing was changed in MYT" in d["prepare_only"]
    assert d["against_myt"] == {"myt_rate": 3.53, "difference": -0.0531, "difference_pct": -1.5, "note": "Positive = the bank's rate is higher than the rate in MYT."}
    assert d["checked_at"].endswith("UTC") and d["source"].startswith("Bank of Israel")


async def test_tool_warns_when_the_newest_rate_is_old():
    r = await call(client_for())            # real clock: the fixture is from 2026-10-16, so this passes only while it is within 3 days
    d = r.structured_content
    assert not r.is_error and ("warning" in d) == ((datetime.now(timezone.utc) - datetime(2026, 10, 16, 9, 22, tzinfo=timezone.utc)).days > 3)


@pytest.mark.parametrize("args,expected", [({"currency": "JPY"}, "must be one of"), ({"myt_current_rate": 99.0}, "myt_current_rate")])
async def test_tool_validates_input(args, expected):
    r = await call(client_for(), **args)
    assert r.is_error and expected in r.content[0].text
