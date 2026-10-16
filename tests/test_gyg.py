"""GetYourGuide activity details: parsing, group categories, checks and the tool. Fixtures are real answers."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.gyg.client import GygClient, GygError
from myt_mcp.gyg.parse import (AgeGroupError, activity_id_from_url, activity_info, check_availability, check_search, group_note, long_date,
                               parse_availability, participants_for, search_page, shortlist, sort_rows, state_from_script, duration_minutes)
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

FIX = Path(__file__).with_name("fixtures")
STATE = json.loads((FIX / "gyg_page_state.json").read_text())
TWO_ADULTS = json.loads((FIX / "gyg_availability_2adults.json").read_text())
WITH_CHILD = json.loads((FIX / "gyg_availability_2adults_1child.json").read_text())
NONE = json.loads((FIX / "gyg_availability_none.json").read_text())
SEARCH_PAGE = json.loads((FIX / "gyg_search_page.json").read_text())
SINGLE_OPTION = json.loads((FIX / "gyg_availability_single_option.json").read_text())
URL = "https://www.getyourguide.com/florence-l32/florence-pasta-cooking-class-with-unlimited-wine-t552524/"
CONNECTOR_URL = URL + "?psrc=widget&partner_id=F71L4IS&currency=EUR&visitor_id=DBEA&date_from=2026-10-19"
OCT19 = date(2026, 10, 19)   # the day the fixtures were captured for


def test_page_info():
    info = activity_info(STATE)
    assert info["activity_id"] == 552524 and info["visitor_id"]
    assert [(c["id"], c["name"], c["min_age"], c["max_age"]) for c in info["categories"]] == [(1, "Adult", 4, 99), (3, "Child", 0, 3)]
    assert info["highlights"][0].startswith("Create 3 types of fresh pasta") and "Tuscan wine" in info["includes"]
    assert info["cancellation"] == "Cancel up to 24 hours in advance for a full refund"


def test_activity_id_from_link():
    assert activity_id_from_url(URL) == 552524 and activity_id_from_url(CONNECTOR_URL) == 552524
    assert activity_id_from_url("https://www.getyourguide.com/florence-l32/") is None


def test_state_from_script_text():
    assert state_from_script("window.__INITIAL_STATE__ = " + json.dumps({"a": {"b": 1}}) + ";\nfoo()") == {"a": {"b": 1}}


@pytest.mark.parametrize("adults,ages,expected", [
    (2, [], {"Adult": 2}),
    (2, [8], {"Adult": 3}),                 # on this activity Adult is 4-99
    (2, [2], {"Adult": 2, "Child": 1}),     # Child is 0-3
    (1, [3, 4], {"Adult": 2, "Child": 1}),
    (0, [1], {"Child": 1}),
])
def test_travellers_go_to_the_activitys_own_groups(adults, ages, expected):
    categories = activity_info(STATE)["categories"]
    participants, names = participants_for(categories, adults, ages)
    assert names == expected and sum(p["count"] for p in participants) == adults + len(ages)
    assert {p["categoryId"] for p in participants} == {1, 3}   # every group is sent, zeros included


def test_age_no_group_takes():
    cats = [{"id": 1, "name": "Adult", "min_age": 18, "max_age": 99}]
    with pytest.raises(AgeGroupError, match="aged 5"):
        participants_for(cats, 2, [5])
    with pytest.raises(AgeGroupError, match="traveller categories"):
        participants_for([], 2, [])


def test_options_start_times_and_group_price():
    parsed = parse_availability(TWO_ADULTS)
    assert parsed["any_available"] and parsed["dates_seen"] == [long_date(OCT19)]
    first = parsed["options"][0]
    assert first["option"].startswith("Pasta Cooking Class with Unlimited Wine at Cucciolo")
    assert (first["duration"], first["language"], first["cancellation"]) == ("2 hours", "English", "Cancel for free until Oct 18")
    assert first["meeting_point"].startswith("Via dei Cerchi, 33 R") and first["pay_later"]
    assert [t["time"] for t in first["start_times"]] == ["10:05 AM", "1:05 PM", "4:05 PM", "7:05 PM"]
    t = first["start_times"][0]
    assert (t["total_price"], t["price_before_discount"], t["discount"], t["currency"]) == (36.0, 72.0, "-50%", "EUR")
    assert t["price_lines"] == [{"travellers": 2, "group": "Adult", "price_each": 18.0}] and t["taxes_included"]
    assert check_availability(parsed, OCT19, 2) == []
    assert "no start times" in parsed["options"][-1]["note"]   # options GetYourGuide lists without times say so


def test_a_child_can_be_charged_as_an_adult():
    parsed = parse_availability(WITH_CHILD)
    assert check_availability(parsed, OCT19, 3) == []
    requested = {"Adult": 2, "Child": 1}
    notes = {o["option"][:12]: group_note(o, requested) for o in parsed["options"] if o["start_times"]}
    assert notes["Handmade Pas"] is None                       # this option has a Child price (free)
    assert "priced this option as 3 Adult" in notes["Pasta Cookin"]


def test_unavailable_day():
    parsed = parse_availability(NONE)
    assert parsed["any_available"] is False and parsed["options"] == [] and "not available" in parsed["note"].lower()


@pytest.mark.parametrize("day,travellers,expected", [
    (OCT19 + timedelta(days=1), 2, "not Tuesday, October 20, 2026"),   # answer is for another day
    (OCT19, 3, "priced for 2 travellers, not 3"),                       # another group
])
def test_checks_catch_a_mismatch(day, travellers, expected):
    problems = check_availability(parse_availability(TWO_ADULTS), day, travellers)
    assert any(expected in p for p in problems)


def test_checks_catch_wrong_totals():
    parsed = parse_availability(TWO_ADULTS)
    parsed["options"][0]["start_times"][0]["total_price"] += 5
    assert any("does not add up" in p for p in check_availability(parsed, OCT19, 2))


# ---------- client and tool ----------

class FakePage:
    def __init__(self, session):
        self.session, self.url = session, None

    async def goto(self, url, **_):
        self.session.visits.append(url)

    async def wait_for_timeout(self, _):
        pass

    async def wait_for_selector(self, *_a, **_k):
        pass

    async def evaluate(self, _script):
        return self.session.read


class FakeSession:
    def __init__(self, answers=None, read=None, status=200):
        self.visits, self.posts = [], []
        self.read = read or {"script": "window.__INITIAL_STATE__ = " + json.dumps(STATE), "title": "Florence: Pasta Cooking Class with Unlimited Wine", "body": ""}
        self._answers, self._status = list(answers or [TWO_ADULTS]), status

    async def run(self, origin, start_url, action):
        return await action(FakePage(self))

    async def fetch(self, origin, start_url, method, url, body=None, headers=None):
        self.posts.append((url, body, headers))
        return {"status": self._status, "url": url, "text": json.dumps(self._answers.pop(0))}


def server_with(session, settings=None):
    settings = settings or Settings()
    client = GygClient(session, limiter=SiteLimiter("GetYourGuide", 0, 1000))
    return create_server(settings, Services(settings, gyg=client))


def args(**extra):
    return {"url": CONNECTOR_URL, "activity_date": OCT19.isoformat(), **extra}


@pytest.fixture
def today_is_before_fixture_date(monkeypatch):
    import myt_mcp.tools.activities as activities
    monkeypatch.setattr(activities, "_today", lambda: date(2026, 10, 13))


async def test_tool_group_prices_and_request(today_is_before_fixture_date):
    session = FakeSession()
    async with Client(server_with(session)) as c:
        r = await c.call_tool("getyourguide_activity_details", args(adults=2))
        await c.call_tool("getyourguide_activity_details", args(adults=2))
    d = r.structured_content
    assert d["travellers"] == {"Adult": 2} and d["any_available"] and d["prices_are_for"].startswith("the whole group together")
    assert d["options"][0]["start_times"][0]["total_price"] == 36.0 and d["checked_at"].endswith("UTC")
    assert d["activity_url"] == URL and d["traveller_groups"][0] == {"name": "Adult", "ages": "4-99"}
    assert d["highlights"] and d["includes"] and d["cancellation"].startswith("Cancel up to 24 hours")
    assert d["end_your_answer_with"].startswith("Source: GetYourGuide, checked ") and d["end_your_answer_with"].endswith(URL)      # source link inside the line
    url, body, headers = session.posts[0]
    assert url.endswith("blocks?date_from=2026-10-19") and headers["accept-currency"] == "EUR"
    assert body["events"][1]["event"]["payload"]["participants"] == [{"categoryId": 1, "count": 2}, {"categoryId": 3, "count": 0}]
    assert body["payload"]["activityId"] == 552524
    assert len(session.posts) == 1 and len(session.visits) == 1                  # the repeat came from the cache
    assert session.visits[0] == URL + "?currency=EUR"                           # tracking parameters removed


async def test_tool_child_charged_as_adult_is_explained(today_is_before_fixture_date):
    session = FakeSession(answers=[WITH_CHILD])
    async with Client(server_with(session)) as c:
        r = await c.call_tool("getyourguide_activity_details", args(adults=2, child_ages=[2]))
    d = r.structured_content
    assert d["travellers"] == {"Adult": 2, "Child": 1}
    assert "price_note" not in d["options"][0] or d["options"][0]["option"].startswith("Handmade")
    assert any("priced this option as 3 Adult" in o.get("price_note", "") for o in d["options"])


async def test_unavailable_day_gives_a_note(today_is_before_fixture_date):
    async with Client(server_with(FakeSession(answers=[NONE]))) as c:
        r = await c.call_tool("getyourguide_activity_details", args())
    assert r.structured_content["any_available"] is False and "not available" in r.structured_content["note"].lower()


async def test_answer_for_another_day_is_not_used(today_is_before_fixture_date):
    async with Client(server_with(FakeSession())) as c:
        r = await c.call_tool("getyourguide_activity_details", {"url": CONNECTOR_URL, "activity_date": (OCT19 + timedelta(days=1)).isoformat()})
    assert r.is_error and "did not match the search" in r.content[0].text


@pytest.mark.parametrize("extra,expected", [
    ({"url": "https://www.viator.com/tours/a/b/d1-X"}, "GetYourGuide activity link"),
    ({"url": "https://www.getyourguide.com/florence-l32/"}, "GetYourGuide activity link"),
    ({"url": "https://evil.test/https://www.getyourguide.com/x-t1/"}, "GetYourGuide activity link"),
    ({"activity_date": "2020-01-01"}, "in the past"),
    ({"adults": 0}, "1-15 people"),
    ({"adults": 16}, "1-15 people"),
    ({"child_ages": [18]}, "ages 0-17"),
    ({"child_ages": [-1]}, "ages 0-17"),
])
async def test_input_validation(extra, expected, today_is_before_fixture_date):
    session = FakeSession()
    async with Client(server_with(session)) as c:
        r = await c.call_tool("getyourguide_activity_details", {**args(), **extra})
    assert r.is_error and expected in r.content[0].text and not session.visits


@pytest.mark.parametrize("read,expected", [
    ({"script": None, "title": None, "body": "please verify you are human"}, "human check"),
    ({"script": None, "title": None, "body": "welcome"}, "no activity data"),
    ({"script": "window.__INITIAL_STATE__ = {broken", "title": None, "body": ""}, "unexpected format"),
])
async def test_page_problems_are_readable(read, expected):
    client = GygClient(FakeSession(read=read), limiter=SiteLimiter("GetYourGuide", 0, 1000))
    with pytest.raises(GygError, match=expected):
        await client.page(URL)


async def test_page_of_another_activity_is_refused():
    client = GygClient(FakeSession(), limiter=SiteLimiter("GetYourGuide", 0, 1000))
    with pytest.raises(GygError, match="not 999"):
        await client.page(URL.replace("t552524", "t999"))


@pytest.mark.parametrize("status,expected", [(403, "refused"), (429, "refused"), (500, "answered 500")])
async def test_availability_errors(status, expected):
    client = GygClient(FakeSession(status=status), limiter=SiteLimiter("GetYourGuide", 0, 1000))
    info = await client.page(URL)
    with pytest.raises(GygError, match=expected):
        await client.availability(URL, info, OCT19, [{"categoryId": 1, "count": 2}])


async def test_gyg_kill_switch(today_is_before_fixture_date):
    async with Client(server_with(FakeSession(), Settings(gyg_enabled=False))) as c:
        r = await c.call_tool("getyourguide_activity_details", args())
    assert r.is_error and "switched off" in r.content[0].text


async def test_unknown_activity_page_is_refused():
    state = {"activity": {"id": 212483, "title": None}, "sdui": {}}
    read = {"script": "window.__INITIAL_STATE__ = " + json.dumps(state), "title": "Lost your way?", "body": ""}
    client = GygClient(FakeSession(read=read), limiter=SiteLimiter("GetYourGuide", 0, 1000))
    with pytest.raises(GygError, match="no activity with id 212483"):
        await client.page(URL.replace("t552524", "t212483"))


def test_single_option_answer_is_read():
    """One option is announced as '1 option available' (not 'Choose from N options'); it was read as no availability."""
    parsed = parse_availability(SINGLE_OPTION)
    assert parsed["any_available"] and len(parsed["options"]) == 1
    option = parsed["options"][0]
    assert [(t["time"], t["total_price"]) for t in option["start_times"]] == [("11:00 AM", 44.0), ("2:00 PM", 58.0), ("6:00 PM", 58.0)]
    assert option["meeting_point"].startswith("Via dell'Anguillara") and option["cancellation"] == "Cancel for free until Mar 2"
    assert check_availability(parsed, date(2027, 3, 3), 2) == []


# ---------- find activities (search service answers, EUR) ----------

def test_search_page_from_a_real_answer():
    rows, total = search_page(SEARCH_PAGE)
    assert total == 573 and len(rows) == 6 and check_search(rows) == []
    first = rows[0]
    assert (first["activity_id"], first["title"], first["duration"], first["rating"], first["reviews"]) == (
        552524, "Florence: Pasta Cooking Class with Unlimited Wine", "2 - 2.5 hours", 4.8, 16683)
    assert (first["from_price"], first["currency"], first["price_basis"], first["free_cancellation"]) == (36.0, "EUR", "per person", True)
    assert first["url"] == URL and first["city"] == "Florence" and first["details"] == ["Wheelchair accessible"]
    assert first["available_on_date"] == "Available 3/3/27" and first["first_start"].startswith("2027-03-03T10:00")
    assert rows[1]["details"] == ["Private option available"] and rows[1]["badges"] == ["Top rated"]
    group = rows[2]
    assert group["price_basis"] == "per group" and group["from_price"] == 118.0 and group["rating"] is None and group["reviews"] is None


def test_search_page_without_a_grid_is_empty():
    assert search_page({"content": [], "trackingEvents": []}) == ([], None)


def test_duration_minutes_and_sort():
    assert [duration_minutes(x) for x in ("2 - 2.5 hours", "45 minutes", "11 days", "3 hours", None, "odd")] == [120, 45, 15840, 180, None, None]
    rows, _ = search_page(SEARCH_PAGE)
    ids = lambda by: [r["activity_id"] for r in sort_rows(rows, by)]
    assert ids("popularity") == [r["activity_id"] for r in rows]
    assert ids("price") == [552524, 561819, 244817, 10918, 1221152, 1495538]          # per-person first, the group-priced one last
    assert ids("rating") == [561819, 10918, 552524, 1221152, 244817, 1495538]       # 4.9 (8813), 4.9 (432), 4.8 (16683); then under 20 reviews: 5.0 (1), 4.7 (14), unrated
    assert ids("reviews")[:2] == [552524, 561819]
    assert ids("duration")[:2] == [552524, 1495538]                                      # both 2 h: the cheaper first


def search_session(*pages):
    return FakeSession(answers=list(pages), read={"visitor_id": "VISITOR123", "body": ""})


async def find(session, **extra):
    async with Client(server_with(session)) as c:
        return await c.call_tool("getyourguide_find_activities", {"query": "Florence pasta cooking class", "activity_date": "2026-10-19", "pages": 1, **extra})


async def test_find_tool_reads_pages_filters_and_says_what_it_covered(today_is_before_fixture_date):
    session = search_session(SEARCH_PAGE, SEARCH_PAGE)           # the same page twice: duplicates are counted once
    r = await find(session, pages=2, sort_by="price", max_price=100, min_rating=4.5, max_results=2)
    d = r.structured_content
    assert [a["activity_id"] for a in d["activities"]] == [552524, 561819] and d["sorted_by"] == "price"
    assert d["coverage"] == {"pages_read": 2, "results_read": 6, "total_on_getyourguide": 573, "all_results_read": False, "passed_filters": 4, "shown": 2}
    assert d["price_range_of_results_read"] == {"min": 36.0, "median": 79.0, "max": 160.0, "of_results": 5, "per": "person", "currency": "EUR"}
    assert "Read 6 of 573 results" in d["note"] and "cheapest of the 6 read" in d["note"] and "getyourguide_activity_details" in d["next_step"]
    assert d["checked_at"].endswith("UTC") and "warning" not in d
    assert [call[0].split("?")[0] for call in session.posts] == ["https://travelers-api.getyourguide.com/user-interface/landing-pages/srp/blocks"] * 2
    url, body, headers = session.posts[1]
    assert "q=Florence+pasta+cooking+class" in url and "date_from=2026-10-19" in url
    assert body["payload"]["page"] == 2 and body["payload"]["datesSelected"] == {"fromDate": "2026-10-19", "toDate": "2026-10-19"}
    assert headers["accept-currency"] == "EUR" and headers["visitor-id"] == "VISITOR123"
    assert len(session.visits) == 1 and "date_from=2026-10-19" in session.visits[0]


async def test_find_tool_other_filters(today_is_before_fixture_date):
    d = (await find(search_session(SEARCH_PAGE), min_price=80, max_hours=3, title_contains=["cooking", "KOSHER"], sort_by="rating")).structured_content
    assert [a["activity_id"] for a in d["activities"]] == [10918, 1221152]          # 85 EUR 3-5 h (4.9 from 432) before 160 EUR (5.0 from 1 review)
    assert d["filters"]["title_contains"] == ["cooking", "kosher"] and d["coverage"]["passed_filters"] == 2
    d = (await find(search_session(SEARCH_PAGE), max_price=10)).structured_content
    assert d["activities"] == [] and "None of the results read passes the filters" in d["note"]
    d = (await find(search_session(SEARCH_PAGE), free_cancellation_only=True, max_results=1)).structured_content
    assert d["coverage"]["passed_filters"] == 6 and d["coverage"]["shown"] == 1


async def test_find_tool_group_priced_rows_are_flagged(today_is_before_fixture_date):
    d = (await find(search_session(SEARCH_PAGE))).structured_content
    assert "price_basis 'per group'" in d["note"]


async def test_find_tool_keeps_pages_read_when_a_later_page_fails(today_is_before_fixture_date):
    class Failing(FakeSession):
        async def fetch(self, *a, **k):
            self.calls = getattr(self, "calls", 0) + 1
            if self.calls == 2:
                return {"status": 500, "url": a[3], "text": ""}
            return await super().fetch(*a, **k)
    failing = Failing(answers=[SEARCH_PAGE], read={"visitor_id": "VISITOR123", "body": ""})
    d = (await find(failing, pages=3)).structured_content
    assert d["coverage"]["pages_read"] == 1 and "page 2 could not be read" in d["warning"] and "pages 1-1" in d["warning"]
    first = await find(Failing(answers=[], status=500, read={"visitor_id": "V", "body": ""}))
    assert first.is_error and "answered 500" in first.content[0].text


@pytest.mark.parametrize("extra,expected", [
    ({"query": " "}, "needs words"),
    ({"query": "x" * 300}, "too long"),
    ({"activity_date": "2020-01-01"}, "in the past"),
    ({"max_results": 0}, "between 1 and 60"),
    ({"pages": 0}, "between 1 and 12"),
    ({"pages": 13}, "between 1 and 12"),
    ({"sort_by": "cheapest"}, "sort_by must be one of"),
    ({"max_price": 0}, "more than 0"),
    ({"min_price": 50, "max_price": 20}, "higher than max_price"),
    ({"min_rating": 6}, "between 0 and 5"),
    ({"max_hours": 0}, "max_hours"),
])
async def test_find_tool_validation(extra, expected, today_is_before_fixture_date):
    session = search_session(SEARCH_PAGE)
    r = await find(session, **{"query": "Florence pasta class", **extra})
    assert r.is_error and expected in r.content[0].text and not session.visits


async def test_find_tool_no_results_unrelated_and_human_check(today_is_before_fixture_date):
    empty = {"content": [], "trackingEvents": []}
    r = await find(search_session(empty), query="Atlantis diving")
    assert not r.is_error and r.structured_content["activities"] == [] and "no activities" in r.structured_content["note"]
    r = await find(search_session(SEARCH_PAGE), query="Reykjavik northern lights")
    assert "None of these results contain the words" in r.structured_content["warning"]
    r = await find(FakeSession(read={"visitor_id": None, "body": "please verify you are human"}))
    assert r.is_error and "human check" in r.content[0].text
    r = await find(FakeSession(read={"visitor_id": None, "body": "welcome"}))
    assert r.is_error and "unexpected format" in r.content[0].text


async def test_find_tool_kill_switch():
    async with Client(server_with(FakeSession(), Settings(gyg_enabled=False))) as c:
        r = await c.call_tool("getyourguide_find_activities", {"query": "Florence pasta class"})
    assert r.is_error and "switched off" in r.content[0].text


def test_shortlist_is_cheapest_best_rated_and_most_reviewed_with_enough_reviews():
    rows, _ = search_page(SEARCH_PAGE)
    picks = shortlist(rows)
    # 36 EUR / 4.9 (8813) / 4.8 (16683): 561819 is the cheapest (tie on 36 -> more reviews is 552524) and the best rated; 552524 the most reviewed
    assert [(p["activity_id"], p["why"]) for p in picks] == [
        (552524, "Cheapest with 20+ reviews; Most reviewed"), (561819, "Best rated with 20+ reviews")]
    assert shortlist([]) == [] and shortlist([r for r in rows if r["price_basis"] == "per group"]) == []


async def test_find_tool_gives_the_shortlist_and_says_best_is_of_the_results_read(today_is_before_fixture_date):
    d = (await find(search_session(SEARCH_PAGE))).structured_content
    assert [p["activity_id"] for p in d["shortlist_for_exact_price"]] == [552524, 561819]
    assert "shortlist_for_exact_price" in d["next_step"] and "best of the 6 read" in d["note"]


async def test_find_tool_numbers_the_rows_and_flags_few_reviews(today_is_before_fixture_date):
    d = (await find(search_session(SEARCH_PAGE), sort_by="rating")).structured_content
    rows = d["activities"]
    assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5, 6] and "rank" in d["show_rows"]
    assert [(r["activity_id"], r["few_reviews"]) for r in rows] == [(561819, False), (10918, False), (552524, False), (1221152, True), (244817, True), (1495538, True)]


def _item(kind, n, text, icon):
    return {"id": f"{kind}-{n}", "type": "granular", "layout": {"type": "horizontalLayout", "content": [
        {"id": f"{kind}-{n}-icon", "type": "iconAtom", "iconName": icon}, {"id": f"{kind}-{n}-title-text", "type": "textAtom", "text": text}]}}


def test_included_and_not_included_items_are_told_apart():
    """The page shows both in one 'Includes' list, told apart only by the icon: 'Hotel pickup and drop-off' is a cross."""
    state = json.loads(json.dumps(STATE))
    state["sdui"] = {"content": [{"id": "inclusions", "content": [
        _item("inclusion", 0, "All ingredients and cooking equipment", "checkmark"), _item("inclusion", 1, "Lots of wine", "checkmark"),
        _item("exclusion", 0, "Hotel pickup and drop-off", "cross"), _item("exclusion", 1, "Gratuities", "cross")]}], "participants": STATE["sdui"].get("participants")}
    info = activity_info(state)
    assert info["includes"] == ["All ingredients and cooking equipment", "Lots of wine"]
    assert info["not_included"] == ["Hotel pickup and drop-off", "Gratuities"]
