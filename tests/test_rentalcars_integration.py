"""Rentalcars.com, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page that does what the real one does: it loads, makes ONE request to /api/search-results?searchCriteria=...
and the script finds that request in the page's own network log and reads it again. The answer has the shape of the site's own answer read live on 27 Oct 2026 (matches, depots, suppliers, fees, aggregates;
tests/test_rentalcars.py builds it). Nothing leaves the machine. The script's rows go through the server's converter, and are compared with the rows the unit tests derive from the same answer."""

import json
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.rentalcars_cars import rentalcars_cars_recipe
from tests.test_rentalcars import LIS, api_answer, match, rows_from

PAGE = ("<html><body><div>Pick-up location</div><div>Humberto Delgado Airport (LIS)</div><h1>530 cars available</h1><div>Sort by: Recommended</div>"
        "<script>fetch('/api/search-results?searchCriteria=%7B%7D&filterCriteria=%7B%7D&serviceFeatures=%5B%5D').then(r => r.json()).then(j => { document.title = 'loaded ' + j.matches.length; });</script></body></html>")


def run_script(answer: dict, url: str | None = None, page_html: str = PAGE, tries: int | None = None, api_status: int = 200, filters: dict | None = None, site=None, seen: list | None = None) -> str:
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = rentalcars_cars_recipe(LIS, LIS, "2027-03-06", "10:00", "2027-03-08", "10:00", 30, filters)
    script = "async () => { const LOCAL_RETURN = true; " + (f"const API_TRIES = {tries}; " if tries else "") + recipe["script"].replace("await (async", "return (async", 1) + " }"
    body = json.dumps(answer)

    def serve(route):
        path = urlparse(route.request.url).path
        if path == "/search-results":
            route.fulfill(status=200, content_type="text/html", body=page_html)
        elif path == "/api/search-results":
            query = parse_qs(urlparse(route.request.url).query)
            if seen is not None:
                seen.append(json.loads(query.get("filterCriteria", ["{}"])[0]))
            route.fulfill(status=api_status, content_type="application/json", body=json.dumps(site(json.loads(query.get("filterCriteria", ["{}"])[0]))) if site else body)
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1300, "height": 900})
            page.route("**/*", serve)
            page.goto(url or recipe["url"])
            page.wait_for_load_state("networkidle")
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out


def test_the_real_script_rereads_the_pages_own_search_answer_and_makes_the_same_rows_the_unit_tests_expect():
    answer = api_answer()
    data = json.loads(run_script(answer))
    assert data["ok"] is True and data["matches_read"] == 3 and data["cars_shown_by_page"] == "530" and data["fuel_policies"] == ["RETURN_SAME"]
    assert data["form"] == {"iata": "LIS", "drop_iata": "LIS", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00", "age": 30}
    assert data["rows"] == json.loads(json.dumps(rows_from(answer)))                 # the JavaScript and the Python read the answer the same way
    recipe = rentalcars_cars_recipe(LIS, LIS, "2027-03-06", "10:00", "2027-03-08", "10:00", 30)
    fx = {"factors": {"INR": 0.0107}, "date": "2026-10-26", "age_days": 1, "source": "Bank of Israel representative rates"}
    wishes = {"expect": recipe["expect"], "automatic": True, "min_seats": 5, "fx": fx}
    offers, sources, problems, by_price, notes = convert_all([{"site": "rentalcars_cars", "result": json.dumps(data), "url": recipe["url"], "wishes": wishes}], wishes)
    assert problems == [] and len(offers) == 3 and sources[0].read == 3 and sources[0].of == 530
    by = {o.name.split(" (")[0]: o for o in offers}
    assert by["Peugeot 2008"].fits is True and by["Fiat 500"].fits is False and by["VW Golf"].fits is False and by["Peugeot 2008"].currency == "EUR" and by["Peugeot 2008"].price_total == round(3259.28 * 0.0107, 2)
    assert any("530 cars" in n for n in notes)


def test_the_real_script_stops_when_the_address_is_not_the_one_asked():
    url = "https://www.rentalcars.com/search-results?locationIata=FAO&dropLocationIata=LIS&driversAge=25&puDay=6&puMonth=3&puYear=2027&puMinute=0&puHour=10&doDay=8&doMonth=3&doYear=2027&doMinute=0&doHour=10"
    data = json.loads(run_script(api_answer(), url=url))
    assert data["ok"] is False and "iata FAO instead of LIS" in data["error"] and "age 25 instead of 30" in data["error"]


def test_the_real_script_says_it_could_not_read_a_page_with_no_search_request_or_an_empty_or_failed_answer():
    silent = json.loads(run_script(api_answer(), page_html="<html><body><h1>Loading</h1></body></html>", tries=2))
    assert silent["ok"] is False and "has not made its search request" in silent["error"] and "never say sold out" in silent["error"]
    empty = json.loads(run_script(api_answer([])))
    assert empty["ok"] is False and "holds no cars" in empty["error"]
    refused = json.loads(run_script(api_answer(), api_status=403))
    assert refused["ok"] is False and "answered 403" in refused["error"]


def _site(total: int, cap: int = 500, bands=(("BUCKET_1", 4), ("BUCKET_2", 3), ("BUCKET_3", 3))):
    """A site that behaves as the real one did on 5 Nov 2026: it counts every car that matches the filters, returns at most `cap` of them (recommended order), and filters by transmission and price band."""
    cars = [match(i + 1, f"Car {i + 1}", gearbox="AUTOMATIC" if i % 2 == 0 else "MANUAL", total=100.0 + i) for i in range(total)]
    for i, m in enumerate(cars):
        m["vehicle"]["id"] = str(1000 + i)
    band_of = {c["vehicle"]["id"]: bands[min(i * len(bands) // total, len(bands) - 1)][0] for i, c in enumerate(cars)}

    def answer(fc: dict) -> dict:
        out = [c for c in cars if (not fc.get("transmission") or c["vehicle"]["transmission"] in fc["transmission"]) and (not fc.get("pricePerDayBuckets") or band_of[c["vehicle"]["id"]] in fc["pricePerDayBuckets"])]
        base = api_answer([])
        base["matches"] = out[:cap]
        base["aggregates"] = {**base["aggregates"], "matches": {"matchCountAfterFiltering": len(out)},
                              "pricePerDayBuckets": [{"value": b, "numVehicles": sum(1 for v in band_of.values() if v == b), "available": True} for b, _ in bands]}
        return base
    return answer


def test_the_script_sends_the_operators_filters_to_the_site_and_reports_both_counts():
    seen: list = []
    data = json.loads(run_script({}, filters={"transmission": ["AUTOMATIC"]}, site=_site(10), seen=seen))
    assert data["ok"] is True and data["unfiltered_total"] == 10 and data["filtered_total"] == 5 and data["matches_read"] == 5 and data["complete"] is True and data["filters_sent"] == {"transmission": ["AUTOMATIC"]}
    assert {r["gearbox"] for r in data["rows"]} == {"AUTOMATIC"} and {} in seen and {"transmission": ["AUTOMATIC"]} in seen          # the page's own search, then the same search with the filter
    plain = json.loads(run_script({}, site=_site(10)))
    assert plain["filtered_total"] is None and plain["filters_sent"] is None and plain["matches_read"] == 10 and plain["complete"] is True


def test_when_the_site_counts_more_cars_than_it_answers_the_script_joins_the_price_bands_and_says_if_it_could_not():
    seen: list = []
    joined = json.loads(run_script({}, site=_site(12, cap=5), seen=seen))
    assert joined["ok"] is True and joined["unfiltered_total"] == 12 and joined["matches_read"] == 12 and joined["complete"] is True and len({r["id"] for r in joined["rows"]}) == 12
    assert [f for f in seen if f.get("pricePerDayBuckets")] == [{"pricePerDayBuckets": ["BUCKET_1"]}, {"pricePerDayBuckets": ["BUCKET_2"]}, {"pricePerDayBuckets": ["BUCKET_3"]}]
    with_filter = json.loads(run_script({}, filters={"transmission": ["MANUAL"]}, site=_site(12, cap=3)))
    assert with_filter["filtered_total"] == 6 and with_filter["matches_read"] == 6 and with_filter["complete"] is True and {r["gearbox"] for r in with_filter["rows"]} == {"MANUAL"}
    too_big = json.loads(run_script({}, site=_site(12, cap=2)))        # one price band alone holds more than the site answers: it says so
    assert too_big["ok"] is True and too_big["complete"] is False and too_big["matches_read"] < 12


def test_a_filter_the_site_finds_no_car_for_is_an_answer_and_not_a_failure():
    data = json.loads(run_script({}, filters={"transmission": ["NONE"]}, site=_site(10)))
    assert data["ok"] is True and data["filtered_total"] == 0 and data["rows"] == [] and data["unfiltered_total"] == 10
