"""Israir flights: the parser (a real answer: TLV to Rome on 1 Mar 2027, 2 adults and a child aged 8), the HTTP flow and the tool."""

import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.israir.client import IsrairClient, IsrairError
from myt_mcp.israir.parse import check_packages, parse_packages
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

ANSWER = json.loads((Path(__file__).with_name("fixtures") / "israir_search_tlv_rom.json").read_text())
CITIES = {"destinations": [{"cityCode": "TLV", "ltravelId": 768}, {"cityCode": "ROM", "ltravelId": 802}, {"cityCode": "MIL", "ltravelId": 567}, {"cityCode": "OPO", "ltravelId": 99}]}
DAY = date(2027, 3, 1)


def test_parse_the_real_answer():
    [o] = parse_packages(ANSWER)
    assert (o["flight_numbers"], o["from"], o["to"], o["departure"], o["arrival"], o["stops"]) == (["349"], "TLV", "FCO", "2027-03-01 16:10", "2027-03-01 18:55", 0)
    assert (o["price_total"], o["currency"], o["price_per_passenger_type"], o["package_type"]) == (237, "USD", {"adult": 79, "child": 79}, "CHARTER")
    assert o["baggage"] == {"hand_bag_included": True, "trolley_included": False, "checked_bag_included": False,
                            "checked_bag": "not included (23 kg can be added for a fee)"}
    assert o["passengers"]["adults"] == 2 and o["passengers"]["children"] == 1 and not o["meal_included"]
    assert o["source"].startswith("https://www.israir.co.il/he-IL/reservation/deal/searchFlight/abroadFlight?destCode=FCO&departDate=01/03/27")
    assert "sessionId" not in o["source"] and "token" not in o["source"]
    assert check_packages([o], DAY, 2, 1, "TLV", "ROM") == []


def test_checks_catch_a_mismatch():
    [o] = parse_packages(ANSWER)
    assert any("not on 2027-03-02" in p for p in check_packages([o], date(2027, 3, 2), 2, 1, "TLV", "ROM"))
    assert any("not 3 adults" in p for p in check_packages([o], DAY, 3, 1, "TLV", "ROM"))
    o["price_total"] = 250
    assert any("does not add up" in p for p in check_packages([o], DAY, 2, 1, "TLV", "ROM"))
    assert parse_packages({"data": {"ltsPackages": [{"broken": True}]}}) == [] and parse_packages({}) == []


class Site:
    def __init__(self, answer=ANSWER, status=200, cities=CITIES, search_text=None):
        self.requests, self.answer, self.status, self.cities, self.search_text = [], answer, status, cities, search_text

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/allPossibleDestinations":
            return httpx.Response(200, json={"data": self.cities})
        if request.url.path == "/api/search/FLIGHTS":
            if self.search_text is not None:
                return httpx.Response(self.status, text=self.search_text)
            return httpx.Response(self.status, json=self.answer)
        return httpx.Response(404)


def client_for(site):
    return IsrairClient(transport=httpx.MockTransport(site), limiter=SiteLimiter("Israir", 0, 1000))


async def test_search_sends_what_the_website_sends_and_caches():
    site = Site()
    client = client_for(site)
    assert (await client.cities())["ROM"] == 802
    await client.search("TLV", "ROM", DAY, 2, (8,))
    search = next(r for r in site.requests if r.url.path == "/api/search/FLIGHTS")
    p = search.url.params
    origin, destination = json.loads(p["origin"]), json.loads(p["destination"])
    assert (origin["cityCode"], origin["ltravelId"]) == ("TLV", 2135) and (destination["cityCode"], destination["ltravelId"], destination["type"]) == ("ROM", 802, "ltravelId")
    assert (p["startDate"], p["adults"], p["children"], p["siteId"]) == ("01/03/2027", "2", "8", "isra2023") and "infants" not in p
    assert json.loads(search.content) == {"ignoredResults": 0, "siteId": "isra2023"}
    count = len(site.requests)
    await client.search("TLV", "ROM", DAY, 2, (8,))
    assert len(site.requests) == count


async def test_infants_and_children_are_sent_apart_and_the_other_direction_uses_the_city_id():
    site = Site()
    await client_for(site).search("ROM", "TLV", date(2027, 3, 4), 2, (1, 8))
    p = next(r for r in site.requests if r.url.path == "/api/search/FLIGHTS").url.params
    assert p["children"] == "8" and p["infants"] == "1" and json.loads(p["origin"])["ltravelId"] == 802 and json.loads(p["destination"])["ltravelId"] == 768


@pytest.mark.parametrize("site,expected", [
    (Site(status=403), "refused the search"), (Site(status=500), "answered 500"),
    (Site(search_text="<html>queue</html>"), "waiting room"), (Site(answer={"status": "Error"}), "unexpected format"),
    (Site(cities=[]), "list of destinations"),
])
async def test_problems_are_readable(site, expected):
    client = client_for(site)
    with pytest.raises(IsrairError, match=expected):
        await client.search("TLV", "ROM", DAY, 2)


# ---------- the tool ----------

def future(days=30):
    return (date.today() + timedelta(days=days)).isoformat()


async def call(site, settings=None, **args):
    settings = settings or Settings()
    server = create_server(settings, Services(settings, israir=client_for(site)))
    async with Client(server) as c:
        return await c.call_tool("israir_flight_prices", args)


@pytest.fixture
def before_the_fixture_date(monkeypatch):
    import myt_mcp.tools.flights as flights
    monkeypatch.setattr(flights, "_today", lambda: date(2026, 10, 16))


async def test_tool_gives_the_flight_the_group_total_in_usd_and_the_baggage(before_the_fixture_date):
    r = await call(Site(), from_airport="TLV", to_airport="FCO", departure_date="2027-03-01", adults=2, child_ages=[8])
    d = r.structured_content
    assert not r.is_error and d["options"][0]["flight_numbers"] == ["349"] and d["options"][0]["price_total"] == 237
    assert "USD" in d["prices_are_for"] and d["at_a_glance"]["cheapest"]["currency"] == "USD" and "checked bag is not in the price" in d["baggage_note"]
    assert d["end_your_answer_with"].startswith("Source: Israir (israir.co.il), checked ") and d["checked_at"].endswith("UTC")


async def test_tool_says_when_israir_has_no_such_flight(before_the_fixture_date):
    empty = {"status": "Success", "data": {"ltsPackages": []}}
    r = await call(Site(answer=empty), from_airport="PDL", to_airport="TLV", departure_date="2027-03-11", adults=2)
    assert "Israir does not sell flights to or from PDL" in r.content[0].text
    r = await call(Site(answer=empty), from_airport="TLV", to_airport="OPO", departure_date="2027-03-11", adults=2)
    assert not r.is_error and r.structured_content["options"] == [] and "batch seats" in r.structured_content["note"]


async def test_a_flight_for_another_group_is_not_used(before_the_fixture_date):
    r = await call(Site(), from_airport="TLV", to_airport="FCO", departure_date="2027-03-01", adults=3, child_ages=[8])
    assert r.is_error and "did not match the search" in r.content[0].text


@pytest.mark.parametrize("extra,expected", [
    ({"from_airport": "FCO", "to_airport": "LIS"}, "one of from_airport and to_airport must be TLV"),
    ({"from_airport": "TLV", "to_airport": "TLV"}, "one of from_airport"),
    ({"from_airport": "t1"}, "airport code"),
    ({"departure_date": "2020-01-01"}, "in the past"),
    ({"departure_date": "2028-06-01"}, "one year ahead"),
    ({"adults": 0}, "adults must be 1-9"),
    ({"adults": 9, "child_ages": [3]}, "at most 9"),
    ({"child_ages": [18]}, "ages 0-17"),
])
async def test_tool_validation(extra, expected, before_the_fixture_date):
    site = Site()
    args = {"from_airport": "TLV", "to_airport": "FCO", "departure_date": "2027-03-01", "adults": 2, **extra}
    r = await call(site, **args)
    assert r.is_error and expected in r.content[0].text and not site.requests


async def test_tool_kill_switch(before_the_fixture_date):
    r = await call(Site(), settings=Settings(israir_enabled=False), from_airport="TLV", to_airport="FCO", departure_date="2027-03-01")
    assert r.is_error and "switched off" in r.content[0].text
