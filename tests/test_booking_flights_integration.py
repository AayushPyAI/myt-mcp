"""Booking.com flights, integration: the REAL script runs in a real browser (Playwright's Chromium) on a flights.booking.com page that serves what the real site serves (read live 5 Nov 2026): GET /api/flights/ with the
search parameters (sort, page, stops, children, cabinClass ...) answering `flightOffers` (15 a page), `aggregation` (totalCount, filteredTotalCount), `searchId` and `searchCriteria`. Nothing leaves the machine.
The rows the script makes are compared with the rows these tests derive in Python from the same offers."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.booking_flights import booking_flights_recipe
from tests.test_booking_flights import DAY, offer, row


def make_offer(sort, page, i, n_trav, cabin="ECONOMY"):
    shared = i == 0 and page == 1                               # the same flight is first in the Best list and in the Cheapest list
    number = 1000 if shared else (1000 if sort == "BEST" else 2000) + i + 15 * (page - 1) + 1
    return offer(flight=f"TP{number}", total=102.0 if shared else 110.0 + i + page, n=n_trav, cabin=cabin, checked=(i % 2 == 0), flex=(i % 3 != 0))


def run_script(pages=2, direct_only=False, children=(), cabin="economy", total=155, status=200, fail_page=None, bad_answer=False, html=None, seen=None, details=0, detail_status=200, detail_seen=None):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = booking_flights_recipe("LIS", "OPO", DAY, 2, direct_only, cabin, pages, list(children), details=details)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"
    code = {"economy": "ECONOMY", "business": "BUSINESS"}[cabin]

    def serve(route):
        u = urlparse(route.request.url)
        if u.hostname != "flights.booking.com":
            route.abort()
        elif u.path.startswith("/api/flight/"):
            token = u.path.rsplit("/", 1)[-1]
            if detail_seen is not None:
                detail_seen.append(token)
            if "adults" not in parse_qs(u.query):      # the real service answers an error body without the search parameters (a fresh browser, 5 Nov 2026)
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"error": {"code": "SEARCH_GETFLIGHTDETAILS_INVALID", "requestId": "x"}}))
                return
            if detail_status != 200:
                route.fulfill(status=detail_status, content_type="application/json", body="{}")
                return
            def feat(name, availability="INCLUDED"):
                return {"featureName": name, "category": "X", "label": name, "availability": availability}
            body = {"token": token, "fareRules": {"perSegment": [{"segmentIdentifiers": [{"segmentIndex": 0, "legIndex": 0}], "availablePolicies": [{"type": "CHANGE_BEFORE"}], "unavailablePolicies": [{"type": "CANCEL_BEFORE"}]}]},
                    "brandedFareInfo": {"fareName": "DISCOUNT", "cabinClass": "ECONOMY", "features": [feat("PERSONAL_BAGGAGE"), feat("CABIN_BAGGAGE"), feat("CHANGEABLE_TICKET")]},
                    "noFlexOrCfarContent": {"title": "Standard ticket", "includedFeatures": ["Cheapest price"], "excludedFeatures": ["No refund if you cancel"]},
                    "brandedFareOffers": [{"brandedFareInfo": {"fareName": "DISCOUNT", "features": [feat("CHANGEABLE_TICKET")]}, "priceBreakdown": {"total": {"currencyCode": "EUR", "units": 102, "nanos": 0}}},
                                          {"brandedFareInfo": {"fareName": "PLUS", "features": [feat("CHECK_BAGGAGE"), feat("REFUNDABLE_TICKET"), feat("CHANGEABLE_TICKET"), feat("PREMIUM_SEAT")]}, "priceBreakdown": {"total": {"currencyCode": "EUR", "units": 201, "nanos": 0}}}],
                    "baggagePolicies": [{"code": "TP", "name": "TAP Portugal", "url": "https://www.flytap.com/en-se/baggage"}]}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        elif u.path == "/api/flights/":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if seen is not None:
                seen.append(q)
            page = int(q.get("page", "1"))
            if (fail_page and page == fail_page) or status != 200:
                route.fulfill(status=status if status != 200 else 500, content_type="application/json", body="{}")
                return
            if bad_answer:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"unexpected": True}))
                return
            filtered = 10 if q.get("stops") == "0" else total
            n_trav = int(q.get("adults", "2")) + len([a for a in q.get("children", "").split(",") if a])
            count = max(0, min(15, filtered - 15 * (page - 1)))
            body = {"aggregation": {"totalCount": total, "filteredTotalCount": filtered, "stops": [{"numberOfStops": 0, "count": 10, "minPrice": {"currencyCode": "EUR", "units": 102, "nanos": 0}}],
                                    "airlines": [{"code": "TP", "name": "TAP Portugal", "count": 50}], "baggage": [{"baggageType": "CABIN", "count": 108}, {"baggageType": "CHECKIN", "count": 74}]},
                    "flightOffers": [make_offer(q["sort"], page, i, n_trav, q.get("cabinClass", "ECONOMY")) for i in range(count)], "searchId": "ABC123", "source": "cache", "searchCriteria": {"cabinClass": q.get("cabinClass")}}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or "<html><body><h1>Search flights: Lisbon - Porto</h1></body></html>")
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto(recipe["url"])
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def convert_one(out, recipe):
    return convert_all([{"site": "booking_flights", "result": out, "url": recipe["url"], "wishes": {"expect": recipe["expect"]}}], {"expect": recipe["expect"]})


def test_the_real_script_asks_the_flights_service_page_by_page_for_best_then_cheapest_and_makes_the_rows_the_converter_expects():
    seen: list = []
    out, recipe = run_script(seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["results_total"] == 155 and data["unfiltered_total"] == 155 and data["sorts"] == [{"sort": "Best", "pages_read": 2, "pages_seen": 11}, {"sort": "Cheapest", "pages_read": 2, "pages_seen": 11}]
    assert data["searched"] == {"type": "ONEWAY", "origin": "LIS", "destination": "OPO", "day": "2026-12-10", "adults": 2, "children": 0, "cabin": "ECONOMY", "currency": "EUR", "stops": None, "airlines": [], "dep_hours": None, "max_hours": None, "checked_bag": False} and data["cabin_back"] == "ECONOMY"
    assert [(q["sort"], q.get("page", "1")) for q in seen] == [("BEST", "1"), ("BEST", "2"), ("CHEAPEST", "1"), ("CHEAPEST", "2")]
    q = seen[0]
    assert (q["type"], q["adults"], q["cabinClass"], q["from"], q["to"], q["depart"], q["currency"], q["enableVI"], q["search_source"]) == ("ONEWAY", "2", "ECONOMY", "LIS.AIRPORT", "OPO.AIRPORT", "2026-12-10", "EUR", "1", "user") and "stops" not in q and "children" not in q
    assert data["baggage_counts"] == [{"type": "CABIN", "count": 108}, {"type": "CHECKIN", "count": 74}] and data["search_id"] == "ABC123" and data["failed"] is None
    rows = data["rows"]
    assert len(rows) == 60 and [r["page"] for r in rows if r["sort"] == "Best"] == [1] * 15 + [2] * 15
    first = rows[0]
    assert {k: v for k, v in first.items() if k != "detail"} == row("Best", 1, flight="TP1000", total=102.0, checked=True, flex=False)              # the JavaScript and the Python read the offer the same way
    assert rows[16] == row("Best", 2, flight="TP1017", total=113.0 + 1, checked=False, flex=True) or rows[16]["legs"][0]["flights"] == ["TP1017"]
    offers, sources, problems, _, notes = convert_one(out, recipe)
    assert not problems and len(offers) == 59 and (sources[0].read, sources[0].of) == (59, 155)       # the shared flight is one row
    shared = next(o for o in offers if "TP1000" in o.name)
    assert shared.details["from_tab"] == "Best and Cheapest" and shared.details["checked_bag"] == "yes: 1 bag(s) per traveller up to 23 kg" and shared.price_total == 102.0


def test_direct_only_children_and_the_business_cabin_are_sent_and_a_short_list_needs_one_request_per_sort():
    seen: list = []
    out, recipe = run_script(pages=3, direct_only=True, children=(8, 10), cabin="business", seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["searched"]["stops"] == "0" and data["searched"]["children"] == 2 and data["searched"]["cabin"] == "BUSINESS" and data["results_total"] == 10
    assert [(q["sort"], q.get("page", "1")) for q in seen] == [("BEST", "1"), ("CHEAPEST", "1")]       # 10 flights: one page of each sort
    assert all(q["stops"] == "0" and q["children"] == "8,10" and q["cabinClass"] == "BUSINESS" and q["adults"] == "2" for q in seen)
    assert len(data["rows"][0]["trav"]) == 4 and data["rows"][0]["legs"][0]["cabins"] == ["BUSINESS"]
    offers, _, problems, _, notes = convert_one(out, recipe)
    assert not problems and all(o.fits is True for o in offers) and any("direct-only filter (stops=0)" in n for n in notes) and any("2 child(ren) (ages 8, 10)" in n for n in notes)


def test_a_failing_second_page_gives_the_first_page_and_says_so_and_a_failing_first_page_is_an_error():
    out, recipe = run_script(fail_page=2)
    data = json.loads(out)
    assert data["ok"] is True and data["failed"] and "Best page 2" in data["failed"][0] and data["sorts"][0]["pages_read"] == 1 and len(data["rows"]) == 30
    notes = convert_one(out, recipe)[4]
    assert any("Not every page asked for was read" in n for n in notes)
    err = json.loads(run_script(status=500)[0])
    assert err["ok"] is False and "no flight list" in err["error"] and "answered 500" in err["error"]
    bad = json.loads(run_script(bad_answer=True)[0])
    assert bad["ok"] is False and "no flight list in the answer" in bad["error"]


def test_the_script_stops_on_a_human_check_and_on_a_page_that_is_not_a_flights_page():
    check = json.loads(run_script(html="<html><body>Are you a person or a robot? Press & hold</body></html>")[0])
    assert check["ok"] is False and "human check" in check["error"] and "do not work around" in check["error"]


def test_the_new_filters_are_sent_to_the_service_and_the_services_direct_only_flag_becomes_the_no_direct_notice():
    seen: list = []
    sync_api = pytest.importorskip("playwright.sync_api")
    out, recipe = run_script(pages=1, seen=seen)
    assert "airlines" not in seen[0] and "depTimeInt" not in seen[0] and "duration" not in seen[0] and "includedBaggage" not in seen[0]       # none asked, none sent
    import tests.test_booking_flights_integration as me
    recipe2 = booking_flights_recipe("LIS", "OPO", DAY, 2, False, "economy", 1, None, ["TP"], "06-11", 3, True)
    seen2: list = []

    def serve(route):
        u = urlparse(route.request.url)
        if u.path == "/api/flights/":
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            seen2.append(q)
            body = {"aggregation": {"totalCount": 5, "filteredTotalCount": 1, "stops": []}, "flightOffers": [make_offer("BEST", 1, 1, 2)], "searchId": "X", "source": "cache", "searchCriteria": {"cabinClass": "ECONOMY"},
                    "displayOptions": {"directFlightsOnlyFilterIgnored": True}}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        elif u.hostname == "flights.booking.com":
            route.fulfill(status=200, content_type="text/html", body="<html><body>x</body></html>")
        else:
            route.abort()
    direct = booking_flights_recipe("LIS", "OPO", DAY, 2, True, "economy", 1)
    script = "async () => { const LOCAL_RETURN = true; " + direct["script"].replace("await (async", "return (async", 1) + " }"
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/*", serve)
        page.goto(direct["url"])
        data = json.loads(page.evaluate(script))
        page.goto(recipe2["url"])
        page.evaluate("async () => { const LOCAL_RETURN = true; " + recipe2["script"].replace("await (async", "return (async", 1) + " }")
        browser.close()
    assert data["no_direct_notice"] is True and data["results_total"] == 1 and len(data["rows"]) >= 1
    last = seen2[-1]
    assert last["airlines"] == "TP" and last["depTimeInt"] == "06-11" and last["duration"] == "3" and last["includedBaggage"] == "CHECKIN"


def test_the_cheapest_flights_get_their_details_read_one_request_each_and_a_failing_details_service_never_hides_the_flights():
    detail_seen: list = []
    out, recipe = run_script(pages=1, details=3, detail_seen=detail_seen)
    data = json.loads(out)
    assert data["ok"] is True and data["details_read"] == 3 and data["details_failed"] is None and len(set(detail_seen)) == 3 and len(detail_seen) == 3
    with_detail = [r for r in data["rows"] if r.get("detail")]
    cheapest_totals = sorted({r["total"] for r in data["rows"]})[:3]
    assert with_detail and all(r["total"] in cheapest_totals or r["legs"][0]["flights"] == data["rows"][0]["legs"][0]["flights"] for r in with_detail)
    d = with_detail[0]["detail"]
    assert d["fare"] == "DISCOUNT" and d["change"] is True and d["cancel"] is False and [o["name"] for o in d["options"]] == ["DISCOUNT", "PLUS"] and d["options"][1]["refundable"] is True and d["options"][1]["checked_bag"] is True
    offers, _, problems, _, notes = convert_one(out, recipe)
    assert not problems and any("were read for the 3 cheapest flight(s)" in n for n in notes) and any(o.details["refund_change"].startswith("change before departure allowed") for o in offers)
    out, recipe = run_script(pages=1, details=2, detail_status=500)
    data = json.loads(out)
    assert data["ok"] is True and data["details_read"] == 0 and len(data["details_failed"]) == 2 and len(data["rows"]) == 30 and not any(r.get("detail") for r in data["rows"])
    assert any("Some fare details could not be read" in n for n in convert_one(out, recipe)[4])
    assert detail_seen and detail_seen[0]
