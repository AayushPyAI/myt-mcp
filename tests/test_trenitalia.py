"""Trenitalia parsing, errors and the train tools. Fixture shape copied from a real lefrecce.it answer."""

import json
from datetime import date, timedelta

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services
from myt_mcp.trenitalia.client import TrenitaliaClient, TrenitaliaError
from myt_mcp.trenitalia.parse import summarize_solutions

pytestmark = pytest.mark.anyio


def eur(x):
    return {"currency": "€", "amount": x}


DIRECT = {
    "solution": {
        "origin": "Firenze S. M. Novella", "destination": "Roma Termini",
        "departureTime": "2026-10-16T08:14:00.000+02:00", "arrivalTime": "2026-10-16T09:49:00.000+02:00",
        "duration": "1h 35min", "status": "SALEABLE",
        "trains": [{"trainCategory": "Frecciarossa", "acronym": "FR", "name": "9511"}],
        "price": eur(85.8), "nodes": [{"origin": "Firenze S. M. Novella"}],
    },
    "grids": [{"services": [
        {"name": "STANDARD", "offers": [{"name": "BASE", "price": eur(100.0), "availableAmount": 133},
                                        {"name": "Economy", "price": eur(85.8), "availableAmount": 133}]},
        {"name": "BUSINESS", "offers": [{"name": "BASE", "price": eur(142.0), "availableAmount": 13}]},
    ]}],
}
WITH_CHANGE = {
    "solution": {**DIRECT["solution"], "departureTime": "2026-10-16T09:00:00.000+02:00", "price": eur(60.0),
                 "trains": [{"trainCategory": "Regionale", "name": "1"}, {"trainCategory": "Frecciarossa", "name": "2"}],
                 "nodes": [{}, {}]},
    "grids": [{"services": []}, {"services": []}],
}
RESULT = {"solutions": [DIRECT, WITH_CHANGE, {"broken": True}]}


def test_summary_rows_and_fares():
    rows, skipped = summarize_solutions(RESULT)
    assert skipped == 1 and len(rows) == 2
    first = rows[0]
    assert (first["departure"], first["arrival"], first["changes"], first["cheapest_price"]) == ("08:14", "09:49", 0, 85.8)
    assert first["trains"] == ["Frecciarossa 9511"]
    assert first["fares"][1] == {"class": "STANDARD", "fare": "Economy", "conditions": "cheaper, limited changes, no refund", "price": 85.8, "seats_left": 133}
    assert rows[1]["changes"] == 1 and rows[1]["fares"] == []   # fares only for direct trains
    assert "Do not state a class" in rows[1]["fares_note"] and "fares_note" not in rows[0]


def mock_client(handler):
    http = httpx.AsyncClient(base_url="https://lefrecce.test", transport=httpx.MockTransport(handler))
    return TrenitaliaClient(http=http, limiter=SiteLimiter("Trenitalia", 0, 1000))


@pytest.mark.parametrize("status,expected", [(403, "refused"), (429, "refused"), (503, "having problems"), (400, "could not run")])
async def test_errors_are_readable(status, expected):
    t = mock_client(lambda r: httpx.Response(status, text="x"))
    with pytest.raises(TrenitaliaError, match=expected):
        await t.find_stations("Roma")


async def test_non_json_and_timeout():
    with pytest.raises(TrenitaliaError, match="page instead of data"):
        await mock_client(lambda r: httpx.Response(200, text="<html>")).find_stations("Roma")

    def slow(_):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(TrenitaliaError, match="did not answer"):
        await mock_client(slow).find_stations("Roma")


def handler_factory(counter):
    def handler(req):
        if req.url.path.endswith("/locations/search"):
            name = req.url.params["name"].lower()
            return httpx.Response(200, json=[{"id": 1 if "fir" in name else 2, "name": name.title()}])
        counter["searches"] += 1
        asked = json.loads(req.content)["departureTime"][:10]   # answer for the asked day, like Trenitalia
        return httpx.Response(200, json=json.loads(json.dumps(RESULT).replace("2026-10-16", asked)))
    return handler


def server_with(counter, settings=None):
    settings = settings or Settings()
    return create_server(settings, Services(settings, trenitalia=mock_client(handler_factory(counter))))


SOON = (date.today() + timedelta(days=20)).isoformat()


async def test_train_prices_tool_and_cache():
    counter = {"searches": 0}
    srv = server_with(counter)
    args = {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON}
    async with Client(srv) as c:
        r1 = await c.call_tool("train_prices", args)
        await c.call_tool("train_prices", args)
    d = r1.structured_content
    assert d["prices_are_for"] == "all passengers together" and len(d["trains"]) == 2 and d["trains"][0]["fares"]
    assert counter["searches"] == 1   # same search answered from cache
    assert "note" not in d                       # fewer trains than max_results: nothing is hidden
    assert d["fare_key"]["BASE"].startswith("flexible") and d["fare_key"]["Economy"].startswith("cheaper")
    assert d["end_your_answer_with"].startswith("Source: Trenitalia (lefrecce.it), checked ") and d["end_your_answer_with"].endswith("https://www.lefrecce.it/")   # the line to show


async def test_train_prices_says_when_more_trains_may_exist():
    srv = server_with({"searches": 0})
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON, "max_results": 2})
    d = r.structured_content
    assert len(d["trains"]) == 2 and "first 2 trains" in d["note"] and "later trains" in d["note"]


@pytest.mark.parametrize("args,expected", [
    ({"travel_date": (date.today() - timedelta(days=1)).isoformat()}, "in the past"),
    ({"depart_after": "8am"}, "HH:MM"),
    ({"adults": 0}, "adults must be"),
    ({"to_station": "Firenze"}, "same station"),
])
async def test_train_input_validation(args, expected):
    srv = server_with({"searches": 0})
    base = {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON}
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {**base, **args})
    assert r.is_error and expected in r.content[0].text


async def test_wrong_day_answer_is_not_used():
    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        return httpx.Response(200, json=RESULT)   # always 16 Oct 2026, whatever day was asked
    settings = Settings()
    srv = create_server(settings, Services(settings, trenitalia=mock_client(handler)))
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON})
    assert r.is_error and "did not match the search" in r.content[0].text


async def test_trenitalia_kill_switch():
    srv = server_with({"searches": 0}, Settings(trenitalia_enabled=False))
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON})
    assert r.is_error and "switched off" in r.content[0].text


@pytest.mark.parametrize("typed,station,expected", [
    ("Firenze", "Firenze ( Tutte Le Stazioni )", True),
    ("florence", "Firenze S. M. Novella", True),          # English name
    ("ROMA termini", "Roma Termini", True),
    ("Forli", "Forlì", True),                              # accents
    ("Venezia Mestre", "Venezia Mestre", True),
    ("romma", "Bromma", False),                            # a typo must not become another country's station
    ("Roma", "Bromma", False),
    ("Milan", "Reggio Emilia", False),
    ("🚆🚆", "Milano ( Tutte Le Stazioni )", False),
])
def test_station_must_really_be_the_one_typed(typed, station, expected):
    from myt_mcp.tools.trains import station_matches
    assert station_matches(typed, station) is expected


async def test_typo_station_is_refused_not_guessed():
    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 760002311, "name": "Bromma"}])
        raise AssertionError("no search may run for a guessed station")
    settings = Settings()
    srv = create_server(settings, Services(settings, trenitalia=mock_client(handler)))
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "romma", "travel_date": SOON})
        emoji = await c.call_tool("train_find_station", {"query": "🚆"})
        bad = await c.call_tool("train_prices", {"from_station": "🚆🚆", "to_station": "Roma", "travel_date": SOON})
    assert r.is_error and "not an exact station name (closest: Bromma)" in r.content[0].text
    assert bad.is_error and "is not a station name" in bad.content[0].text


def test_english_names_are_searched_in_italian():
    from myt_mcp.tools.trains import italian_name
    assert italian_name("Rome") == "roma" and italian_name("Florence") == "firenze" and italian_name("rome termini") == "roma termini"
    assert italian_name("Venezia Mestre") == "Venezia Mestre" and italian_name("Paris") == "Paris"


async def test_many_trains_are_read_page_by_page_until_the_day_ends():
    """Trenitalia gives 10 trains per request; offset 0, 10, 20 ... until a short page."""
    offsets = []

    def train(i):
        return {"solution": {**DIRECT["solution"], "departureTime": f"2026-10-16T{6 + i // 2:02d}:{(i % 2) * 30:02d}:00.000+02:00"}, "grids": DIRECT["grids"]}

    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        body = json.loads(req.content)
        offsets.append(body["criteria"]["offset"])
        assert body["criteria"]["limit"] == 10
        first = body["criteria"]["offset"]
        asked = body["departureTime"][:10]
        sols = [train(i) for i in range(first, min(first + 10, 27))]      # a day with 27 trains
        return httpx.Response(200, json=json.loads(json.dumps({"solutions": sols}).replace("2026-10-16", asked)))

    settings = Settings()
    srv = create_server(settings, Services(settings, trenitalia=mock_client(handler)))
    base = {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON}
    async with Client(srv) as c:
        whole = await c.call_tool("train_prices", {**base, "max_results": 60, "depart_after": "05:00"})
        capped = await c.call_tool("train_prices", {**base, "max_results": 25, "depart_after": "05:30"})
        too_many = await c.call_tool("train_prices", {**base, "max_results": 151})
    d = whole.structured_content
    assert len(d["trains"]) == 27 and "note" not in d and d["at_a_glance"]["note"].startswith("Cheapest and fastest of ALL")
    assert all("fares" not in t for t in d["trains"]) and "max_results=1" in d["fares_note"]      # many trains: one short line each
    assert all(t["from"] and t["to"] for t in d["trains"])                                        # ...but the stations stay
    assert offsets[:3] == [0, 10, 20]                       # stopped at the short third page
    assert len(capped.structured_content["trains"]) == 25 and "later trains" in capped.structured_content["note"]
    assert too_many.is_error and "between 1 and 150" in too_many.content[0].text


def _mixed_day_server():
    """Four trains: 08:00 €80 1h40 direct, 09:00 €50 2h30 direct, 10:00 €30 3h change, 23:00 €40 2h direct (arrives after midnight)."""
    def train(hhmm, price, duration, changes):
        d = {"solution": {**DIRECT["solution"], "departureTime": f"2026-10-16T{hhmm}:00.000+02:00", "duration": duration, "price": eur(price),
                          "nodes": [{}] * (changes + 1)}, "grids": DIRECT["grids"]}
        return d
    day = [train("08:00", 80.0, "1h 40min", 0), train("09:00", 50.0, "2h 30min", 0), train("10:00", 30.0, "3h 0min", 1), train("23:00", 40.0, "2h 0min", 0)]

    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        asked = json.loads(req.content)["departureTime"][:10]
        return httpx.Response(200, json=json.loads(json.dumps({"solutions": day}).replace("2026-10-16", asked)))
    settings = Settings()
    return create_server(settings, Services(settings, trenitalia=mock_client(handler)))


async def _times(**args):
    async with Client(_mixed_day_server()) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON, "depart_after": "05:00", **args})
    assert not r.is_error, r.content[0].text
    return r.structured_content


@pytest.mark.parametrize("sort_by,expected", [
    ("departure", ["08:00", "09:00", "10:00", "23:00"]),
    ("price", ["10:00", "23:00", "09:00", "08:00"]),
    ("duration", ["08:00", "23:00", "09:00", "10:00"]),
    ("arrival", ["08:00", "09:00", "10:00", "23:00"]),
])
async def test_trains_can_be_sorted(sort_by, expected):
    d = await _times(sort_by=sort_by)
    assert [t["departure"] for t in d["trains"]] == expected and d["sorted_by"] == sort_by


async def test_arrival_sort_puts_a_train_that_arrives_after_midnight_last():
    d = await _times(sort_by="arrival")
    assert d["trains"][-1]["departure"] == "23:00"        # 23:00 + 2h = 01:00 next day, later than a 10:00 + 3h arrival


async def test_price_and_direct_filters():
    d = await _times(sort_by="price", max_price=60)
    assert [t["departure"] for t in d["trains"]] == ["10:00", "23:00", "09:00"] and d["trains_read"] == 4
    d = await _times(sort_by="price", max_price=60, direct_only=True)
    assert [t["departure"] for t in d["trains"]] == ["23:00", "09:00"] and d["filters"] == {"max_price": 60.0, "direct_only": True, "train_type": "all"}
    assert d["at_a_glance"]["cheapest_of_shown"]["departure"] == "23:00"


async def test_filters_that_remove_everything_say_so():
    d = await _times(max_price=10)
    assert d["trains"] == [] and "none passes the filters" in d["note"]


@pytest.mark.parametrize("args,expected", [({"sort_by": "cheapest"}, "sort_by must be one of"), ({"max_price": 0}, "max_price must be more than 0")])
async def test_sort_and_filter_validation(args, expected):
    async with Client(_mixed_day_server()) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON, **args})
    assert r.is_error and expected in r.content[0].text


async def test_next_day_trains_in_the_24_hour_window_are_left_out():
    """An evening search also returns tomorrow's early trains; they must not count as that day's cheapest or earliest."""
    def train(day, hhmm, price):
        return {"solution": {**DIRECT["solution"], "departureTime": f"{day}T{hhmm}:00.000+02:00", "price": eur(price)}, "grids": DIRECT["grids"]}

    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        asked = json.loads(req.content)["departureTime"][:10]
        tomorrow = (date.fromisoformat(asked) + timedelta(days=1)).isoformat()
        return httpx.Response(200, json={"solutions": [train(asked, "20:06", 70.0), train(asked, "21:40", 60.0), train(tomorrow, "06:30", 20.0)]})

    settings = Settings()
    srv = create_server(settings, Services(settings, trenitalia=mock_client(handler)))
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON, "depart_after": "20:00", "sort_by": "price"})
    d = r.structured_content
    assert [t["departure"] for t in d["trains"]] == ["21:40", "20:06"] and d["trains_read"] == 3 and d["next_day_trains_left_out"] == 1
    assert d["at_a_glance"]["cheapest_of_shown"]["price"] == 60.0       # not tomorrow's 20.0


def _types_server(frecce_only_answer_400=False):
    """Frecce + a regional + an Intercity; criteria flags are honoured like Trenitalia does."""
    def train(hhmm, category, price):
        return {"solution": {**DIRECT["solution"], "departureTime": f"2026-10-16T{hhmm}:00.000+02:00", "price": eur(price),
                             "trains": [{"trainCategory": category, "name": "1"}]}, "grids": DIRECT["grids"]}
    day = [train("08:00", "Frecciarossa", 60.0), train("09:00", "Regionale", 20.0), train("10:00", "Intercity", 30.0)]
    seen = []

    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        body = json.loads(req.content)
        crit = body["criteria"]
        seen.append((crit["frecceOnly"], crit["regionalOnly"]))
        asked = body["departureTime"][:10]
        rows = day
        if crit["frecceOnly"]:
            rows = [d for d in day if d["solution"]["trains"][0]["trainCategory"].startswith("Frecc")]
        if crit["regionalOnly"]:
            rows = [d for d in day if d["solution"]["trains"][0]["trainCategory"] == "Regionale"]
        if frecce_only_answer_400 and (crit["regionalOnly"] or crit["frecceOnly"]):
            return httpx.Response(400, json={"message": "There are no travel solutions with the selected search criteria. Please try another date."})
        return httpx.Response(200, json=json.loads(json.dumps({"solutions": rows}).replace("2026-10-16", asked)))
    settings = Settings()
    return create_server(settings, Services(settings, trenitalia=mock_client(handler))), seen


async def _typed(srv, **args):
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON, "depart_after": "05:00", **args})
    return r


@pytest.mark.parametrize("train_type,expected,flags", [
    ("all", ["08:00", "09:00", "10:00"], (False, False)),
    ("frecce", ["08:00"], (True, False)),
    ("regional", ["09:00"], (False, True)),
    ("intercity", ["10:00"], (False, False)),       # no API flag for Intercity: filtered here
])
async def test_train_type_filter(train_type, expected, flags):
    srv, seen = _types_server()
    r = await _typed(srv, train_type=train_type)
    assert [t["departure"] for t in r.structured_content["trains"]] == expected and seen[0] == flags
    assert r.structured_content["filters"]["train_type"] == train_type


async def test_a_type_filter_that_matches_nothing_is_empty_not_an_error():
    srv, _ = _types_server(frecce_only_answer_400=True)
    r = await _typed(srv, train_type="regional")
    assert not r.is_error and r.structured_content["trains"] == [] and "probably not published yet" in r.structured_content["note"]


async def test_only_frecce_on_a_far_date_gets_a_regional_not_published_note():
    far = (date.today() + timedelta(days=120)).isoformat()
    srv, _ = _types_server()
    async with Client(srv) as c:
        frecce = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": far, "depart_after": "05:00", "train_type": "frecce"})
        allt = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": far, "depart_after": "05:00"})
        near = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON, "depart_after": "05:00"})
    assert "types_note" not in frecce.structured_content and "types_note" not in allt.structured_content   # mixed day: regional exists
    assert "types_note" not in near.structured_content


async def test_far_date_with_only_frecce_returned_gets_the_note():
    far = (date.today() + timedelta(days=120)).isoformat()

    def only_frecce(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        asked = json.loads(req.content)["departureTime"][:10]
        return httpx.Response(200, json=json.loads(json.dumps({"solutions": [DIRECT]}).replace("2026-10-16", asked)))
    settings = Settings()
    srv = create_server(settings, Services(settings, trenitalia=mock_client(only_frecce)))
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": far, "depart_after": "05:00"})
    assert "not published yet" in r.structured_content["types_note"] and "Only Frecce" in r.structured_content["types_note"]


async def test_train_type_validation():
    srv, _ = _types_server()
    r = await _typed(srv, train_type="bus")
    assert r.is_error and "train_type must be one of" in r.content[0].text


async def test_trains_to_different_stations_are_labelled_and_the_answer_says_so():
    def train(hhmm, destination):
        return {"solution": {**DIRECT["solution"], "departureTime": f"2026-10-16T{hhmm}:00.000+02:00", "destination": destination}, "grids": DIRECT["grids"]}

    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        asked = json.loads(req.content)["departureTime"][:10]
        rows = [train("07:48", "Roma Tiburtina"), train("07:48", "Roma Termini")] + [train(f"{8 + i // 2:02d}:{(i % 2) * 30:02d}", "Roma Termini") for i in range(10)]
        return httpx.Response(200, json=json.loads(json.dumps({"solutions": rows}).replace("2026-10-16", asked)))
    settings = Settings()
    srv = create_server(settings, Services(settings, trenitalia=mock_client(handler)))
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON, "depart_after": "05:00"})
    d = r.structured_content
    assert {t["to"] for t in d["trains"]} == {"Roma Tiburtina", "Roma Termini"} and "different stations" in d["stations_note"]
    assert "Roma Tiburtina" in d["stations_note"]


async def test_a_train_without_a_price_is_left_out_with_a_warning_not_a_refusal():
    night = {"solution": {**DIRECT["solution"], "departureTime": "2026-10-16T23:00:00.000+02:00", "price": None, "trains": [{"trainCategory": "InterCityNotte", "name": "1955"}]},
             "grids": []}

    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        asked = json.loads(req.content)["departureTime"][:10]
        return httpx.Response(200, json=json.loads(json.dumps({"solutions": [DIRECT, night]}).replace("2026-10-16", asked)))
    settings = Settings()
    srv = create_server(settings, Services(settings, trenitalia=mock_client(handler)))
    async with Client(srv) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON, "depart_after": "05:00"})
    d = r.structured_content
    assert not r.is_error and len(d["trains"]) == 1 and d["trains_read"] == 2
    assert "InterCityNotte 1955" in d["warning"] and "no price" in d["warning"]


def _always_400():
    def handler(req):
        if req.url.path.endswith("/locations/search"):
            return httpx.Response(200, json=[{"id": 1 if "fir" in req.url.params["name"].lower() else 2, "name": req.url.params["name"].title()}])
        return httpx.Response(400, json={"message": "There are no travel solutions with the selected search criteria. Please try another date."})
    settings = Settings()
    return create_server(settings, Services(settings, trenitalia=mock_client(handler)))


async def test_a_far_date_Trenitalia_does_not_publish_yet_is_an_answer_not_an_error():
    far = (date.today() + timedelta(days=420)).isoformat()
    async with Client(_always_400()) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": far})
    d = r.structured_content
    assert not r.is_error and d["not_published_yet"] is True and d["trains"] == [] and "Do NOT estimate" in d["note"]


async def test_a_rejected_search_for_a_near_date_stays_an_error():
    async with Client(_always_400()) as c:
        r = await c.call_tool("train_prices", {"from_station": "Firenze", "to_station": "Roma", "travel_date": SOON})
    assert r.is_error and "rejected this search (400)" in r.content[0].text


# ---------- HTTP first, the automation Chrome second (23 Oct 2026) ----------

class _Chrome:
    def __init__(self, status=200, text='[{"id": 83, "displayName": "Firenze S. M. Novella"}]'):
        self.calls, self.status, self.text = [], status, text

    async def fetch(self, origin, start_url, method, url, body=None, headers=None):
        self.calls.append((method, url))
        return {"status": self.status, "url": url, "text": self.text}


async def test_a_refused_http_request_is_repeated_in_the_automation_chrome():
    http = httpx.AsyncClient(base_url="https://lefrecce.test", transport=httpx.MockTransport(lambda request: httpx.Response(403, text="blocked")))
    chrome = _Chrome()
    client = TrenitaliaClient(http=http, limiter=SiteLimiter("Trenitalia", 0, 1000), browser=chrome)
    stations = await client.find_stations("Firenze")
    assert stations == [{"id": 83, "name": "Firenze S. M. Novella"}] and chrome.calls[0][0] == "GET" and "locations/search?name=Firenze" in chrome.calls[0][1]


async def test_a_working_http_request_never_opens_the_browser_and_a_failing_browser_keeps_the_http_message():
    ok = httpx.AsyncClient(base_url="https://lefrecce.test", transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[{"id": 1, "displayName": "Roma Termini"}])))
    chrome = _Chrome()
    assert await TrenitaliaClient(http=ok, limiter=SiteLimiter("Trenitalia", 0, 1000), browser=chrome).find_stations("Roma")
    assert chrome.calls == []
    from myt_mcp.errors import IntegrationError

    class Broken:
        async def fetch(self, *a, **k):
            raise IntegrationError("browser is not running")
    refused = httpx.AsyncClient(base_url="https://lefrecce.test", transport=httpx.MockTransport(lambda request: httpx.Response(429, text="slow down")))
    with pytest.raises(TrenitaliaError, match="refused the request \\(429\\)"):
        await TrenitaliaClient(http=refused, limiter=SiteLimiter("Trenitalia", 0, 1000), browser=Broken()).find_stations("Roma")
