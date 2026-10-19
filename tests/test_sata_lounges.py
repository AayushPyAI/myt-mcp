"""SATA flights (azoresairlines.pt) and Aspire lounges. Fixtures are trimmed real answers."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.lounges import aspire as aspire_api
from myt_mcp.lounges.aspire import AspireClient, AspireError, Reply
from myt_mcp.lounges.parse import match_airport, summarize_rates
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.sata.client import SataClient, SataError, _is_flight_search, search_link
from myt_mcp.sata.parse import check_answer, summarize_availability
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).with_name("fixtures")
ROUND_TRIP = json.loads((FIXTURES / "sata_lis_pdl_round_trip.json").read_text())
ISLANDS = json.loads((FIXTURES / "sata_pdl_hor.json").read_text())
TLV_RATES = json.loads((FIXTURES / "aspire_rates_tlv.json").read_text())
SOON = (date.today() + timedelta(days=30)).isoformat()


# ---------- SATA flights ----------

OUT = (date.today() + timedelta(days=30)).isoformat()
BACK = (date.today() + timedelta(days=37)).isoformat()
PAX_2_1 = {"adults": 2, "children": 1, "infants": 0}


def shifted(fixture, out=OUT, back=BACK):
    """The real answer moved to the test's dates (fixtures were captured for 10 and 17 Nov 2026)."""
    return json.loads(json.dumps(fixture).replace("2026-11-10", out).replace("2026-11-17", back))


def test_checks_accept_the_real_answer():
    assert check_answer(ROUND_TRIP, "LIS", "PDL", "2026-11-10", "2026-11-17", PAX_2_1) == []
    assert check_answer(ISLANDS, "PDL", "HOR", "2026-11-12", None, PAX_2_1) == []


@pytest.mark.parametrize("args,expected", [
    (("LIS", "PDL", "2026-11-11", "2026-11-17", PAX_2_1), "instead of LIS->PDL on 2026-11-11"),
    (("LIS", "PDL", "2026-11-10", None, PAX_2_1), "2 directions instead of 1"),
    (("LIS", "PDL", "2026-11-10", "2026-11-17", {"adults": 2, "children": 0, "infants": 0}), "priced for"),
    (("OPO", "PDL", "2026-11-10", "2026-11-17", PAX_2_1), "instead of OPO->PDL"),
])
def test_checks_catch_a_mismatch(args, expected):
    assert any(expected in p for p in check_answer(ROUND_TRIP, *args))


def test_checks_catch_wrong_totals_and_currency():
    broken = json.loads(json.dumps(ROUND_TRIP))
    broken["data"]["currency"] = "USD"
    first = next(iter(broken["data"]["itineraryInfoDictionary"].values()))
    first["totalTripPrice"]["cash"] += 50
    problems = check_answer(broken, "LIS", "PDL", "2026-11-10", "2026-11-17", PAX_2_1)
    assert any("USD" in p for p in problems) and any("does not add up" in p for p in problems)

def test_one_way_options():
    d = summarize_availability(ISLANDS, 3)
    first = d["options"][0]
    assert d["currency"] == "EUR" and d["total_options"] == 10
    assert first["legs"][0]["flights"] == ["SP 7442"] and first["legs"][0]["stops"] == 0   # direct first at equal price
    assert first["total_price"] == 255.95 and first["per_passenger_type"] == {"adults": 193.3, "children": 62.65}
    assert first["legs"][0]["departs"] == "2026-11-12 08:30" and first["legs"][0]["fare"] == "VALUE_AZ"
    assert d["fare_conditions"]["VALUE_AZ"]["checked_bag"].startswith("23 kg")
    assert d["note"].startswith("Showing 3 of 10 options") and "higher max_results" in d["note"]
    assert "note" not in summarize_availability(ISLANDS, 10)                      # everything shown: nothing to add


def test_per_person_split_is_group_total_divided_by_travellers():
    """per_passenger_type is a GROUP total per type (193.30 + 62.65 = 255.95): one adult is 96.65, not 193.30."""
    d = summarize_availability(ISLANDS, 3, PAX_2_1)
    first = d["options"][0]
    assert first["per_passenger_type"] == {"adults": 193.3, "children": 62.65}
    assert first["per_person_by_type"] == {"adults": 96.65, "children": 62.65}
    assert round(sum(first["per_passenger_type"].values()), 2) == first["total_price"]
    assert "TOTAL for all travellers of that type" in d["per_passenger_type_note"] and "per_person_by_type" in d["per_passenger_type_note"]
    assert summarize_availability(ISLANDS, 3)["options"][0]["per_person_by_type"] == {}          # no traveller counts: nothing to divide by
    assert summarize_availability(ISLANDS, 3, {"adults": 2, "children": 0, "infants": 0})["options"][0]["per_person_by_type"] == {"adults": 96.65}


def test_round_trip_options():
    d = summarize_availability(ROUND_TRIP, 10)
    first = d["options"][0]
    assert first["total_price"] == 502.99 and len(first["legs"]) == 2
    assert first["legs"][0]["flights"] == ["S4 121"] and first["legs"][1]["from"] == "PDL"
    assert list(first["price_by_fare"]) == ["SPL_DOMESTIC_BF", "BSC_DOMESTIC_BF", "FLX_DOMESTIC_BF", "TOP_DOMESTIC_BF"]
    assert d["total_options"] == 4   # 2 outbound x 2 return flights
    assert "Non Refundable" in d["fare_conditions"]["SPL_DOMESTIC_BF"]["refund"]
    assert "SPL" in d["fare_names_note"] and "made-up" in d["fare_names_note"]
    starred = [k for k, c in d["fare_conditions"].items() if any("*" in str(v) for v in c.values())]
    assert ("fine_print" in d) == bool(starred)                                 # an asterisk always comes with its warning
    if starred:
        assert "never call it free" in d["fine_print"]


def test_round_trip_shows_different_outbound_flights_first():
    d = summarize_availability(ROUND_TRIP, 2)
    assert [o["legs"][0]["flights"] for o in d["options"]] == [["S4 121"], ["S4 125"]]
    assert all(o["total_price"] == 502.99 for o in d["options"])


def test_search_link():
    link = search_link("LIS", "PDL", date(2026, 11, 10), date(2026, 11, 17), 2, 1, 0)
    assert link == ("https://book.azoresairlines.pt/booking/dl?step=flights&pointOfSale=PT&adults=2&lang=en"
                    "&search=LIS.PDL.2026-11-10*PDL.LIS.2026-11-17&children=1")


class _Req:
    def __init__(self, body):
        self.post_data = body


class _Resp:
    def __init__(self, url, body, status=200, text=""):
        self.url, self.request, self.status, self._text = url, _Req(body), status, text

    async def text(self):
        return self._text


def test_only_the_full_search_is_read():
    url = "https://api-book.azoresairlines.pt/ibe/pricedAvailability"
    assert _is_flight_search(_Resp(url, '{"options":{"tbar":false,"solutions":true}}'))
    assert not _is_flight_search(_Resp(url, '{"options":{"tbar":true,"solutions":false}}'))   # the date bar call
    assert not _is_flight_search(_Resp("https://api-book.azoresairlines.pt/ibe/calendarPrices/oneway", None))


class _Waiter:
    def __init__(self, response):
        self._response = response

    @property
    async def value(self):
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self._response is None:
            raise TimeoutError("no flight search")


class FakeBookingPage:
    """Stands in for SATA's booking page: 'loads' the link and hands back a prepared flight answer."""

    def __init__(self, response, body=""):
        self.links, self._response, self._body = [], response, body

    def expect_response(self, predicate, timeout):
        return _Waiter(self._response)

    async def goto(self, url, **_):
        self.links.append(url)

    async def evaluate(self, _script):
        return self._body


class FakeBrowser:
    def __init__(self, page):
        self.page = page

    async def run(self, origin, start_url, action):
        return await action(self.page)


def answer(data, status=200):
    return _Resp("https://api-book.azoresairlines.pt/ibe/pricedAvailability", None, status, json.dumps(data))


def sata_server(page, settings=None):
    settings = settings or Settings()
    client = SataClient(FakeBrowser(page), limiter=SiteLimiter("SATA", 0, 1000))
    return create_server(settings, Services(settings, sata=client))


async def test_round_trip_tool_and_cache():
    page = FakeBookingPage(answer(shifted(ROUND_TRIP)))
    args = {"from_airport": "lis", "to_airport": "PDL", "departure_date": OUT, "return_date": BACK, "children": 1, "max_results": 2}
    async with Client(sata_server(page)) as c:
        r = await c.call_tool("sata_flight_prices", args)
        await c.call_tool("sata_flight_prices", args)
    d = r.structured_content
    assert d["prices_are_for"] == "all passengers together, in EUR" and len(d["options"]) == 2
    assert d["options"][0]["total_price"] == 502.99 and d["search"]["from"] == "LIS"
    assert len(page.links) == 1 and f"search=LIS.PDL.{OUT}*PDL.LIS.{BACK}" in page.links[0]   # repeat answered from cache
    assert d["source"] == page.links[0] and d["checked_at"].endswith("UTC") and d["data_age_minutes"] == 0


async def test_mismatched_answer_is_not_used():
    page = FakeBookingPage(answer(shifted(ROUND_TRIP)))   # SATA answers for OUT, but we ask a day later
    later = (date.today() + timedelta(days=31)).isoformat()
    async with Client(sata_server(page)) as c:
        r = await c.call_tool("sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": later,
                                                     "return_date": BACK, "children": 1})
    assert r.is_error and "did not match the search" in r.content[0].text and "was not used" in r.content[0].text


@pytest.mark.parametrize("page,expected", [
    (FakeBookingPage(None, "Please verify you are human"), "human check"),
    (FakeBookingPage(None, "Choose your flights"), "did not show flights in time"),
    (FakeBookingPage(answer({}, status=403)), "refused the search"),
    (FakeBookingPage(_Resp("x", None, 200, "<html>")), "page instead of data"),
])
async def test_sata_failures_are_readable(page, expected):
    client = SataClient(FakeBrowser(page), limiter=SiteLimiter("SATA", 0, 1000))
    with pytest.raises(SataError, match=expected):
        await client.search("LIS", "PDL", date.today() + timedelta(days=30), None, 2, 0, 0)


async def test_no_flights_note():
    empty = {"messages": [], "data": {"currency": "EUR", "bounds": [], "cabins": [], "itineraryInfoDictionary": {}}}
    async with Client(sata_server(FakeBookingPage(answer(empty)))) as c:
        r = await c.call_tool("sata_flight_prices", {"from_airport": "PDL", "to_airport": "CVU", "departure_date": OUT})
    assert r.structured_content["options"] == [] and "no flights" in r.structured_content["note"]


@pytest.mark.parametrize("args,expected", [
    ({"from_airport": "Lisbon"}, "airport code"),
    ({"departure_date": "2020-01-01"}, "in the past"),
    ({"return_date": (date.today() + timedelta(days=1)).isoformat()}, "before departure_date"),
    ({"infants": 3}, "one per adult"),
    ({"adults": 5, "children": 5}, "9 seats"),
    ({"to_airport": "LIS"}, "the same"),
])
async def test_flight_input_validation(args, expected):
    page = FakeBookingPage(answer(ISLANDS))
    async with Client(sata_server(page)) as c:
        r = await c.call_tool("sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": SOON, **args})
    assert r.is_error and expected in r.content[0].text and not page.links


async def test_sata_kill_switch():
    async with Client(sata_server(FakeBookingPage(answer(ISLANDS)), Settings(sata_enabled=False))) as c:
        r = await c.call_tool("sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": SOON})
    assert r.is_error and "switched off" in r.content[0].text


# ---------- lounges ----------

AIRPORTS = ["london-heathrow-airport", "tel-aviv-ben-gurion-airport", "venice-marco-polo-airport", "verona-airport"]


def test_match_airport():
    assert match_airport("tlv", AIRPORTS) == ["tel-aviv-ben-gurion-airport"]
    assert match_airport("Ben Gurion", AIRPORTS) == ["tel-aviv-ben-gurion-airport"]
    assert match_airport("Venice airport", AIRPORTS) == ["venice-marco-polo-airport"]
    assert match_airport("Lisbon", AIRPORTS) == [] and match_airport("  ", AIRPORTS) == []


def test_group_price():
    d = summarize_rates(TLV_RATES, {"adults": 2, "children": 1, "infants": 1})
    assert d["available"] and d["total_price"] == 240.0 and d["lounge_entry"].endswith("06:00:00")
    assert [t["ticket"] for t in d["tickets"]] == ["Adult", "Child", "Infant"] and d["tickets"][2]["price_each"] == 0.0
    assert "note" not in d


def test_group_limits_and_discounts():
    rates = json.loads(json.dumps(TLV_RATES))
    adult = rates["data"]["tickets"][0]
    adult["price"] = {"unit": 72.0, "originalValue": 80.0, "discount": 8.0}   # discount already in unit
    child = rates["data"]["tickets"][1]
    child["price"] = {"unit": 80.0, "originalValue": 80.0, "discount": 10.0}  # discount still to take off
    d = summarize_rates(rates, {"adults": 6, "children": 1})
    assert d["tickets"][0]["price_each"] == 72.0 and d["tickets"][1]["price_each"] == 70.0
    assert "two bookings" in d["note"]
    assert summarize_rates({"isError": True, "errorDescription": "Closed"}, {"adults": 1}) == {"available": False, "note": "Closed"}
    assert summarize_rates({"data": {"isAvailable": False}}, {"adults": 1})["available"] is False


LOUNGE_PAGE = """<html><head><title>Aspire Lounges | Tel Aviv (TLV) Airport Lounge</title>
<meta name="description" content="Relax at Tel Aviv &amp; more"></head><body>x-data="{ loungeID: '252', }"</body></html>"""


class FakeTransport:
    def __init__(self, replies=None):
        self.sent = []
        self._replies = replies or {}

    async def send(self, method, url, body=None):
        self.sent.append((method, url, body))
        for part, reply in self._replies.items():
            if part in url:
                return reply
        if url.endswith("aspirelounges.com/"):
            return Reply(200, '<a href="https://www.aspirelounges.com/airports/tel-aviv-ben-gurion-airport/">TLV</a>')
        if "/airports/" in url:
            return Reply(200, '<a href="/airport-lounges/tel-aviv-ben-gurion-airport-aspire-lounge/">Lounge</a>')
        if "/airport-lounges/" in url:
            return Reply(200, LOUNGE_PAGE)
        asked = body["ArrivalDate"][:16]   # answer for the asked flight time, like Aspire
        return Reply(200, json.dumps(TLV_RATES).replace("2026-11-10T08:00", asked).replace("2026-11-10T06:00", asked[:11] + "06:00"))

    async def aclose(self):
        pass


def lounge_server(transport, settings=None):
    settings = settings or Settings()
    client = AspireClient(transport, limiter=SiteLimiter("Aspire", 0, 1000))
    return create_server(settings, Services(settings, aspire=client))


FLIGHT = (datetime.now() + timedelta(days=30)).replace(hour=8, minute=0, second=0, microsecond=0)


async def test_lounge_tool_and_page_cache():
    transport = FakeTransport()
    async with Client(lounge_server(transport)) as c:
        r = await c.call_tool("lounge_prices", {"airport": "TLV", "flight_departure": FLIGHT.isoformat(), "children": 1})
        await c.call_tool("lounge_prices", {"airport": "Ben Gurion", "flight_departure": FLIGHT.isoformat(), "children": 1})
    d = r.structured_content
    lounge = d["lounges"][0]
    assert (lounge["lounge_id"], lounge["airport_code"], lounge["total_price"]) == (252, "TLV", 240.0)
    assert lounge["description"] == "Relax at Tel Aviv & more" and "age_rules" in d
    assert d["source"] == lounge["url"] and lounge["url"] in d["end_your_answer_with"] and d["end_your_answer_with"].endswith(d["age_rules"])      # the lounge page is the source link
    posts = [s for s in transport.sent if s[0] == "POST"]
    assert len(transport.sent) == 4 and posts[0][2]["LoungeId"] == "252" and posts[0][2]["Currency"] == "EUR"
    assert posts[0][2]["ArrivalDate"] == FLIGHT.strftime("%Y-%m-%dT%H:%M:00")


async def test_rates_for_another_flight_time_are_not_used():
    transport = FakeTransport({"availability/rates": Reply(200, json.dumps(TLV_RATES))})   # always 10 Nov 08:00
    async with Client(lounge_server(transport)) as c:
        r = await c.call_tool("lounge_prices", {"airport": "TLV", "flight_departure": FLIGHT.isoformat()})
    assert r.is_error and "did not match the search" in r.content[0].text


async def test_airport_without_aspire():
    async with Client(lounge_server(FakeTransport())) as c:
        r = await c.call_tool("lounge_prices", {"airport": "Lisbon", "flight_departure": FLIGHT.isoformat()})
    assert r.structured_content["lounges"] == [] and "no lounge" in r.structured_content["note"]


@pytest.mark.parametrize("reply,expected", [
    (Reply(403, "<html>Attention Required! | Cloudflare</html>"), "human check"),
    (Reply(200, "<title>Just a moment...</title>"), "human check"),
    (Reply(500, "oops"), "could not answer"),
])
async def test_aspire_blocks_and_errors(reply, expected):
    client = AspireClient(FakeTransport({"aspirelounges.com/": reply}), limiter=SiteLimiter("Aspire", 0, 1000))
    with pytest.raises(AspireError, match=expected):
        await client.airports()


@pytest.mark.parametrize("args,expected", [
    ({"flight_departure": "2020-01-01T08:00:00"}, "in the past"),
    ({"adults": 0}, "at least one traveller"),
    ({"airport": " "}, "airport is empty"),
])
async def test_lounge_input_validation(args, expected):
    transport = FakeTransport()
    async with Client(lounge_server(transport)) as c:
        r = await c.call_tool("lounge_prices", {"airport": "TLV", "flight_departure": FLIGHT.isoformat(), **args})
    assert r.is_error and expected in r.content[0].text and not transport.sent


async def test_aspire_kill_switch():
    async with Client(lounge_server(FakeTransport(), Settings(aspire_enabled=False))) as c:
        r = await c.call_tool("lounge_prices", {"airport": "TLV", "flight_departure": FLIGHT.isoformat()})
    assert r.is_error and "switched off" in r.content[0].text


async def test_aspire_refusal_is_explained_without_a_guessed_reason(monkeypatch):
    import myt_mcp.lounges.aspire as aspire_module
    from myt_mcp.errors import IntegrationError
    monkeypatch.setattr(aspire_module, "RETRY_WAIT_SECONDS", 0)

    class Refusing(FakeTransport):
        async def send(self, method, url, body=None):
            if method == "POST":
                self.posts = getattr(self, "posts", 0) + 1
                raise IntegrationError("The request to https://www.aspirelounges.com failed in the browser. The site refused it")
            return await super().send(method, url, body)

    transport = Refusing()
    async with Client(lounge_server(transport)) as c:
        r = await c.call_tool("lounge_prices", {"airport": "TLV", "flight_departure": FLIGHT.isoformat()})
    text = r.content[0].text
    assert r.is_error and "did not answer" in text and "do not guess" in text
    assert "early" not in text and transport.posts == 2          # one retry, and no invented cause


async def test_aspire_retries_once_when_the_connection_drops(monkeypatch):
    import myt_mcp.lounges.aspire as aspire_module
    from myt_mcp.errors import IntegrationError
    monkeypatch.setattr(aspire_module, "RETRY_WAIT_SECONDS", 0)

    class Flaky(FakeTransport):
        failed = False

        async def send(self, method, url, body=None):
            if method == "POST" and not self.failed:
                self.failed = True
                raise IntegrationError("The request to https://www.aspirelounges.com failed in the browser.")
            return await super().send(method, url, body)

    async with Client(lounge_server(Flaky())) as c:
        r = await c.call_tool("lounge_prices", {"airport": "TLV", "flight_departure": FLIGHT.isoformat()})
    assert not r.is_error and r.structured_content["lounges"]


# ---------- Aspire: plain HTTP first, the browser as the fallback ----------

class _Transport:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    async def send(self, method, url, body=None):
        self.calls.append((method, url))
        if self.error:
            raise self.error
        return self.reply

    async def aclose(self):
        pass


@pytest.mark.parametrize("primary,expect_fallback", [
    (_Transport(reply=aspire_api.Reply(200, "{}")), False),
    (_Transport(reply=aspire_api.Reply(404, "no")), False),                         # the site's own answer: not a reason to switch
    (_Transport(reply=aspire_api.Reply(403, "blocked")), True),
    (_Transport(reply=aspire_api.Reply(429, "slow")), True),
    (_Transport(reply=aspire_api.Reply(503, "down")), True),
    (_Transport(error=aspire_api.AspireError("Could not reach Aspire Lounges (ConnectError).")), True),
])
async def test_aspire_uses_http_first_and_the_browser_only_when_http_fails(primary, expect_fallback):
    fallback = _Transport(reply=aspire_api.Reply(200, '{"from": "browser"}'))
    reply = await aspire_api.FallbackTransport(primary, fallback).send("GET", "https://www.aspirelounges.com/x")
    assert bool(fallback.calls) is expect_fallback and (reply.text == '{"from": "browser"}') is expect_fallback
