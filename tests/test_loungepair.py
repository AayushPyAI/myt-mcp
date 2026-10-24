"""LoungePair: lounge pages read over plain HTTPS (patterns taken from the real pages of 24 Oct 2026)."""

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.lounges.loungepair import LoungePairClient, LoungePairError, parse_airport, parse_lounge
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

LIS_PATH = "/at/LIS/lisbon-portela-airport-terminal-1-ana-airport-lounge/"
TLV_PATH = "/at/TLV/ben-gurion-airport-terminal-3-concourse-c-jetex-c-lounge/"
AIRPORT = '<a href="/at/LIS/lisbon-portela-airport-terminal-1-ana-airport-lounge/?currency=INR">ANA</a><a href="/at/LIS/lisbon-portela-airport-terminal-1-ana-airport-lounge/">again</a><a href="/at/FAO/faro-lounge/">other</a>'
LIS_PAGE = ('<html><script>var x = 1;</script><h1 class="a">ANA Lounge</h1><p>Lisbon Portela Airport (LIS) Terminal 1 04:00 - 23:00 daily Popular</p>'
            '<p>Important information Due to peak activity access may be restricted between 06:00 - 16:00 daily. About this lounge With 900 square meters. Terminal 1. Showers.</p>'
            '<p>Lounge access starts from €19 EUR per person (about $21 USD).</p><p>FlexiPass (+€5 EUR) A FlexiPass gives you the option to change or cancel.</p>'
            '<p>Children under 2 years old can enter most lounges free of charge without a pass. Children aged 2 and over will usually require a full-price pass, unless otherwise stated.</p></html>')
TLV_PAGE = ('<h1>Jetex C Lounge</h1><p>Ben Gurion Airport (TLV) Terminal 3, Concourse C 24 hours daily Popular</p><p>Important information This lounge is temporarily closed for renovation. About this lounge x</p>'
            '<p>access starts from €52 EUR per person (about $58 USD).</p>')


def client_for(handler, limiter=None):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    return LoungePairClient(http, limiter=limiter or SiteLimiter("LoungePair", 0, 1000))


def handler(seen):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        path = request.url.path
        if path == "/at/LIS/":
            return httpx.Response(200, text=AIRPORT)
        if path == LIS_PATH:
            return httpx.Response(200, text=LIS_PAGE)
        if path == "/at/TLV/":
            return httpx.Response(200, text=f'<a href="{TLV_PATH}">Jetex</a>')
        if path == TLV_PATH:
            return httpx.Response(200, text=TLV_PAGE)
        return httpx.Response(404, text="")
    return handle


def test_the_airport_page_gives_each_lounge_of_that_airport_once():
    assert parse_airport(AIRPORT, "LIS") == [LIS_PATH]


def test_a_lounge_page_gives_price_hours_terminal_notice_and_children_and_never_a_guess():
    lounge = parse_lounge(LIS_PAGE, LIS_PATH)
    assert (lounge["name"], lounge["terminal"], lounge["opening_hours"]) == ("ANA Lounge", "Terminal 1", "04:00 - 23:00 daily")
    assert (lounge["from_price_per_person"], lounge["currency"], lounge["flexipass_extra"]) == (19.0, "EUR", 5.0)
    assert lounge["closed"] is False and "restricted" in lounge["important_information"] and lounge["children"].startswith("Children under 2")
    assert lounge["url"] == "https://www.loungepair.com" + LIS_PATH
    jetex = parse_lounge(TLV_PAGE, TLV_PATH)
    assert jetex["closed"] is True and jetex["terminal"] == "Terminal 3, Concourse C" and jetex["opening_hours"] == "24 hours daily"
    empty = parse_lounge("<html>nothing</html>", "/at/XXX/x/")
    assert empty["name"] is None and empty["from_price_per_person"] is None and empty["closed"] is False


async def test_the_client_asks_for_euro_reads_the_pages_once_a_day_and_wants_an_iata_code():
    seen: list[str] = []
    client = client_for(handler(seen))
    first = await client.lounges("lis")
    await client.lounges("LIS")
    assert [l["name"] for l in first] == ["ANA Lounge"] and seen == ["https://www.loungepair.com/at/LIS/", "https://www.loungepair.com" + LIS_PATH + "?currency=EUR"]
    assert await client.lounges("PDL") == []
    with pytest.raises(LoungePairError, match="3-letter IATA"):
        await client.lounges("Lisbon")


async def test_a_human_check_stops_the_client_and_pauses_the_site():
    limiter = SiteLimiter("LoungePair", 0, 1000)
    client = client_for(lambda r: httpx.Response(200, text="<title>Just a moment...</title>"), limiter)
    with pytest.raises(LoungePairError, match="human check"):
        await client.lounges("LIS")
    with pytest.raises(Exception, match="(?i)pause|cool|wait|blocked|try again"):
        await client.lounges("TLV")


async def test_the_tool_marks_every_row_comparison_only_warns_about_a_closed_lounge_and_gives_a_link():
    settings = Settings()
    services = Services(settings, loungepair=client_for(handler([])))
    async with Client(create_server(settings, services)) as c:
        lis = (await c.call_tool("loungepair_lounges", {"airport": "LIS"})).structured_content
        tlv = (await c.call_tool("loungepair_lounges", {"airport": "TLV"})).structured_content
        none = (await c.call_tool("loungepair_lounges", {"airport": "PDL"})).structured_content
    assert lis["comparison_only"] is True and lis["lounges"][0]["quotable"] is False and "not a price for this flight" in lis["lounges"][0]["price_kind"]
    assert lis["source"].endswith(LIS_PATH) and lis["age_rules"].startswith("Children under 2") and "warning" not in lis
    assert tlv["lounges"][0]["closed"] is True and "closed" in tlv["warning"] and "not_provided" in tlv
    assert none["lounges"] == [] and none["source"].endswith("/at/PDL/") and "no lounge" in none["note"]


def test_the_boarding_note_says_when_to_leave_and_whether_the_hours_cover_it():
    from datetime import datetime

    from myt_mcp.lounges.loungepair import hours_note

    assert hours_note("04:00 - 23:00 daily", None) is None
    note = hours_note("04:00 - 23:00 daily", datetime(2026, 12, 17, 19, 15))
    assert "by 18:30" in note and "45 minutes" in note and "does NOT cover" not in note
    assert "does NOT cover 00:15" in hours_note("04:00 - 23:00 daily", datetime(2026, 12, 18, 1, 0))
    assert "open" not in hours_note("24 hours daily", datetime(2026, 12, 17, 3, 0)).replace("opening hours suggest", "")


async def test_every_lounge_comes_with_a_ready_row_that_compose_answer_takes_unchanged_and_never_multiplies_the_price():
    settings = Settings()
    services = Services(settings, loungepair=client_for(handler([])))
    async with Client(create_server(settings, services)) as c:
        d = (await c.call_tool("loungepair_lounges", {"airport": "LIS", "flight_departure": "2099-12-17T19:15:00"})).structured_content
        lounge = d["lounges"][0]
        row = lounge["offer"]
        assert row["price_total"] == 19.0 and row["currency"] == "EUR" and row["quotable"] is False and "PER PERSON" in row["price_basis"] and "not multiplied" in row["price_basis"]
        assert row["details"]["terminal"] == "Terminal 1" and row["details"]["adult_price"] == "from 19 EUR per person" and row["details"]["flexipass_extra"] == "5 EUR per person"
        assert "by 18:30" in lounge["boarding_note"]
        out = (await c.call_tool("compose_answer", {"kind": "lounges", "offers": [row], "filters_used": ["Airport LIS (operator)"],
                                                     "sources_read": [{"name": "LoungePair", "read": 1, "of": 1, "link": row["link"]}],
                                                     "not_checked": [{"name": "Aspire Lounges", "reason": "route not served: Aspire has no lounge at this airport"}]})).structured_content
    assert out["ok"] is True and "19.00 EUR" in out["answer"] and "38.00" not in out["answer"]
