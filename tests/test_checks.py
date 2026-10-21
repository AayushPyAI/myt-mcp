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
        info = c.server_info                                   # the icon and title a client may show for the connector
        assert info.title and info.website_url and [i.src for i in info.icons or []] and all(i.src.startswith("https://") for i in info.icons)
        for topic in TOPICS:
            r = await c.call_tool("quote_guide", {"topic": topic})
            assert not r.is_error and r.content[0].text.startswith("## ")
        rules = await c.call_tool("quote_guide", {"topic": "rules"})
        assert rules.content[0].text.startswith("## Rules\n")


async def test_capabilities_answer_the_can_you_questions_and_normal_queries_still_point_to_the_playbook():
    from mcp import Client

    from myt_mcp.app import INSTRUCTIONS, create_server
    from myt_mcp.config import Settings

    async with Client(create_server(Settings())) as c:
        text = (await c.call_tool("quote_guide", {"topic": "capabilities"})).content[0].text
    assert text.startswith("## What this connector can and cannot do")
    for fact in ("Screen only", "ChangeTripStatus", "Not tested. Do not offer it", "Margin Prices", "Never", "ALLOWED_TRIP_IDS"):
        assert fact in text, fact
    assert "connector_capabilities" in INSTRUCTIONS                          # the "can you ... in MYT?" route
    for normal in ('quote_guide("workflow")', "hotel_prices", "find_trip first", "calculate_quote"):
        assert normal in INSTRUCTIONS, normal                                  # the normal quote route is untouched


async def test_no_hallucination_rules_cover_claims_not_only_prices():
    from myt_mcp.app import INSTRUCTIONS
    from myt_mcp.guide import sections

    text = sections()["correct_data"]
    for rule in ("Never say \"done\" before you have read it back", "Statements about MYT screens", "No general knowledge as facts",
                 "Always name the trip", "\"I don't know\" and \"not available\" are correct answers", "Quote what you read"):
        assert rule in text, rule
    assert "never say \"done\" before reading it back" in INSTRUCTIONS


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


async def test_connector_capabilities_tool_answers_the_can_you_questions():
    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    async with Client(create_server(Settings())) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert "connector_capabilities" in tools and "CALL THIS FIRST" in tools["connector_capabilities"].description
        assert tools["connector_capabilities"].annotations.read_only_hint
        text = (await c.call_tool("connector_capabilities", {})).content[0].text
    assert "Screen only" in text and "Not tested. Do not offer it" in text and "ChangeTripStatus" in text


def test_quote_comes_after_itinerary_and_supplier_reservations():
    from myt_mcp.app import INSTRUCTIONS
    from myt_mcp.guide import sections

    text = sections()["workflow"]
    assert "Step 0" in text and "BEFORE the quote" in text and "Our job is step (d) only" in text
    assert "supplier reservations" in INSTRUCTIONS and "BEFORE the" in INSTRUCTIONS


def test_skyscanner_shows_best_and_cheapest_together_and_asks_the_rest_once():
    from myt_mcp.guide import sections

    text = "\n".join(sections().values())
    for rule in ("Best** tab and its **Cheapest** tab together", "Skyscanner's Best", "Ask the operator ONCE", "Want to see more"):
        assert rule in text, rule


def test_flights_say_sources_checked_never_assume_adults_and_skip_israir_for_portugal():
    from myt_mcp.guide import sections

    flights, other, correct = sections()["flights"], sections()["other_sources"], sections()["correct_data"]
    assert flights.startswith("## Flights: which sources to use")
    for rule in ("Sources checked: ... | Not checked", "do not call it for those legs", "Never write \"all adults\"", "always read Skyscanner too"):
        assert rule in flights, rule
    assert "Skyscanner, El Al, ITA Airways" not in other and "NOT in this list" in other
    assert "Travellers' ages are not in MYT" in correct


def test_every_price_answer_starts_with_sources_checked():
    from myt_mcp.guide import sections

    text = sections()["answer_format"]
    assert "First line of EVERY price answer" in text and "Sources checked: ... | Not checked" in text
    for need in ("hotels", "cars", "flights", "trains", "transfers", "activities", "airport lounges"):
        assert f"**{need}**" in text, need
    assert "Never skip a source silently" in text


def test_sources_checked_line_is_in_the_core_instructions_every_chat_gets():
    from myt_mcp.app import INSTRUCTIONS

    assert "Sources checked: ... | Not checked: ... (why)" in INSTRUCTIONS and len(INSTRUCTIONS) < 3700


def test_read_every_source_and_reasons_come_from_a_source_in_every_category():
    from myt_mcp.app import INSTRUCTIONS
    from myt_mcp.guide import sections

    text = sections()["answer_format"]
    assert "Read every source, ask nothing first" in text and "never answer \"say the word and I will pull it\"" in text
    assert "Reasons only from a source" in text and "my judgement, not from a source" in text
    assert "without asking" in INSTRUCTIONS and "reasons only from a tool" in INSTRUCTIONS and len(INSTRUCTIONS) < 3700


def test_filters_are_always_applied_but_only_with_a_source_and_the_same_on_every_site():
    from myt_mcp.guide import sections

    text = sections()["answer_format"]
    for rule in ("Same filters on every site, and only filters with a source", "Never add a filter that comes from neither",
                 "Most flexible = look at every fare", "ends with the link of every source", "you check yourself, never \"say the word\""):
        assert rule in text, rule
    assert "Always apply filters, never read an unfiltered list" in sections()["filters"]


def test_source_data_lists_the_fields_to_read_from_every_source():
    from myt_mcp.guide import TOPICS, sections

    assert "source_data" in TOPICS
    text = sections()["source_data"]
    assert text.startswith("## What to read from each source")
    for source in ("Hotels", "Cars", "Flights", "Trains", "Transfers", "Activities", "Lounges"):
        assert f"**{source}**" in text, source
    for field in ("cancellation", "bed type", "excess and insurance", "whole fare ladder", "not shown", "not read"):
        assert field in text, field
    assert "quote_guide(\"source_data\")" in sections()["answer_format"]


def test_transfer_rules_and_source_data_are_pointed_to_from_the_core_instructions():
    from myt_mcp.app import INSTRUCTIONS
    from myt_mcp.guide import sections

    assert '("source_data")' in INSTRUCTIONS and len(INSTRUCTIONS) < 3700
    text = sections()["transfers"]
    for rule in ("Rules for every transfer answer", "SAME time on RateHawk, Mozio and Kiwitaxi", "pickup_time_was_default",
                 "not \"N adults\"", "same capacity", "showing the cheapest N of M read", "known pattern"):
        assert rule in text, rule


def test_links_for_every_source_open_the_quotation_and_same_filter_everywhere():
    from myt_mcp.guide import sections

    text = sections()["answer_format"]
    for rule in ("Last line = a URL for every source", "A site name with a time but no URL does not count",
                 "open the quotation yourself", "never a reason", "same on every source", "Show connecting flights only when the operator asks"):
        assert rule in text, rule


def test_car_rules_pickup_time_filter_sources_fields_and_supplier_check():
    from myt_mcp.guide import sections

    text = sections()["cars"]
    for rule in ("Rules for every car answer", "10:00 is not a default", "Filters used, each with its source", "Same filters on both sites",
                 "the rental company", "\"In MYT supplier?\"", "open the detail page of the cheapest"):
        assert rule in text, rule
