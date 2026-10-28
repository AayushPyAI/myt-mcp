"""Viator parsing, client rules and the activity tools. Fixtures are trimmed copies of real viator.com page data."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services
from myt_mcp.viator.client import ViatorClient, ViatorError
from myt_mcp.viator.parse import AgeBandError, age_bands_for, availability, summarize_availability, summarize_product, summarize_search

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).with_name("fixtures")
SEARCH = json.loads((FIXTURES / "viator_search.json").read_text())
PRODUCT = json.loads((FIXTURES / "viator_product.json").read_text())
SINTRA_CHECK = json.loads((FIXTURES / "viator_availability_sintra.json").read_text())
COOKING_CHECK = json.loads((FIXTURES / "viator_availability_cooking.json").read_text())


def as_check(fixture, day, code="5383SINTRACASCAIS"):
    """A real availability answer re-labelled for the activity and day the test asks for."""
    return json.loads(json.dumps(fixture).replace("212483P5", code).replace("5383SINTRACASCAIS", code)
                      .replace("2026-10-16", day.isoformat()))


CSRF = {"headerName": "X-CSRF-TOKEN", "parameterName": "_csrf", "token": "t1"}
URL = "https://www.viator.com/tours/Lisbon/Sintra-and-Cascais-Small-Group-Day-Trip-from-Lisbon/d538-5383SINTRACASCAIS"
DAY = date.today() + timedelta(days=30)
CALENDAR = {"currencyCode": "EUR", "dates": {
    (DAY - timedelta(days=1)).isoformat(): {"formattedPrice": "€86", "isDiscounted": False},
    (DAY + timedelta(days=2)).isoformat(): {"formattedPrice": "€49", "isDiscounted": True},
}}


def test_search_rows():
    rows, total, skipped = summarize_search(SEARCH["state"], SEARCH["urls"], 2)
    assert len(rows) == 2 and total > 2 and skipped == 0
    first = rows[0]
    assert first["code"] == "5383SINTRACASCAIS" and first["currency"] == "EUR" and first["from_price"] > 0
    assert first["url"] == URL and first["rating"] and first["reviews"] and first["duration"] == "8h"


def test_search_skips_broken_items():
    state = {"__PRELOADED_DATA__": {"pageModel": {"preloadedData": {"search": {"results": [{"item": None}, "x"]}}}}}
    assert summarize_search(state, {}, 5) == ([], 0, 2)


def test_product_details():
    d = summarize_product(PRODUCT, CALENDAR, DAY)
    assert (d["code"], d["supplier"], d["duration"], d["starts_at"]) == ("5383SINTRACASCAIS", "Inside Lisbon", "8h", "8:00 AM")
    assert d["meeting_points"][0]["name"] == "Hard Rock Cafe | Lisbon" and d["pickup_offered"] is False
    assert d["included"] and d["not_included"] and d["cancellation_policy"][0].startswith("For a full refund")
    assert "English" in d["languages"] and {a["band"] for a in d["age_bands"]} >= {"ADULT", "CHILD"}
    assert len(d["options"]) == 5


def test_availability_on_a_date():
    assert availability(CALENDAR, DAY - timedelta(days=1))["price_per_person_from"] == "€86"
    missing = availability(CALENDAR, DAY)
    assert missing["available"] is False and len(missing["nearest_available_dates"]) == 2
    assert availability({}, DAY)["available"] is False
    assert len(availability(CALENDAR, None)["next_available_dates"]) == 2


def test_age_bands_follow_the_activity():
    assert age_bands_for(PRODUCT, 2, [7, 2, 14]) == {"ADULT": 3, "CHILD": 1, "INFANT": 1}   # 14 is an adult here (12-99)
    assert age_bands_for(PRODUCT, 0, [5]) == {"CHILD": 1}
    with pytest.raises(AgeBandError, match="aged 1"):
        age_bands_for({"availabilityConfig": {"ageBandRanges": [{"ageBand": "ADULT", "ageMin": 18, "ageMax": 99}]}}, 2, [1])


def test_availability_check_summary():
    d = summarize_availability(COOKING_CHECK)
    first = d["options"][0]
    assert d["any_available"] and first["available"] and first["total_price_from"] == 50.0
    assert [t["time"] for t in first["start_times"]] == ["10:00 AM", "2:30 PM", "6:30 PM"]
    assert first["start_times"][2]["total_price"] == 138.0 and first["price_per_traveller"][0]["age_group"] == "ADULT"
    assert d["options"][-1]["available"] is False and d["options"][-1]["total_price_from"] is None
    assert (d["refundable"], d["free_cancellation_until"]) == (True, "2026-10-15")
    sold_out = summarize_availability(SINTRA_CHECK)
    assert not sold_out["any_available"] and sold_out["options"][0]["total_price_from"] == 140.0   # price kept, cheapest first


class FakePage:
    def __init__(self, pages, visits):
        self.pages, self.visits, self.url = pages, visits, None

    async def goto(self, url, **_):
        self.url = url
        self.visits.append(url)

    async def wait_for_timeout(self, _):
        pass

    async def evaluate(self, _script):
        return self.pages(self.url)


class FakeSession:
    """Stands in for the automation browser: returns prepared page data instead of opening viator.com."""

    def __init__(self, pages, calendar=CALENDAR, calendar_status=200, checks=None):
        self.visits, self.fetches, self.posts = [], [], []
        self._page = FakePage(pages, self.visits)
        self._calendar, self._status = calendar, calendar_status
        self._checks = list(checks or [(200, COOKING_CHECK)])

    async def run(self, origin, start_url, action):
        return await action(self._page)

    async def fetch(self, origin, start_url, method, url, body=None, headers=None):
        self.fetches.append(url)
        if method == "POST":
            self.posts.append((body, headers))
            status, answer = self._checks.pop(0)
            return {"status": status, "url": url, "text": json.dumps(answer)}
        return {"status": self._status, "url": url, "text": json.dumps(self._calendar)}


def page_data(url):
    if "/searchResults/" in url:
        return {"state": json.dumps(SEARCH["state"]), "urls": SEARCH["urls"], "currency": "EUR", "blocked": False}
    state = {"__PRELOADED_DATA__": {"pageModel": {"product": PRODUCT}, "csrf": CSRF}}
    return {"state": json.dumps(state), "urls": {}, "currency": "EUR", "blocked": False}


def server_with(session, settings=None):
    settings = settings or Settings()
    client = ViatorClient(session, limiter=SiteLimiter("Viator", 0, 1000))
    return create_server(settings, Services(settings, viator=client))


async def test_search_tool_and_cache():
    session = FakeSession(page_data)
    async with Client(server_with(session)) as c:
        r = await c.call_tool("viator_search_activities", {"query": "Sintra day trip", "max_results": 2})
        await c.call_tool("viator_search_activities", {"query": "  sintra DAY trip "})
    d = r.structured_content
    assert len(d["activities"]) == 2 and "warning" not in d
    assert len(session.visits) == 1   # same search answered from cache


async def test_details_tool_with_group_check():
    session = FakeSession(page_data, checks=[(200, as_check(COOKING_CHECK, DAY + timedelta(days=2)))])
    args = {"url": URL, "activity_date": (DAY + timedelta(days=2)).isoformat(), "adults": 2, "child_ages": [8]}
    async with Client(server_with(session)) as c:
        r = await c.call_tool("viator_activity_details", args)
        await c.call_tool("viator_activity_details", args)
    d = r.structured_content
    assert d["availability"]["available"] is True and d["availability"]["price_per_person_from"] == "€49"
    group = d["for_your_group"]
    assert group["travellers"] == {"ADULT": 2, "CHILD": 1} and group["options"][0]["total_price_from"] == 50.0
    body, headers = session.posts[0]
    assert body == {"productCode": "5383SINTRACASCAIS", "searchDate": args["activity_date"], "ageBands": {"ADULT": "2", "CHILD": "1"}}
    assert headers == {"X-Requested-With": "XMLHttpRequest", "X-CSRF-TOKEN": "t1"}
    assert len(session.posts) == 1 and len(session.visits) == 1   # repeated check answered from cache


async def test_details_without_date_skips_the_check():
    session = FakeSession(page_data)
    async with Client(server_with(session)) as c:
        r = await c.call_tool("viator_activity_details", {"url": URL})
    assert "for_your_group" not in r.structured_content and not session.posts


async def test_expired_token_reloads_the_page_once():
    session = FakeSession(page_data, checks=[(403, {}), (200, SINTRA_CHECK)])
    client = ViatorClient(session, limiter=SiteLimiter("Viator", 0, 1000))
    answer = await client.check_availability(URL, DAY, {"ADULT": 2})
    assert answer is not None and len(session.posts) == 2 and len(session.visits) == 2


@pytest.mark.parametrize("checks,expected", [
    ([(403, {}), (403, {})], "answered 403"),
    ([(200, {"validationErrors": {"date": "bad"}})], "did not accept"),
])
async def test_check_failures_are_readable(checks, expected):
    client = ViatorClient(FakeSession(page_data, checks=checks), limiter=SiteLimiter("Viator", 0, 1000))
    with pytest.raises(ViatorError, match=expected):
        await client.check_availability(URL, DAY, {"ADULT": 2})


async def test_missing_calendar_is_flagged():
    async with Client(server_with(FakeSession(page_data, calendar_status=403))) as c:
        r = await c.call_tool("viator_activity_details", {"url": URL})
    assert "did not return its price calendar" in r.structured_content["availability"]["note"]


async def test_other_currency_is_not_used():
    def inr(url):
        return {**page_data(url), "currency": "INR"}

    async with Client(server_with(FakeSession(inr))) as c:
        r = await c.call_tool("viator_search_activities", {"query": "Sintra"})
    assert r.is_error and "not EUR" in r.content[0].text and "was not used" in r.content[0].text


async def test_page_of_another_activity_is_not_used():
    other = URL.replace("5383SINTRACASCAIS", "9999OTHER")
    async with Client(server_with(FakeSession(page_data))) as c:
        r = await c.call_tool("viator_activity_details", {"url": other})
    assert r.is_error and "not 9999OTHER" in r.content[0].text


async def test_group_check_for_other_travellers_is_not_used():
    bookable = DAY + timedelta(days=2)   # a day in the activity's calendar
    session = FakeSession(page_data, checks=[(200, as_check(COOKING_CHECK, bookable))])   # priced for 2 adults + 1 child
    args = {"url": URL, "activity_date": bookable.isoformat(), "adults": 3}
    async with Client(server_with(session)) as c:
        r = await c.call_tool("viator_activity_details", args)
    assert r.is_error and "did not match the search" in r.content[0].text


@pytest.mark.parametrize("page", [
    {"state": None, "urls": {}, "blocked": False},
    {"state": "{}", "urls": {}, "blocked": True},
])
async def test_captcha_or_empty_page_stops(page):
    client = ViatorClient(FakeSession(lambda _: page), limiter=SiteLimiter("Viator", 0, 1000))
    with pytest.raises(ViatorError, match="human check"):
        await client.search("Sintra")


async def test_page_without_activity_data():
    page = {"state": json.dumps({"__PRELOADED_DATA__": {"pageModel": {}}}), "urls": {}, "blocked": False}
    client = ViatorClient(FakeSession(lambda _: page), limiter=SiteLimiter("Viator", 0, 1000))
    with pytest.raises(ViatorError, match="no activity data"):
        await client.product(URL)


@pytest.mark.parametrize("tool,args,expected", [
    ("viator_search_activities", {"query": " "}, "query is empty"),
    ("viator_search_activities", {"query": "pasta", "max_results": 61}, "between 1 and 60"),
    ("viator_search_activities", {"query": "pasta", "pages": 10}, "pages must be between 1 and 9"),
    ("viator_search_activities", {"query": "pasta", "sort_by": "cheapest"}, "sort_by must be one of"),
    ("viator_search_activities", {"query": "pasta", "max_price": 0}, "max_price must be more than 0"),
    ("viator_search_activities", {"query": "pasta", "min_rating": 6}, "min_rating must be between"),
    ("viator_activity_details", {"url": "https://www.getyourguide.com/x"}, "Viator activity link"),
    ("viator_activity_details", {"url": URL, "activity_date": "2020-01-01"}, "in the past"),
    ("viator_activity_details", {"url": URL, "adults": 0}, "1-15 people"),
    ("viator_activity_details", {"url": URL, "child_ages": [19]}, "ages 0-17"),
])
async def test_input_validation(tool, args, expected):
    session = FakeSession(page_data)
    async with Client(server_with(session)) as c:
        r = await c.call_tool(tool, args)
    assert r.is_error and expected in r.content[0].text and not session.visits


async def test_viator_kill_switch():
    async with Client(server_with(FakeSession(page_data), Settings(viator_enabled=False))) as c:
        r = await c.call_tool("viator_search_activities", {"query": "Sintra"})
    assert r.is_error and "switched off" in r.content[0].text


async def test_date_outside_the_calendar_gets_no_group_price():
    session = FakeSession(page_data, checks=[(200, as_check(COOKING_CHECK, DAY))])   # the check would say "available"
    async with Client(server_with(session)) as c:
        r = await c.call_tool("viator_activity_details", {"url": URL, "activity_date": DAY.isoformat(), "adults": 2})
    group = r.structured_content["for_your_group"]
    assert group["any_available"] is False and "does not list this date" in group["note"] and not session.posts
    assert r.structured_content["availability"]["available"] is False


@pytest.mark.parametrize("query", ["\"'<>&%$#@!", "🍝🍝", "?", "a" * 300])
async def test_search_text_must_be_sane(query):
    session = FakeSession(page_data)
    async with Client(server_with(session)) as c:
        r = await c.call_tool("viator_search_activities", {"query": query})
    assert r.is_error and not session.visits


async def test_unrelated_results_are_flagged():
    async with Client(server_with(FakeSession(page_data))) as c:
        r = await c.call_tool("viator_search_activities", {"query": "underwater basket weaving"})
        ok = await c.call_tool("viator_search_activities", {"query": "Sintra day trip"})
    assert "None of these results contain the words you searched" in r.structured_content["warning"]
    assert "warning" not in ok.structured_content


async def test_viator_error_page_is_reported_as_such():
    class ErrorPage(FakePage):
        async def goto(self, url, **_):
            raise RuntimeError("Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE at https://www.viator.com/x")

    class ErrorSession(FakeSession):
        def __init__(self):
            super().__init__(page_data)
            self._page = ErrorPage(page_data, self.visits)

    client = ViatorClient(ErrorSession(), limiter=SiteLimiter("Viator", 0, 1000))
    with pytest.raises(ViatorError, match="error page"):
        await client.search("pasta")


def test_product_codes_with_underscore_or_dot_are_read_from_links():
    from myt_mcp.viator.parse import code_from_url
    assert code_from_url("https://www.viator.com/tours/Florence/Pizza-Class/d519-5049ITALY_PIZZA") == "5049ITALY_PIZZA"
    assert code_from_url("https://www.viator.com/tours/Florence/Pasta/d519-212483P5?pid=P0") == "212483P5"
    assert code_from_url("https://www.viator.com/tours/Rome/Tour/d511-12.5P3/") == "12.5P3"
    assert code_from_url("https://www.viator.com/tours/Rome/") is None


async def test_search_warns_when_a_result_has_no_link():
    def no_urls(url):
        data = page_data(url)
        if "/searchResults/" in url:
            data["urls"] = {}
        return data

    async with Client(server_with(FakeSession(no_urls))) as c:
        r = await c.call_tool("viator_search_activities", {"query": "Sintra day trip", "max_results": 2})
    d = r.structured_content
    assert all(a["url"] is None for a in d["activities"]) and "no activity link" in d["warning"] and "do not guess" in d["warning"]


def test_viator_shows_the_list_price_next_to_the_discounted_price():
    from myt_mcp.viator.parse import _before_discount, _paid

    discounted = {"discountedPrice": {"amount": 80.0}, "retailPrice": {"amount": 100.0}}
    assert _paid(discounted) == 80.0 and _before_discount(discounted) == 100.0
    assert _before_discount({"retailPrice": {"amount": 100.0}}) is None                       # no discount
    assert _before_discount({"discountedPrice": {"amount": 100.0}, "retailPrice": {"amount": 100.0}}) is None
    assert _before_discount(None) is None



# ---- many pages, sorting and filters -------------------------------------------------------------------------------

def _item(code, price, rating, reviews, minutes, free):
    return {"result": {"item": {
        "productCode": code, "title": {"text": f"Pasta class {code}"}, "primaryDestination": {"name": "Florence"},
        "pricingInfo": {"fromPrice": {"amount": price, "currency": "EUR"}, "priceVariesByGroupSize": False},
        "reviewSummary": {"exactRating": rating, "count": reviews},
        "itinerary": {"duration": {"unit": "MINUTES", "duration": minutes}},
        "cancellationPolicy": {"freeCancellation": free}, "offeredLanguages": [], "productBadges": [], "description": {"text": "pasta"},
    }}, "url": f"https://www.viator.com/tours/Florence/Pasta-{code}/d519-{code}"}


def _paged_pages(total_pages, last_page_rows=24, fail_on=None):
    """A fake Viator: page n has 24 'pasta' classes (the last page fewer); prices fall as the code number rises."""
    def pages(url):
        n = 1
        if "/searchResults/all/" in url:
            n = int(url.split("/searchResults/all/")[1].split("?")[0])
        if fail_on == n:
            raise ViatorError("Viator answered with an error page for this request (it may not accept this search text or this link). Try other words.")
        count = last_page_rows if n == total_pages else 24
        items = [_item(f"P{n}x{i}", 100 - (n - 1) * 24 - i, 4.0 + (i % 10) / 10, 10 * (i + 1), 60 + 30 * (i % 6), i % 2 == 0) for i in range(count)]
        state = {"__PRELOADED_DATA__": {"pageModel": {"preloadedData": {"search": {
            "totalResults": 200, "results": [i["result"] for i in items]}}}}}
        return {"state": json.dumps(state), "urls": {i["result"]["item"]["productCode"]: i["url"] for i in items}, "currency": "EUR", "blocked": False}
    return pages


async def _search(pages_fn, **args):
    session = FakeSession(pages_fn)
    async with Client(server_with(session)) as c:
        r = await c.call_tool("viator_search_activities", {"query": "pasta class", **args})
    return r, session


async def test_pages_are_read_through_viators_paging_urls():
    r, session = await _search(_paged_pages(9), pages=3, max_results=60)
    d = r.structured_content
    assert [v.split("viator.com")[1] for v in session.visits] == [
        "/searchResults/all?text=pasta%20class", "/searchResults/all/2?text=pasta%20class", "/searchResults/all/3?text=pasta%20class"]
    assert d["coverage"] == {"pages_read": 3, "results_read": 72, "total_on_viator": 200, "all_results_read": False, "passed_filters": 72, "shown": 60}
    assert "Read 72 of 200+" in d["note"] and "never just 'the cheapest'" in d["note"]
    assert d["price_range_of_results_read"]["min"] == 29 and d["price_range_of_results_read"]["max"] == 100


async def test_reading_stops_at_the_last_page():
    r, session = await _search(_paged_pages(2, last_page_rows=10), pages=9)
    assert len(session.visits) == 2 and r.structured_content["coverage"]["results_read"] == 34


async def test_sort_by_price_puts_the_cheapest_of_all_pages_first():
    r, _ = await _search(_paged_pages(3), pages=3, sort_by="price", max_results=3)
    assert [a["from_price"] for a in r.structured_content["activities"]] == [29, 30, 31]       # from page 3, not page 1


async def test_other_sorts_and_filters():
    r, _ = await _search(_paged_pages(1), sort_by="rating", max_results=2)
    assert [a["rating"] for a in r.structured_content["activities"]] == [4.9, 4.9]
    r, _ = await _search(_paged_pages(1), sort_by="duration", max_results=1)
    assert r.structured_content["activities"][0]["duration"] == "1h"
    r, _ = await _search(_paged_pages(1), max_price=80, free_cancellation_only=True, min_rating=4.5, max_hours=2, sort_by="price", max_results=60)
    rows = r.structured_content["activities"]
    assert rows and all(a["from_price"] <= 80 and a["free_cancellation"] and a["rating"] >= 4.5 for a in rows)
    assert all(a["duration"] in ("1h", "1h 30m", "2h") for a in rows)
    assert [a["from_price"] for a in rows] == sorted(a["from_price"] for a in rows)
    assert r.structured_content["coverage"]["passed_filters"] == len(rows) < 24


async def test_filters_that_remove_everything_say_so():
    r, _ = await _search(_paged_pages(1), max_price=1)
    assert r.structured_content["activities"] == [] and "passes the filters" in r.structured_content["note"]


async def test_a_failing_later_page_gives_a_partial_answer_with_a_warning():
    r, session = await _search(_paged_pages(9, fail_on=3), pages=4)
    d = r.structured_content
    assert not r.is_error and d["coverage"]["pages_read"] == 2 and d["coverage"]["results_read"] == 48
    assert "page 3 could not be read" in d["warning"]


async def test_a_failing_first_page_is_an_error():
    r, _ = await _search(_paged_pages(9, fail_on=1))
    assert r.is_error and "error page" in r.content[0].text


def test_duration_and_price_helpers():
    from myt_mcp.viator.parse import duration_minutes, price_range
    assert duration_minutes("2h 30m") == 150 and duration_minutes("1h 30m \u2013 2h") == 90 and duration_minutes("45m") == 45 and duration_minutes(None) is None
    assert price_range([{"from_price": 10}, {"from_price": 30}, {"from_price": 20}, {"from_price": 100}]) == {"min": 10, "median": 25.0, "max": 100, "of_results": 4, "currency": "EUR"}
    assert price_range([{"from_price": None}]) is None


def test_rating_sort_puts_results_with_fewer_than_20_reviews_last():
    from myt_mcp.viator.parse import sort_rows
    rows = [{"code": "a", "rating": 5.0, "reviews": 1}, {"code": "b", "rating": 4.9, "reviews": 8813},
            {"code": "c", "rating": 4.6, "reviews": 20}, {"code": "d", "rating": None, "reviews": None}, {"code": "e", "rating": 5.0, "reviews": 19}]
    assert [r["code"] for r in sort_rows(rows, "rating")] == ["b", "c", "e", "a", "d"]


async def test_rows_are_ranked_flagged_and_listed_for_an_exact_price_check():
    r, _ = await _search(_paged_pages(1), sort_by="rating", max_results=60)
    d = r.structured_content
    rows = d["activities"]
    assert [a["rank"] for a in rows] == list(range(1, len(rows) + 1)) and "rank" in d["show_rows"]
    assert all(a["few_reviews"] == ((a["reviews"] or 0) < 20) for a in rows)
    few = [i for i, a in enumerate(rows) if a["few_reviews"]]
    assert few == list(range(len(rows) - len(few), len(rows)))                    # results with few reviews come last
    picks = d["shortlist_for_exact_price"]
    assert 1 <= len(picks) <= 3 and all(p["reviews"] >= 20 and p["url"] for p in picks) and picks[0]["why"].startswith("Cheapest of the ") and "read, with 20+ reviews" in picks[0]["why"]
    solid = [a for a in rows if not a["few_reviews"] and a["from_price"] is not None]
    assert picks[0]["from_price"] == min(a["from_price"] for a in solid)


async def test_title_contains_keeps_only_matching_titles():
    r, _ = await _search(_paged_pages(1), title_contains=["zzz-no-such-word"])
    assert r.structured_content["activities"] == [] and r.structured_content["filters"]["title_contains"] == ["zzz-no-such-word"]
    r, _ = await _search(_paged_pages(1), max_results=60)
    word = r.structured_content["activities"][0]["title"].split()[0].lower().strip(":,")
    r, _ = await _search(_paged_pages(1), max_results=60, title_contains=[word])
    assert r.structured_content["activities"] and all(word in a["title"].lower() for a in r.structured_content["activities"])


def test_a_one_word_query_is_searched_as_x_tours_so_viator_does_not_redirect_to_the_destination_page():
    """28 Oct 2026, checked in the server's Chrome: 'Lisbon' ends on viator.com/Lisbon/d538-ttd (other card layout, no 'Showing N - M of' line); 'Lisbon tours' stays on the search page."""
    from myt_mcp.sites.viator_find import viator_find_recipe
    one = viator_find_recipe("Lisbon", "7 Mar 2027")
    assert one["url"].endswith("/searchResults/all?text=Lisbon+tours") and one["expect"]["query"] == "Lisbon tours"
    assert one["expect"]["title_contains"] == ["lisbon"] and one["expect"]["group"] == "Lisbon, 7 Mar 2027"          # the title words stay the operator's own
    many = viator_find_recipe("Florence golf cart tour")
    assert many["url"].endswith("text=Florence+golf+cart+tour") and many["expect"]["query"] == "Florence golf cart tour"
