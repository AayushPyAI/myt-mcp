"""Correct, real data: mismatched answers are refused, and every price says when it was fetched."""

import time

import pytest

from myt_mcp.cache import TTLCache
from myt_mcp.checks import DataCheckError, ensure, with_checked_at
from myt_mcp.ofran.offers import check_offers

pytestmark = pytest.mark.anyio


def test_ensure_refuses_with_the_reason():
    ensure("X", [])
    with pytest.raises(DataCheckError, match="X's answer did not match the search \\(wrong day\\). It was not used"):
        ensure("X", ["wrong day"])


def test_ofran_offer_checks():
    car = {"price": 120.5, "currency": "EUR"}
    assert check_offers([car, {**car, "price": 99}]) == []
    assert check_offers([{**car, "price": 0}]) == ["an offer has no price"]
    assert check_offers([{**car, "currency": None}]) == ["an offer has no currency"]
    assert "several currencies" in check_offers([car, {**car, "currency": "USD"}])[0]


async def test_checked_at_keeps_the_real_fetch_time_when_cached():
    cache = TTLCache(600, track_fetch_time=True)

    async def load():
        return {"price": 10}

    @with_checked_at
    async def tool():
        return dict(await cache.get_or_load("k", load))

    first = await tool()
    cache._data["k"] = (cache._data["k"][0], time.time() - 300, cache._data["k"][2])   # fetched 5 minutes ago
    second = await tool()
    assert first["checked_at"].endswith("UTC") and first["data_age_minutes"] == 0
    assert second["data_age_minutes"] == 5


async def test_lists_and_untracked_caches_get_no_stamp():
    plain = TTLCache(600)

    @with_checked_at
    async def tool():
        return {"stations": await plain.get_or_load("k", _stations)}

    assert "checked_at" not in await tool()


async def _stations():
    return ["Firenze"]


async def test_myt_must_return_the_asked_trip():
    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    from myt_mcp.services import Services

    class WrongTripMYT:
        async def get_trip_v3(self, trip_id):
            return {"trip": {"trip_id": trip_id + 1}}

        async def aclose(self):
            pass

    settings = Settings()
    async with Client(create_server(settings, Services(settings, myt=WrongTripMYT()))) as c:
        r = await c.call_tool("get_trip", {"trip_id": 276310})
    assert r.is_error and "MYT returned trip 276311 instead of 276310" in r.content[0].text


async def test_playbook_is_served_by_the_server():
    from mcp import Client

    from myt_mcp.app import INSTRUCTIONS, create_server
    from myt_mcp.config import Settings
    from myt_mcp.guide import TOPICS

    assert len(INSTRUCTIONS) < 3700 and "quote_guide" in INSTRUCTIONS
    async with Client(create_server(Settings())) as c:
        assert c.instructions == INSTRUCTIONS
        for topic in TOPICS:
            r = await c.call_tool("quote_guide", {"topic": topic})
            assert not r.is_error and r.content[0].text.startswith("## ")
        rules = await c.call_tool("quote_guide", {"topic": "rules"})
        assert rules.content[0].text.startswith("## Rules\n")


async def test_browser_retries_on_a_fresh_tab_and_explains_the_reason():
    from myt_mcp.browser import BrowserError, BrowserSession

    class Ctx:
        pages: list = []

    class Tab:
        def __init__(self, name, fail):
            self.name, self.fail, self.closed = name, fail, False
            self.context = Ctx()
            Ctx.pages = [*Ctx.pages, self]

        async def close(self):
            self.closed = True
            Ctx.pages = [p for p in Ctx.pages if p is not self]

        async def goto(self, url):
            pass

    tabs = []

    class Session(BrowserSession):
        async def page(self, origin, start_url):
            existing = next((p for p in Ctx.pages if not p.closed), None)
            tab = existing if existing and self._pages.get(origin) is existing else Tab(f"t{len(tabs)}", len(tabs) == 0)
            if tab not in tabs:
                tabs.append(tab)
            self._pages[origin] = tab
            return tab

    s = Session("http://127.0.0.1:1")
    Ctx.pages = []

    async def action(tab):
        if tab.fail:
            raise RuntimeError("Execution context was destroyed")
        return tab.name

    assert await s.run("https://x.test", "https://x.test/", action) == "t1"   # second attempt ran on a new tab
    assert tabs[0].closed is False or len(tabs) == 2

    async def always_fails(tab):
        raise RuntimeError("Page.goto: net::ERR_FAILED")

    with pytest.raises(BrowserError, match=r"stopped responding \(Page.goto: net::ERR_FAILED\)"):
        await s.run("https://x.test", "https://x.test/", always_fails)


def test_source_line_carries_age_rules():
    from myt_mcp.checks import _cite

    r = {"source": "https://x.test/", "checked_at": "2026-10-13 12:00 UTC", "data_age_minutes": 0, "age_rules": "Child ages differ."}
    assert _cite("lounge_prices", r).endswith("https://x.test/. Note: Child ages differ.")
    r.pop("age_rules")
    assert _cite("lounge_prices", r).endswith("https://x.test/")


def test_comparison_checklist_is_served_and_pointed_to():
    from myt_mcp.checks import REMINDER
    from myt_mcp.guide import sections
    text = sections()["comparison"]
    assert text.startswith("## Comparison checklist") and all(f"{n}. **" in text for n in range(1, 9))
    assert "quote_guide('comparison')" in REMINDER
