"""Europcar cars, integration: the REAL script runs in a real browser (Playwright's Chromium) on a europcar.com page that does what the real one does: it loads and makes ONE request to Europcar's own offers
service (GET .../group-direct-channel-context/v1/offers?apikey=...&limit=10&offset=0). The service here answers like the real one read on 5 Nov 2026 (`data`, `meta`, `pagination`, 409 MINIMUM_DRIVER_AGE) and
honours limit, offset and filter. The script finds the page's own request in its network log and sends it again, 50 cars at a time. Nothing leaves the machine. Its rows go through the server's converter and are
compared with the rows tests/test_europcar.py derives in Python from the same answer."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.europcar_cars import europcar_cars_recipe
from tests.test_europcar import offer, rows_from

CARS = [offer(f"CAR {i}", "CDAR", "Compact", 5 if i % 3 else 4, i % 2 == 0, 100.0 + i, 50.0 + i / 2, 3000.0 if i != 8 else 0.0) for i in range(1, 38)]
OFFERS_URL = ("https://api.aws.emobg.io/group-direct-channel-context/v1/offers?apikey=PAGEKEY&origin=www.europcar.com/onesite&vehicle-types=CAR,LUXURY&country-of-residence=IL&pickup-station-code=LIST01"
              "&drop-off-station-code=LIST01&pickup-date=2027-03-06T10:00&drop-off-date=2027-03-08T10:00&driver-age=30&sort=-recommendation,price&limit=10&offset=0")
PAGE = "<html><body><div>Europcar</div><script>fetch(%s).then(r => r.json()).then(j => { document.title = 'loaded ' + j.data.length; });</script></body></html>" % json.dumps(OFFERS_URL)
CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*"}


def service(cars=CARS, status=None, seen=None):
    def answer(query: dict) -> tuple[int, dict]:
        if seen is not None:
            seen.append({k: v[0] for k, v in query.items()})
        if status:
            return status
        limit, offset = int(query["limit"][0]), int(query["offset"][0])
        flt = query.get("filter", [""])[0]
        out = cars
        for part in [x for x in flt.split(",") if x]:
            if part == "feature:contains:AUTOMATIC":
                out = [c for c in out if c["car"]["engine"]["automatic"]]
            elif part.startswith("seats:gte:"):
                out = [c for c in out if c["car"]["capacity"]["seats"] >= int(part.split(":")[2])]
        return 200, {"meta": {"durationInDays": 2, "youngDriverSurchargeApplied": False, "currencies": {"customer": "USD", "destination": "EUR"}}, "data": out[offset:offset + limit],
                     "recommendations": [], "pagination": {"offset": offset, "limit": limit, "size": len(out[offset:offset + limit]), "total": len(out), "totalWithoutFilter": len(cars)}}
    return answer


def run_script(answer=None, url=None, html=PAGE, tries=None, filter_text="", age=30):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = europcar_cars_recipe("Lisbon Airport", "LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", age, "IL", filter_text)
    script = "async () => { const LOCAL_RETURN = true; " + (f"const API_TRIES = {tries}; " if tries else "") + recipe["script"].replace("await (async", "return (async", 1) + " }"
    answer = answer or service()

    def serve(route):
        u = urlparse(route.request.url)
        if u.path.endswith("/reservation/vehicles"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif u.path.endswith("/group-direct-channel-context/v1/offers"):
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=CORS)
                return
            result = answer(parse_qs(u.query))
            status, body = result if isinstance(result, tuple) and isinstance(result[0], int) else (200, result)
            route.fulfill(status=status, content_type="application/json", headers=CORS, body=json.dumps(body))
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto(url or recipe["url"])
            page.wait_for_function("document.title.startsWith('loaded') || true")
            page.wait_for_timeout(300)
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def test_the_real_script_sends_the_pages_own_request_again_pages_through_every_car_and_makes_the_same_rows_the_unit_tests_expect():
    seen: list = []
    out, recipe = run_script(service(seen=seen))
    data = json.loads(out)
    assert data["ok"] is True and data["age"] == 30 and data["residency"] == "IL" and data["total"] == 37 and data["cars_read"] == 37 and data["complete"] is True and data["days"] == 2 and data["filter_sent"] is None
    assert data["form"] == {"pickup_station": "LIST01", "dropoff_station": "LIST01", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00"}
    assert data["rows"] == json.loads(json.dumps(rows_from(CARS)))                       # the JavaScript and the Python read the answer the same way
    sent = [s for s in seen if s.get("limit") == "50"]
    assert [s["offset"] for s in sent] == ["0"] and all(s["apikey"] == "PAGEKEY" for s in seen) and "filter" not in sent[0]       # the page's own key and parameters, 50 at a time (one page holds all 37)
    wishes = {"expect": recipe["expect"], "automatic": True, "zero_excess": True, "min_seats": 5}
    offers, sources, problems, _, notes = convert_all([{"site": "europcar_cars", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)
    assert problems == [] and len(offers) == 37 and sources[0].read == 37 and {o.currency for o in offers} == {"EUR"}
    fits = {o.name.split(" (")[0]: o.fits for o in offers}
    assert [k for k, v in fits.items() if v] == ["CAR 8"]                                        # zero excess AND automatic AND 5 seats: only CAR 8
    assert any("public website price" in n for n in notes)


def test_the_script_pages_through_a_long_list_and_sends_the_operators_filter_to_europcar():
    many = [offer(f"CAR {i}", "CDAR", "Compact", 5, i % 2 == 0, 100.0 + i) for i in range(1, 121)]
    seen: list = []
    data = json.loads(run_script(service(many, seen=seen))[0])
    assert data["total"] == 120 and data["cars_read"] == 120 and data["complete"] is True and [s["offset"] for s in seen if s.get("limit") == "50"] == ["0", "50", "100"]
    seen.clear()
    filtered = json.loads(run_script(service(many, seen=seen), filter_text="feature:contains:AUTOMATIC,seats:gte:5")[0])
    assert filtered["filter_sent"] == "feature:contains:AUTOMATIC,seats:gte:5" and filtered["total"] == 60 and filtered["unfiltered_total"] == 120 and filtered["cars_read"] == 60 and {r["automatic"] for r in filtered["rows"]} == {True}
    assert all(s.get("filter") == "feature:contains:AUTOMATIC,seats:gte:5" for s in seen if s.get("limit") == "50")
    none = json.loads(run_script(service(many), filter_text="seats:gte:12")[0])
    assert none["ok"] is True and none["total"] == 0 and none["rows"] == [] and none["unfiltered_total"] == 120


def test_europcars_own_refusals_come_back_with_their_code_and_the_converter_names_them():
    out, recipe = run_script(service(status=(409, {"status": 409, "label": "Conflict", "message": "Driver's age 18 below minimum", "code": "MINIMUM_DRIVER_AGE"})))
    data = json.loads(out)
    assert data["ok"] is False and data["code"] == "MINIMUM_DRIVER_AGE" and data["http_status"] == 409 and "409 MINIMUM_DRIVER_AGE" in data["error"] and "Driver's age 18 below minimum" in data["error"]
    problems = convert_all([{"site": "europcar_cars", "result": out, "url": recipe["url"], "wishes": {"expect": recipe["expect"]}}], {"expect": recipe["expect"]})[2]
    assert any("does not rent to a driver of this age" in p for p in problems)
    bad = json.loads(run_script(service(status=(400, {"status": 400, "message": "Invalid pickUpDate is before current date", "code": "INVALID_SEARCH_CRITERIA"})))[0])
    assert bad["ok"] is False and "400 INVALID_SEARCH_CRITERIA" in bad["error"]


def test_the_real_script_stops_when_the_page_searched_something_else():
    other = PAGE.replace("driver-age=30", "driver-age=26").replace("country-of-residence=IL", "country-of-residence=IN")
    data = json.loads(run_script(html=other)[0])
    assert data["ok"] is False and "driver age 26 instead of 30" in data["error"] and "residency IN instead of IL" in data["error"]


def test_the_real_script_says_it_could_not_read_a_page_without_the_offers_request_or_with_an_empty_answer():
    silent = json.loads(run_script(html="<html><body><div>Loading</div></body></html>", tries=2)[0])
    assert silent["ok"] is False and "has not made its offers request" in silent["error"] and "never say sold out" in silent["error"]
    empty = json.loads(run_script(service([]))[0])
    assert empty["ok"] is False and "holds no cars" in empty["error"]
