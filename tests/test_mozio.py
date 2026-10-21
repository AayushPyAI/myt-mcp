"""Mozio transfers: the parser (real answers: Ponta Delgada airport to a hotel in Furnas on 8 Mar 2027, 3 passengers), the browser flow and the tool."""

import json
from datetime import date, time, timedelta
from pathlib import Path

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.mozio.client import MozioClient, MozioError, search_link
from myt_mcp.mozio.parse import check_offers, parse_polls
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

POLLS = json.loads((Path(__file__).with_name("fixtures") / "mozio_polls_pdl_furnas.json").read_text())
DAY = date(2027, 3, 8)
API = "https://api.mozio.com/v2/search/"


def test_parse_the_real_answer():
    p = parse_polls(POLLS)
    assert p["finished"] and p["currency"] == "EUR" and p["passengers"] == 3 and p["pickup"] == "2027-03-08 12:00"
    assert (p["from"]["name"], p["from"]["type"], p["from"]["airport_code"]) == ("Ponta Delgada Airport", "airport", "PDL")
    assert "Furnas" in p["to"]["name"] and p["to"]["only_the_town"] is False
    kinds = sorted((o["vehicle_type"], o["vehicle_class"]) for o in p["offers"])
    assert kinds == [("Private Bus", "Standard"), ("Private Van", "Business VAN"), ("Private Van", "Standard"), ("Sedan", "Business"), ("Sedan", "Standard")]
    sedan = min(p["offers"], key=lambda o: o["price_total"])
    assert (sedan["vehicle_type"], sedan["max_passengers"], sedan["max_bags"], sedan["duration_minutes"]) == ("Sedan", 3, 3, 50)
    assert sedan["departure"] == "2027-03-08 12:00" and sedan["arrival"].startswith("2027-03-08 12:4")
    assert sedan["free_cancellation_hours_before"] == 24 and sedan["waiting_minutes_included"] == 60 and sedan["tolls_included"] is True
    assert 1 < sedan["platform_fee"] < 3 and abs(sedan["price_without_platform_fee"] + sedan["platform_fee"] - sedan["price_total"]) < 0.02
    assert "Early driver details" in sedan["included"] and any(e["name"].startswith("Child booster") and e["price"] > 0 for e in sedan["extras_on_request"])
    assert check_offers(p, DAY, 3, "EUR") == []


def test_polls_are_merged_without_duplicates():
    assert len(parse_polls(POLLS + POLLS)["offers"]) == 5 and parse_polls([])["offers"] == []


def test_checks_catch_a_mismatch():
    p = parse_polls(POLLS)
    assert any("it is for 3 passengers, not 2" in x for x in check_offers(p, DAY, 2, "EUR"))
    assert any("not 2027-03-09" in x for x in check_offers(p, date(2027, 3, 9), 3, "EUR"))
    assert any("not USD" in x for x in check_offers(p, DAY, 3, "USD"))
    p["offers"][0]["price_total"] += 5
    assert any("does not add up" in x for x in check_offers(p, DAY, 3, "EUR"))
    assert any("not finished" in x for x in check_offers({**p, "finished": False}, DAY, 3, "EUR"))


def test_search_link_is_the_one_the_site_builds():
    link = search_link("pdl", "Terra Nostra Garden Hotel, Furnas, Portugal", DAY, time(14, 5), 3)
    assert link.startswith("https://www.mozio.com/v2/en-us/search?start_name=PDL&start_address=PDL&end_name=Terra+Nostra")
    assert "pickup_datetime=03%2F08%2F2027+02%3A05+PM" in link and "mode=one_way" in link and "num_passengers=3" in link and link.endswith("currency=EUR")


# ---------- the browser flow ----------

class _Request:
    def __init__(self, method):
        self.method = method


class _Response:
    def __init__(self, url, status=200, body=None, method="GET"):
        self.url, self.status, self.request, self._body = url, status, _Request(method), body

    async def json(self):
        return self._body


class FakePage:
    def __init__(self, responses, page_text=""):
        self.links, self.handlers, self._responses, self._text = [], [], responses, page_text

    def on(self, _event, handler):
        self.handlers.append(handler)

    def remove_listener(self, _event, handler):
        self.handlers.remove(handler)

    async def goto(self, url, **_):
        self.links.append(url)
        for r in self._responses:
            for h in list(self.handlers):
                h(r)

    async def evaluate(self, _script):
        return self._text


class FakeBrowser:
    def __init__(self, page):
        self.page = page

    async def run(self, origin, start_url, action):
        return await action(self.page)


def good_responses():
    return [_Response(API, 201, None, "POST")] + [_Response(f"{API}abc/poll/", 200, p) for p in POLLS]


def client_for(page):
    return MozioClient(FakeBrowser(page), limiter=SiteLimiter("Mozio", 0, 1000), wait_seconds=3)


async def test_the_page_answers_are_collected_and_cached():
    page = FakePage(good_responses())
    client = client_for(page)
    found = await client.search("PDL", "Furnas", DAY, time(12, 0), 3)
    assert len(found["polls"]) == 4 and found["url"] == page.links[0] and not page.handlers
    await client.search("PDL", "Furnas", DAY, time(12, 0), 3)
    assert len(page.links) == 1


@pytest.mark.parametrize("responses,text,expected", [
    ([_Response(API, 403, None, "POST")], "", "refused the search"),
    ([_Response(API, 500, None, "POST")], "", "search failed"),
    ([], "Please verify you are human", "human check"),
    ([], "Loading", "did not show prices"),
])
async def test_problems_are_readable(responses, text, expected):
    with pytest.raises(MozioError, match=expected):
        await client_for(FakePage(responses, text)).search("PDL", "Furnas", DAY, time(12, 0), 3)


# ---------- the tool ----------

def future(days=30):
    return (date.today() + timedelta(days=days)).isoformat()


async def call(page, settings=None, **args):
    settings = settings or Settings()
    server = create_server(settings, Services(settings, mozio=client_for(page)))
    async with Client(server) as c:
        return await c.call_tool("mozio_transfer_prices", args)


@pytest.fixture
def before_the_fixture_date(monkeypatch):
    import myt_mcp.tools.transfers as transfers
    monkeypatch.setattr(transfers, "_today", lambda: date(2026, 10, 16))


async def test_tool_gives_every_offer_the_cheapest_that_fits_and_the_source(before_the_fixture_date):
    r = await call(FakePage(good_responses()), from_place="PDL", to_place="Terra Nostra Garden Hotel, Furnas", travel_date="2027-03-08", passengers=3)
    d = r.structured_content
    assert not r.is_error and [o["vehicle_type"] for o in d["offers"]][:2] == ["Sedan", "Private Van"]
    assert d["offers"][0]["price_total"] <= d["offers"][1]["price_total"] and all(o["fits_group"] for o in d["offers"])
    assert d["at_a_glance"]["cheapest_that_fits"]["vehicle_type"] == "Sedan" and "EUR" in d["prices_are"]
    assert d["matched_from"]["airport_code"] == "PDL" and "address_note" not in d
    assert d["end_your_answer_with"].startswith("Source: Mozio (mozio.com), checked ") and d["checked_at"].endswith("UTC")


async def test_only_offers_that_take_the_group_are_shown(before_the_fixture_date):
    polls = json.loads(json.dumps(POLLS))
    polls[-1]["num_passengers"] = 12
    r = await call(FakePage([_Response(f"{API}abc/poll/", 200, p) for p in polls]), from_place="PDL", to_place="Furnas", travel_date="2027-03-08", passengers=12)
    d = r.structured_content
    assert not r.is_error and [o["vehicle_type"] for o in d["offers"]] == ["Private Bus"] and d["coverage"]["offers_read"] == 5 and d["coverage"]["fit_the_group"] == 1
    polls = json.loads(json.dumps(POLLS))
    for p in polls:
        for res in p["results"]:
            res["steps"][0]["details"]["vehicle"]["max_passengers"] = 3
    polls[-1]["num_passengers"] = 5
    r = await call(FakePage([_Response(f"{API}abc/poll/", 200, p) for p in polls]), from_place="PDL", to_place="Furnas", travel_date="2027-03-08", passengers=5)
    assert r.structured_content["at_a_glance"]["cheapest_that_fits"] is None and "two vehicles" in r.structured_content["note"] and r.structured_content["offers"] == []


async def test_max_results_caps_the_list_and_ranks(before_the_fixture_date):
    r = await call(FakePage(good_responses()), from_place="PDL", to_place="Furnas", travel_date="2027-03-08", passengers=3, max_results=2)
    d = r.structured_content
    assert [o["rank"] for o in d["offers"]] == [1, 2] and d["coverage"]["shown"] == 2 and d["coverage"]["fit_the_group"] == 5 and "3 more offers" in d["more_offers_note"]


async def test_a_scheduled_shuttle_is_not_a_private_offer(before_the_fixture_date):
    polls = json.loads(json.dumps(POLLS))
    cheap = next(res for p in polls for res in p["results"] if res["steps"][0]["details"]["vehicle"]["vehicle_type"]["name"] == "Sedan")
    cheap["steps"][0]["details"]["vehicle"]["vehicle_type"]["name"] = "Bus"
    cheap["steps"][0]["details"]["ticket_types"] = [{"ticket_id": "PNOS", "ticket_name": "Adult", "schedules": []}]
    r = await call(FakePage([_Response(f"{API}abc/poll/", 200, p) for p in polls]), from_place="PDL", to_place="Furnas", travel_date="2027-03-08", passengers=3)
    d = r.structured_content
    assert d["coverage"]["scheduled_shuttles_not_priced"] == 1 and d["coverage"]["private_offers"] == 4 and "Bus" not in [o["vehicle_type"] for o in d["offers"]]
    assert "per-person tickets" in d["shuttle_note"] and d["offers"][0]["price_total"] >= 141


async def test_only_the_town_is_flagged(before_the_fixture_date):
    polls = json.loads(json.dumps(POLLS))
    polls[-1]["end_location"]["is_incomplete"] = True
    r = await call(FakePage([_Response(f"{API}abc/poll/", 200, p) for p in polls]), from_place="PDL", to_place="Furnas", travel_date="2027-03-08", passengers=3)
    assert "centre of the town" in r.structured_content["address_note"]


async def test_no_offers_is_not_an_error(before_the_fixture_date):
    polls = json.loads(json.dumps(POLLS))
    for p in polls:
        p["results"] = []
    r = await call(FakePage([_Response(f"{API}abc/poll/", 200, p) for p in polls]), from_place="PDL", to_place="Furnas", travel_date="2027-03-08", passengers=3)
    assert not r.is_error and r.structured_content["offers"] == [] and "no transfer" in r.structured_content["note"]


async def test_an_answer_for_another_group_is_not_used(before_the_fixture_date):
    r = await call(FakePage(good_responses()), from_place="PDL", to_place="Furnas", travel_date="2027-03-08", passengers=2)
    assert r.is_error and "did not match the search" in r.content[0].text


@pytest.mark.parametrize("extra,expected", [
    ({"from_place": " "}, "need a place"), ({"to_place": "x" * 151}, "too long"), ({"travel_date": "2020-01-01"}, "in the past"),
    ({"max_results": 0}, "max_results must be between 1 and 50"), ({"passengers": 0}, "between 1 and 16"), ({"passengers": 17}, "between 1 and 16"), ({"pickup_time": "25:00"}, "HH:MM"), ({"pickup_time": "noon"}, "HH:MM"),
])
async def test_tool_validation(extra, expected, before_the_fixture_date):
    page = FakePage(good_responses())
    args = {"from_place": "PDL", "to_place": "Furnas", "travel_date": "2027-03-08", "passengers": 3, **extra}
    r = await call(page, **args)
    assert r.is_error and expected in r.content[0].text and not page.links


async def test_tool_kill_switch(before_the_fixture_date):
    r = await call(FakePage(good_responses()), settings=Settings(mozio_enabled=False), from_place="PDL", to_place="Furnas", travel_date="2027-03-08")
    assert r.is_error and "switched off" in r.content[0].text


async def test_a_default_pickup_time_is_flagged_and_a_given_one_is_not(before_the_fixture_date):
    base = dict(from_place="PDL", to_place="Terra Nostra Garden Hotel, Furnas", travel_date="2027-03-08", passengers=3)
    default = (await call(FakePage(good_responses()), **base)).structured_content
    assert default["pickup_time"] == "12:00" and "pickup_time_was_default" in default and "ask the operator" in default["pickup_time_was_default"]
    given = (await call(FakePage(good_responses()), **base, pickup_time="12:00")).structured_content
    assert "pickup_time_was_default" not in given
