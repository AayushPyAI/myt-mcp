"""Kiwitaxi transfers: the results-page parser (a real page, 1 Mar 2027, FCO to Room Mate Collection Mia, 3 passengers),
the HTTP search flow and the tool."""

from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.kiwitaxi.client import KiwitaxiClient, KiwitaxiError
from myt_mcp.kiwitaxi.parse import check_results, date_label, parse_results
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

PAGE = (Path(__file__).with_name("fixtures") / "kiwitaxi_results.html").read_text()
DAY = date(2027, 3, 1)
FCO = {"id": "internal:374", "type": "airport", "title": "Rome Airport Fiumicino (FCO)", "address": "Rome Airport Fiumicino (FCO), Italy"}
HOTEL = {"id": "ChIJT5F8Q7hhLxMRqJm2JfhTtlQ", "type": None, "title": "Room Mate Collection Mia, Rome Colosseum",
         "address": "Room Mate Collection Mia, Rome Colosseum, Via Capo d'Africa, Rome, Metropolitan City of Rome Capital, Italy"}
STREET = {"id": "ChIJYRHhRLhhLxMRWCwnasVpFcU", "type": None, "title": "Via Capo d'Africa, 54", "address": "Via Capo d'Africa, 54, Roma, Italy"}


def test_parse_the_real_results_page():
    parsed = parse_results(PAGE)
    assert parsed["route"] == {"from": "Rome Airport Fiumicino (FCO)", "to": "Room Mate Collection Mia, Rome Colosseum",
                               "to_address": "Room Mate Collection Mia, Rome Colosseum, Via Capo d'Africa, Rome, Metropolitan City of Rome Capital, Italy",
                               "date": "1 MAR 2027", "passengers": "3", "driving_time": "~ 29 min"}
    offers = {o["vehicle"]: o for o in parsed["offers"]}
    assert list(offers) == ["Minibus 7PAX", "Comfort", "Business", "Minivan 4PAX", "Premium Minibus"]
    assert (offers["Comfort"]["price"], offers["Comfort"]["currency"], offers["Comfort"]["max_passengers"], offers["Comfort"]["max_standard_bags"]) == (106.0, "EUR", 4, 3)
    assert offers["Minibus 7PAX"]["price"] == 138.0 and offers["Business"]["price"] == 122.0 and offers["Minivan 4PAX"]["price"] == 130.0
    assert offers["Business"]["free_cancellation_hours_before"] == 24 and offers["Premium Minibus"]["price"] == 150.0 and offers["Premium Minibus"]["max_standard_bags"] == 4
    assert offers["Comfort"]["description"] == "Sedan comfort for 4 passengers" and offers["Comfort"]["free_cancellation_hours_before"] == 16
    assert check_results(parsed, DAY, 3) == []


def test_check_results_catches_a_wrong_page():
    parsed = parse_results(PAGE)
    assert any("not '2 MAR 2027'" in p for p in check_results(parsed, date(2027, 3, 2), 3))
    assert any("not 4" in p for p in check_results(parsed, DAY, 4))
    parsed["offers"][1]["currency"] = "USD"
    assert any("not EUR" in p for p in check_results(parsed, DAY, 3))
    assert any("no vehicle" in p for p in check_results({"route": parsed["route"], "offers": []}, DAY, 3))


def test_date_label_and_prices_in_other_symbols():
    assert date_label(date(2027, 12, 31)) == "31 DEC 2027" and date_label(date(2027, 3, 1)) == "1 MAR 2027"
    from myt_mcp.kiwitaxi.parse import _price
    assert _price("€1,138.50") == (1138.5, "EUR") and _price("$163") == (163.0, "USD") and _price("from") == (None, None)


class Site:
    """Kiwitaxi's three requests, answered like the real site: only browser-like requests get the redirect."""

    def __init__(self, page=PAGE, places=None, results_status=200):
        self.requests, self.page, self.results_status = [], page, results_status
        self.places = places if places is not None else {"fiumicino": [FCO], "room mate": [HOTEL], "via capo": [STREET, HOTEL]}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/en/":
            return httpx.Response(200, text="<html></html>")
        if path == "/en/search/autocomplete":
            if request.headers.get("sec-fetch-mode") != "cors":
                return httpx.Response(404)
            text = request.url.params["input"].lower()
            found = next((v for k, v in self.places.items() if k in text), [])
            return httpx.Response(200, json=found)
        if path == "/en/product-search-v2":
            if request.headers.get("sec-fetch-mode") != "navigate":
                return httpx.Response(404, text="not found")
            return httpx.Response(302, headers={"location": "/en/italy/fiumicino-airport-rome-center-district-rome?ref=sf#transfers"})
        if path.startswith("/en/italy/"):
            return httpx.Response(self.results_status, text=self.page)
        return httpx.Response(404)


def client_for(site):
    return KiwitaxiClient(transport=httpx.MockTransport(site), limiter=SiteLimiter("Kiwitaxi", 0, 1000))


async def test_search_flow_sends_what_the_website_sends():
    site = Site()
    found = await client_for(site).search("Fiumicino", "Room Mate Collection Mia Rome", DAY, 3)
    assert found["route"]["date"] == "1 MAR 2027" and len(found["offers"]) == 5
    assert found["url"] == "https://kiwitaxi.com/en/italy/fiumicino-airport-rome-center-district-rome?ref=sf"
    assert found["chosen_from"]["id"] == "internal:374" and found["chosen_to"]["title"].startswith("Room Mate")
    places = [r for r in site.requests if r.url.path == "/en/search/autocomplete"]
    search = next(r for r in site.requests if r.url.path == "/en/product-search-v2")
    assert places[0].url.params["searchSession"] == places[1].url.params["searchSession"] == search.url.params["search_session"]
    assert places[1].url.params["pairId"] == "internal:374" and "pairId" not in places[0].url.params
    p = search.url.params
    assert (p["place_from_id"], p["place_to_id"], p["date_start"], p["passenger_count"], p["all_passenger_count"]) == ("internal:374", HOTEL["id"], "2027-03-01", "3", "3")
    assert "userCurrencyCode=EUR" in search.headers["cookie"] and search.headers["sec-fetch-mode"] == "navigate"


async def test_the_next_suggestion_can_be_chosen_and_the_same_search_is_cached():
    site = Site()
    client = client_for(site)
    found = await client.search("Fiumicino", "Via Capo d'Africa 54 Roma", DAY, 3, to_pick=1)
    assert found["chosen_to"]["title"] == HOTEL["title"] and found["other_to"] == ["Via Capo d'Africa, 54"]
    count = len(site.requests)
    await client.search("fiumicino", "via capo d'africa 54  roma", DAY, 3, to_pick=1)
    assert len(site.requests) == count                                              # answered from memory


@pytest.mark.parametrize("site,expected", [
    (Site(places={}), "knows no place for 'Fiumicino'"),
    (Site(results_status=500), "results page answered 500"),
    (Site(page="<html>please verify you are human</html>", results_status=403), "human check"),
])
async def test_problems_are_readable(site, expected):
    with pytest.raises(KiwitaxiError, match=expected):
        await client_for(site).search("Fiumicino", "Room Mate Collection Mia Rome", DAY, 3)


async def test_a_second_place_that_does_not_exist():
    site = Site(places={"fiumicino": [FCO]})
    with pytest.raises(KiwitaxiError, match="knows no place for 'Atlantis'"):
        await client_for(site).search("Fiumicino", "Atlantis", DAY, 3)


# ---------- the tool ----------

def future(days=30):
    return (date.today() + timedelta(days=days)).isoformat()


async def call(site, name="kiwitaxi_transfer_prices", settings=None, **args):
    settings = settings or Settings()
    server = create_server(settings, Services(settings, kiwitaxi=client_for(site)))
    async with Client(server) as c:
        return await c.call_tool(name, args)


async def test_tool_gives_offers_matches_and_the_cheapest_that_fits(monkeypatch):
    import myt_mcp.tools.transfers as transfers
    monkeypatch.setattr(transfers, "_today", lambda: date(2026, 10, 16))
    r = await call(Site(), from_place="Fiumicino", to_place="Room Mate Collection Mia Rome", travel_date="2027-03-01", passengers=3)
    d = r.structured_content
    assert not r.is_error and d["prices_are"].endswith("one way, in EUR") and d["passengers"] == 3
    assert d["matched_from"]["name"] == "Rome Airport Fiumicino (FCO)" and d["matched_to"]["name"].startswith("Room Mate")
    assert [(o["vehicle"], o["price"]) for o in d["offers"]][:3] == [("Comfort", 106.0), ("Business", 122.0), ("Minivan 4PAX", 130.0)]
    assert d["approx_driving_time"] == "29 min"
    assert d["at_a_glance"]["cheapest_that_fits"]["vehicle"] == "Comfort" and all(o["fits_group"] for o in d["offers"])
    assert d["offers"][3]["price"] == 138.0 and d["offers"][4]["price"] == 150.0
    assert d["end_your_answer_with"].startswith("Source: Kiwitaxi (kiwitaxi.com), checked ") and d["end_your_answer_with"].endswith(d["source"])
    assert "prepayment" in d["payment_note"] and d["checked_at"].endswith("UTC")


async def test_tool_says_when_no_vehicle_takes_the_group(monkeypatch):
    import myt_mcp.tools.transfers as transfers
    monkeypatch.setattr(transfers, "_today", lambda: date(2026, 10, 16))
    page = PAGE.replace('<p class="search-data-pax-value">3</p>', '<p class="search-data-pax-value">9</p>')
    r = await call(Site(page=page), from_place="Fiumicino", to_place="Room Mate Collection Mia Rome", travel_date="2027-03-01", passengers=9)
    assert r.structured_content["at_a_glance"]["cheapest_that_fits"] is None and "two vehicles" in r.structured_content["note"]


@pytest.mark.parametrize("extra,expected", [
    ({"from_place": " "}, "need a place name"),
    ({"from_place": "x" * 200}, "too long"),
    ({"travel_date": "2020-01-01"}, "in the past"),
    ({"passengers": 0}, "between 1 and 16"),
    ({"passengers": 17}, "between 1 and 16"),
    ({"from_match": 5}, "between 0 and 4"),
])
async def test_tool_validation(extra, expected):
    site = Site()
    args = {"from_place": "Fiumicino", "to_place": "Room Mate Collection Mia Rome", "travel_date": future(), "passengers": 3, **extra}
    r = await call(site, **args)
    assert r.is_error and expected in r.content[0].text and not site.requests


async def test_tool_kill_switch():
    r = await call(Site(), settings=Settings(kiwitaxi_enabled=False), from_place="Fiumicino", to_place="Hotel", travel_date=future(), passengers=2)
    assert r.is_error and "switched off" in r.content[0].text


async def test_a_page_for_another_date_is_not_used():
    r = await call(Site(), from_place="Fiumicino", to_place="Room Mate Collection Mia Rome", travel_date="2027-03-02", passengers=3)
    assert r.is_error and "did not match the search" in r.content[0].text


async def test_tool_says_when_kiwitaxi_has_no_transfer_for_the_route(monkeypatch):
    import myt_mcp.tools.transfers as transfers
    monkeypatch.setattr(transfers, "_today", lambda: date(2026, 10, 16))
    r = await call(Site(page="<html><body>Error 404 Page Not Found</body></html>"), from_place="Fiumicino", to_place="Room Mate Collection Mia Rome",
                   travel_date="2027-03-01", passengers=3)
    d = r.structured_content
    assert not r.is_error and d["offers"] == [] and "no private transfer" in d["note"] and d["matched_to"]["name"].startswith("Room Mate")


async def test_a_404_results_page_means_no_transfer_for_that_route(monkeypatch):
    import myt_mcp.tools.transfers as transfers
    monkeypatch.setattr(transfers, "_today", lambda: date(2026, 10, 16))
    r = await call(Site(results_status=404), from_place="Fiumicino", to_place="Room Mate Collection Mia Rome", travel_date="2027-03-01", passengers=3)
    assert not r.is_error and r.structured_content["offers"] == [] and "no private transfer" in r.structured_content["note"]


# ---------- the place Kiwitaxi suggests must look like the place typed ----------

BUDAPEST = {"id": "internal:9", "type": "airport", "title": "Budapest Airport Ferenc Liszt (BUD)", "address": "Budapest Airport Ferenc Liszt (BUD), Hungary"}
FLR = {"id": "internal:10", "type": "airport", "title": "Florence Airport (FLR)", "address": "Florence Airport (FLR), Italy"}


def test_place_matches_rejects_another_town_and_accepts_codes_and_hotels():
    from myt_mcp.kiwitaxi.parse import place_matches
    assert not place_matches("Florence Airport", BUDAPEST) and place_matches("Florence Airport", FLR)
    assert place_matches("FLR", FLR) and not place_matches("FLR", BUDAPEST) and place_matches("Fiumicino", FCO)
    assert place_matches("Room Mate Collection Mia Rome", HOTEL) and not place_matches("Furnas", {"title": "Burgas Airport (BOJ)", "address": "Burgas, Bulgaria"})
    assert place_matches("Hotel Rome", HOTEL)       # 'hotel' is a generic word: only Rome counts, Rome/Roma share their first letters


async def test_the_first_suggestion_is_skipped_when_it_is_another_town():
    site = Site(places={"florence airport": [BUDAPEST, FLR], "room mate": [HOTEL]})
    found = await client_for(site).search("Florence Airport", "Room Mate Collection Mia Rome", DAY, 3)
    assert found["chosen_from"]["title"] == "Florence Airport (FLR)"


async def test_no_suggestion_that_looks_like_the_typed_place_is_an_error_with_the_suggestions():
    site = Site(places={"florence airport": [BUDAPEST], "room mate": [HOTEL]})
    with pytest.raises(KiwitaxiError, match="Budapest Airport.*none of which looks like it.*from_match"):
        await client_for(site).search("Florence Airport", "Room Mate Collection Mia Rome", DAY, 3)
    # an explicit pick is trusted: the operator looked at the suggestions
    found = await client_for(Site(places={"florence airport": [BUDAPEST, FLR], "room mate": [HOTEL]})).search("Florence Airport", "Room Mate Collection Mia Rome", DAY, 3, from_pick=1)
    assert found["chosen_from"]["title"] == "Florence Airport (FLR)"
