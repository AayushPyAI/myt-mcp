"""TAP Air Portugal: the availability parser (a real answer, Florence to Lisbon on 6 Mar 2027, 2 adults and a child, EUR), the page client,
the fare calendar over HTTP and the two tools with their filters."""

import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services
from myt_mcp.tap.client import TapClient, TapError, _is_availability, search_link
from myt_mcp.tap.parse import check_availability, parse_availability, split_by_origin

pytestmark = pytest.mark.anyio

ANSWER = json.loads((Path(__file__).with_name("fixtures") / "tap_availability_flr_lis.json").read_text())
DAY = date(2027, 3, 6)


def test_parse_the_real_answer():
    p = parse_availability(ANSWER)
    assert p["currency"] == "EUR" and p["passengers"] == {"ADT": 2, "CHD": 1} and len(p["flights"]) == 5
    direct = next(f for f in p["flights"] if f["stops"] == 0)
    assert [(s["flight"], s["operated_by"], s["from"], s["departure"], s["to"], s["arrival"], s["aircraft"]) for s in direct["segments"]] == [
        ("TP875", "NI", "FLR", "2027-03-06 12:20", "LIS", "2027-03-06 14:30", "E90")]
    assert direct["duration_minutes"] == 190
    fares = {f["fare_code"]: f for f in direct["fares"]}
    assert [f["fare_code"] for f in direct["fares"]][:3] == ["DISCNEW", "CLANEW", "PLUSNEW"]
    assert (fares["DISCNEW"]["price_total"], fares["DISCNEW"]["checked_bag_included"], fares["DISCNEW"]["refundable"]) == (434.38, False, False)
    assert (fares["CLANEW"]["price_total"], fares["CLANEW"]["checked_bag_included"], fares["CLANEW"]["refundable"]) == (530.38, True, False)
    assert (fares["PLUSNEW"]["price_total"], fares["PLUSNEW"]["checked_bag_included"], fares["PLUSNEW"]["refundable"]) == (654.38, True, True)
    assert fares["DISCNEW"]["price_per_passenger_type"] == {"ADT": 154.3, "CHD": 125.78}               # 2 x 154.30 + 125.78 = 434.38
    assert fares["DISCNEW"]["seats_left"] == 9 and fares["DISCNEW"]["price_base"] + fares["DISCNEW"]["price_taxes"] == pytest.approx(fares["DISCNEW"]["price_total"], abs=0.05)


def test_train_leg_offers_start_elsewhere_and_are_split_off():
    p = parse_availability(ANSWER)
    same, elsewhere = split_by_origin(p, "FLR")
    assert len(same) == 3 and {f["segments"][0]["from"] for f in elsewhere} == {"ZMS"}
    assert all(f["segments"][0]["from"] == "FLR" for f in same)
    assert check_availability(p, "FLR", "LIS", DAY, 2, 1, 0, "EUR") == []


def test_checks_catch_a_mismatch():
    p = parse_availability(ANSWER)
    assert any("not on 2027-03-07" in x for x in check_availability(p, "FLR", "LIS", date(2027, 3, 7), 2, 1, 0, "EUR"))
    assert any("passengers" in x for x in check_availability(p, "FLR", "LIS", DAY, 3, 1, 0, "EUR"))
    assert any("not USD" in x for x in check_availability(p, "FLR", "LIS", DAY, 2, 1, 0, "USD"))
    assert any("ends at LIS, not OPO" in x for x in check_availability(p, "FLR", "OPO", DAY, 2, 1, 0, "EUR"))
    p["flights"][0]["fares"][0]["price_total"] += 10
    assert any("does not add up" in x for x in check_availability(p, "FLR", "LIS", DAY, 2, 1, 0, "EUR"))
    assert parse_availability({"data": {"listOutbound": [{"listSegment": []}]}})["flights"] == [] and parse_availability({})["flights"] == []


def test_search_link_matches_the_booking_deeplink():
    link = search_link("FLR", "LIS", DAY, 2, 1, 0)
    assert link.startswith("https://booking.flytap.com/booking/flights/deeplink?") and "market=PT" in link
    assert all(x in link for x in ("origin=FLR", "destination=LIS", "flightType=single", "adt=2", "chd=1", "inf=0", "depDate=06.03.2027"))


# ---------- the booking page, faked like SATA's ----------

class _Req:
    def __init__(self, method="POST"):
        self.method = method


class _Resp:
    def __init__(self, url, status=200, text="", method="POST"):
        self.url, self.status, self._text, self.request = url, status, text, _Req(method)

    async def text(self):
        return self._text


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
            raise TimeoutError("no availability call")


class FakePage:
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


AVAILABILITY_URL = "https://booking.flytap.com/bfm/rest/booking/availability/search?payWithMiles=false&starAlliance=false"


def answer(data=None, status=200):
    return _Resp(AVAILABILITY_URL, status, json.dumps(ANSWER if data is None else data))


def test_only_the_availability_post_is_read():
    assert _is_availability(_Resp(AVAILABILITY_URL))
    assert not _is_availability(_Resp(AVAILABILITY_URL, method="GET"))
    assert not _is_availability(_Resp("https://booking.flytap.com/bfm/rest/session/create"))


def tap_for(page, calendar_transport=None):
    return TapClient(FakeBrowser(page), limiter=SiteLimiter("TAP", 0, 1000), transport=calendar_transport)


@pytest.mark.parametrize("page,expected", [
    (FakePage(None, "Access denied. This request was blocked by our security services"), "human check or refused"),
    (FakePage(None, "Choose your flights"), "did not show flights in time"),
    (FakePage(answer({}, status=403)), "refused the search"),
    (FakePage(_Resp(AVAILABILITY_URL, 200, "<html>blocked</html>")), "page instead of data"),
    (FakePage(_Resp(AVAILABILITY_URL, 200, "<html>ACCESS DENIED - blocked by our security services</html>")), "refused the search"),
    (FakePage(_Resp(AVAILABILITY_URL, 200, "{}")), "unexpected format"),
    (FakePage(answer({}, status=500)), "search failed"),
])
async def test_page_problems_are_readable(page, expected):
    with pytest.raises(TapError, match=expected):
        await tap_for(page).search("FLR", "LIS", DAY, 2, 1, 0)


# ---------- the fare calendar over plain HTTP ----------

CALENDAR = {"status": "200", "data": {"bestPriceForDates": [
    {"departureAirport": "FLR", "arrivalAirport": "LIS", "departureDate": "2027-03-05T00:00:00", "bestTotalPrice": 178.9, "currency": "USD", "insertionDate": "2026-09-07T09:43:33", "soldOut": False, "noFlights": False},
    {"departureAirport": "FLR", "arrivalAirport": "LIS", "departureDate": "2027-03-06T00:00:00", "bestTotalPrice": 176.9, "currency": "USD", "insertionDate": "2026-09-07T09:43:33", "soldOut": False, "noFlights": False},
    {"departureAirport": "FLR", "arrivalAirport": "LIS", "departureDate": "2027-03-07T00:00:00", "bestTotalPrice": 0, "currency": "USD", "insertionDate": None, "soldOut": False, "noFlights": True}]}}


class CalendarSite:
    def __init__(self, status=200, answer=CALENDAR):
        self.requests, self.status, self.answer = [], status, answer

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/calendar":
            return httpx.Response(self.status, json=self.answer) if self.status == 200 else httpx.Response(self.status, text="x")
        return httpx.Response(200, text="<html></html>")


async def test_calendar_sends_what_the_website_sends():
    site = CalendarSite()
    got = await tap_for(FakePage(None), httpx.MockTransport(site)).calendar("FLR", "LIS", 2027, 3)
    assert len(got["days"]) == 3
    post = next(r for r in site.requests if r.url.path == "/api/calendar")
    assert post.url.params["functionName"] == "calendar"
    assert json.loads(post.content) == {"cabinClass": "E", "destination": "LIS", "market": "US", "month": "3", "origin": "FLR", "paxType": "ADT",
                                        "payWithMiles": False, "starAlliance": False, "tripType": "O", "year": "2027"}


@pytest.mark.parametrize("site,expected", [(CalendarSite(status=403), "refused the request"), (CalendarSite(status=500), "answered 500"),
                                           (CalendarSite(answer={"data": {}}), "unexpected format")])
async def test_calendar_problems_are_readable(site, expected):
    with pytest.raises(TapError, match=expected):
        await tap_for(FakePage(None), httpx.MockTransport(site)).calendar("FLR", "LIS", 2027, 3)


# ---------- the tools ----------

def tap_server(page, transport=None, settings=None):
    settings = settings or Settings()
    return create_server(settings, Services(settings, tap=tap_for(page, transport)))


@pytest.fixture
def before_the_fixture_date(monkeypatch):
    import myt_mcp.tools.flights as flights
    monkeypatch.setattr(flights, "_today", lambda: date(2026, 10, 16))


async def flights_call(page=None, **extra):
    page = page or FakePage(answer())
    args = {"from_airport": "FLR", "to_airport": "LIS", "departure_date": "2027-03-06", "adults": 2, "child_ages": [8], **extra}
    async with Client(tap_server(page)) as c:
        return await c.call_tool("tap_flight_prices", args), page


async def test_tool_gives_flights_fares_flags_and_the_source(before_the_fixture_date):
    r, page = await flights_call()
    d = r.structured_content
    assert not r.is_error and d["prices_are_for"].endswith("one way, in EUR") and d["search"] == {"from": "FLR", "to": "LIS", "date": "2027-03-06", "adults": 2, "children": 1, "infants": 0}
    assert d["coverage"] == {"flights_read": 3, "passed_filters": 3, "shown": 3, "other_origin_offers": 2}
    first = d["flights"][0]
    assert first["rank"] == 1 and first["segments"][0]["flight"] == "TP875" and first["cheapest_total"] == 434.38 and first["stops"] == 0
    assert d["at_a_glance"]["cheapest"] == {"flights": "TP875", "departure": "2027-03-06 12:20", "price_total": 434.38}
    assert d["at_a_glance"]["cheapest_with_checked_bag"]["fare_code"] == "CLANEW" and d["at_a_glance"]["cheapest_with_checked_bag"]["price_total"] == 530.38
    assert {o["from"] for o in d["other_origin_offers"]} == {"ZMS"} and "train leg" in d["other_origin_note"]
    assert d["source"] == page.links[0] and d["end_your_answer_with"].startswith("Source: TAP Air Portugal (flytap.com), checked ") and d["checked_at"].endswith("UTC")
    assert "adt=2" in page.links[0] and "chd=1" in page.links[0]


async def test_filters_direct_price_bag_and_refund(before_the_fixture_date):
    d = (await flights_call(direct_only=True))[0].structured_content
    assert d["coverage"]["passed_filters"] == 1 and d["flights"][0]["stops"] == 0
    d = (await flights_call(max_price=500))[0].structured_content
    assert [f["fare_code"] for f in d["flights"][0]["fares"]] == ["DISCNEW"] and all(f["price_total"] <= 500 for fl in d["flights"] for f in fl["fares"])
    d = (await flights_call(checked_bag_only=True))[0].structured_content
    assert all(f["checked_bag_included"] for fl in d["flights"] for f in fl["fares"]) and d["flights"][0]["fares"][0]["fare_code"] == "CLANEW"
    d = (await flights_call(refundable_only=True))[0].structured_content
    assert all(f["refundable"] for fl in d["flights"] for f in fl["fares"]) and d["flights"][0]["fares"][0]["fare_code"] == "PLUSNEW"
    d = (await flights_call(max_price=100))[0].structured_content
    assert d["flights"] == [] and "None of the flights read passes the filters" in d["note"] and d["coverage"]["passed_filters"] == 0


async def test_sort_orders_and_max_results(before_the_fixture_date):
    by_price = (await flights_call(sort_by="price"))[0].structured_content["flights"]
    by_departure = (await flights_call(sort_by="departure"))[0].structured_content["flights"]
    by_duration = (await flights_call(sort_by="duration"))[0].structured_content["flights"]
    assert [f["cheapest_total"] for f in by_price] == sorted(f["cheapest_total"] for f in by_price)
    departures = [f["segments"][0]["departure"] for f in by_departure]
    assert departures == sorted(departures)
    durations = [f["duration_minutes"] for f in by_duration]
    assert durations == sorted(durations) and by_duration[0]["stops"] == 0
    d = (await flights_call(max_results=1))[0].structured_content
    assert d["coverage"]["shown"] == 1 and d["coverage"]["passed_filters"] == 3


async def test_infant_and_teen_ages_are_counted_the_way_tap_counts_them(before_the_fixture_date):
    r, page = await flights_call(adults=1, child_ages=[1, 13])
    assert "adt=2" in page.links[0] and "inf=1" in page.links[0] and "chd=0" in page.links[0]


async def test_an_answer_for_another_group_is_not_used(before_the_fixture_date):
    r, _ = await flights_call(child_ages=[])                  # asks 2 adults; the page answered 2 adults + 1 child
    assert r.is_error and "did not match the search" in r.content[0].text


@pytest.mark.parametrize("extra,expected", [
    ({"to_airport": "FLR"}, "are the same"), ({"to_airport": "lisbon"}, "airport code"), ({"departure_date": "2020-01-01"}, "in the past"),
    ({"departure_date": "2028-06-01"}, "up to about a year"), ({"child_ages": [18]}, "ages 0-17"), ({"adults": 0}, "adults must be 1-9"),
    ({"adults": 1, "child_ages": [1, 1]}, "at most one per adult"), ({"max_results": 0}, "between 1 and 20"),
    ({"sort_by": "cheapest"}, "sort_by must be"), ({"max_price": 0}, "more than 0"),
])
async def test_tool_validation(extra, expected, before_the_fixture_date):
    r, page = await flights_call(**extra)
    assert r.is_error and expected in r.content[0].text and page.links == []


async def test_tool_says_when_tap_has_no_flight(before_the_fixture_date):
    empty = {"data": {"listPaxNum": [{"paxNum": 2, "paxType": "ADT"}, {"paxNum": 1, "paxType": "CHD"}], "listOutbound": [], "offers": {"currency": "EUR", "listOffers": []}, "notAvailable": True}}
    r, _ = await flights_call(FakePage(answer(empty)))
    assert not r.is_error and r.structured_content["flights"] == [] and "no flight on this route and date" in r.structured_content["note"]


async def test_tool_kill_switch(before_the_fixture_date):
    settings = Settings(tap_enabled=False)
    async with Client(tap_server(FakePage(answer()), settings=settings)) as c:
        r = await c.call_tool("tap_flight_prices", {"from_airport": "FLR", "to_airport": "LIS", "departure_date": "2027-03-06"})
    assert r.is_error and "switched off" in r.content[0].text


async def test_calendar_tool_lists_days_and_the_cheapest(before_the_fixture_date):
    async with Client(tap_server(FakePage(None), httpx.MockTransport(CalendarSite()))) as c:
        r = await c.call_tool("tap_fare_calendar", {"from_airport": "FLR", "to_airport": "LIS", "year": 2027, "month": 3})
    d = r.structured_content
    assert not r.is_error and d["route"] == "FLR-LIS" and d["month"] == "2027-03" and "USD" in d["prices_are"] and len(d["days"]) == 3
    assert d["cheapest_day"] == {"date": "2027-03-06", "lowest_price_per_adult": 176.9}
    assert d["days"][2] == {"date": "2027-03-07", "lowest_price_per_adult": None, "sold_out": False, "no_flights": True, "price_checked_on": None}
    assert d["end_your_answer_with"].startswith("Source: TAP Air Portugal fare calendar")


@pytest.mark.parametrize("extra,expected", [({"month": 13}, "this month or a later"), ({"year": 2025}, "this month or a later"), ({"year": 2026, "month": 9}, "this month or a later"),
                                            ({"from_airport": "x"}, "airport code")])
async def test_calendar_validation(extra, expected, before_the_fixture_date):
    args = {"from_airport": "FLR", "to_airport": "LIS", "year": 2027, "month": 3, **extra}
    async with Client(tap_server(FakePage(None), httpx.MockTransport(CalendarSite()))) as c:
        r = await c.call_tool("tap_fare_calendar", args)
    assert r.is_error and expected in r.content[0].text
