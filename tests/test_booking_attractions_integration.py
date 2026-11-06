"""Booking.com attractions, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page that serves what the real site serves (read live 5 Nov 2026): the first 15 activities and the filter
statistics embedded as an Apollo store (<script type="application/json" data-capla-store-data="apollo">: ROOT_QUERY.attractionsProduct.searchProducts with {input: {ufi, limit, page, source, filters, sortBy}}), the page's
tokens inside its inline data, and POST accommodations.booking.com/dml/graphql (operation SearchResultsProducts) answering the next pages and the other sort. Nothing leaves the machine."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.booking_attractions import booking_attractions_recipe
from tests.test_booking_attractions import DAY, SLUG

UFI = -2167973


def product(i, sort="trending", page=1, free=None, rating5=4.6):
    """An activity as the service returns it (structure read live 5 Nov 2026)."""
    shared = i == 0 and page == 1                      # the same activity is first in every sort
    n = 0 if shared else i + 15 * (page - 1) + (100 if sort == "trending" else 200)
    return {"__typename": "AttractionsProduct", "id": f"PR{n:04d}", "slug": SLUG if shared else f"pr{n:04d}-{sort}-tour", "name": "Tickets into The Lisbon Oceanarium" if shared else f"{sort} tour {n}",
            "duration": {"__typename": "AttractionsDuration", "label": "Duration: 3 hours", "min": None, "max": None, "type": "FIXED", "value": "PT3H"},
            "cancellationPolicy": {"__typename": "AttractionsCancellationPolicy", "comparedTo": "start", "hasFreeCancellation": (n % 2 == 0) if free is None else free, "isStillRefundable": True, "label": None, "message": None, "percentage": 100, "period": "P1D", "until": "2027-03-06T10:00:00"},
            "reviewsStats": {"__typename": "AttractionsReviewStats", "combinedNumericStats": {"__typename": "AttractionsStats", "average": rating5 if shared else 4.0 + (n % 10) / 10, "total": 4218 if shared else 50 + n, "scale": "FIVE_POINT"}},
            "representativePrice": {"__typename": "AttractionsPrice", "chargeAmount": 25.5 if shared else 30.0 + n / 100, "currency": "EUR", "publicAmount": 25.5 if shared else 30.0 + n / 100, "discounts": []},
            "labels": [{"__typename": "AttractionsLabel", "text": "Free cancellation", "type": "free_cancellation"}] if (n % 2 == 0 if free is None else free) else [],
            "flags": [{"__typename": "AttractionsProductFlags", "flag": "bestseller", "value": True, "rank": 1, "label": "#1 Best seller in Lisbon", "tooltip": None}] if shared else [], "primaryLabel": None}


def apollo_store(filters=None, sort=None, total=60, matching=None, has_next=True, products=None):
    filters = filters or {}
    inp = {"limit": 15, "page": 1, "source": "search_results", "ufi": UFI, **filters, **({"sortBy": sort} if sort else {})}
    stats_inp = {"extractFilterOptions": True, "extractFilterStats": True, "extractSorters": True, "limit": 0, "page": 1, "source": "search_results", "ufi": UFI, **filters, **({"sortBy": sort} if sort else {})}
    items = products if products is not None else [product(i, sort or "trending", 1) for i in range(15)]
    store = {"ROOT_QUERY": {"__typename": "Query", "attractionsProduct": {
        "getLocationDetails:{\"input\":{\"slug\":\"lisbon-pt\"}}": {"__typename": "X"},
        "searchProducts:" + json.dumps({"input": stats_inp}): {"__typename": "AttractionsProductSearchResponse", "filterStats": {"__typename": "FilterStats", "filteredProductCount": matching or total, "unfilteredProductCount": total}, "sorters": []},
        "searchProducts:" + json.dumps({"input": inp}): {"__typename": "AttractionsProductSearchResponse", "pagination": {"__typename": "P", "hasNextPage": has_next}, "unavailableProducts": [], "products": [{"__ref": f"AttractionsProduct:{{\"slug\":\"{p['slug']}\"}}"} for p in items]}}}}
    for p in items:
        store[f"AttractionsProduct:{{\"slug\":\"{p['slug']}\"}}"] = p
    return store


def page_html(store=None, tokens=True, check=False):
    if check:
        return "<html><body>Are you a person or a robot? Press &amp; hold</body></html>"
    data = '<script>window.__ctx = {"csrfToken":"tok-1","pageviewId":"pv-1","etSerializedState":"et-1"};</script>' if tokens else ""
    blob = f'<script type="application/json" data-capla-store-data="apollo">{json.dumps(store)}</script>' if store is not None else ""
    return f"<html><head><title>Lisbon activities</title></head><body><h1>Lisbon experiences</h1>{data}{blob}</body></html>"


def run_script(recipe=None, store=None, tokens=True, fail_sort=None, fail_all=False, seen=None, html=None, check=False, path="/attractions/searchresults/pt/lisbon.en-gb.html", matching_pages=3):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = recipe or booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"
    store = store if store is not None else apollo_store()

    def serve(route):
        u = urlparse(route.request.url)
        if u.hostname == "accommodations.booking.com" and u.path == "/dml/graphql":
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers={"access-control-allow-origin": "https://www.booking.com", "access-control-allow-credentials": "true", "access-control-allow-headers": "*", "access-control-allow-methods": "POST"})
                return
            body = json.loads(route.request.post_data)
            inp = body["variables"]["input"]
            if seen is not None:
                seen.append({"op": body["operationName"], "input": inp, "headers": dict(route.request.headers), "ctx": body["variables"]["contextParams"], "query": body["query"][:60]})
            cors = {"access-control-allow-origin": "https://www.booking.com", "access-control-allow-credentials": "true"}
            sort = inp.get("sortBy", "trending")
            if fail_all or (fail_sort and sort == fail_sort):
                route.fulfill(status=500, content_type="application/json", headers=cors, body="{}")
                return
            page = inp["page"]
            items = [product(i, sort, page) for i in range(15)]
            route.fulfill(status=200, content_type="application/json", headers=cors, body=json.dumps({"data": {"attractionsProduct": {"searchProducts": {"pagination": {"hasNextPage": page < matching_pages}, "products": items}}}}))
        elif u.hostname == "www.booking.com":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or page_html(store, tokens, check))
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto("https://www.booking.com" + path + "?aid=304142&label=mkt1&date_from=2027-03-07&date_to=2027-03-07&adults=2&selected_currency=EUR")
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def convert_one(out, recipe):
    return convert_all([{"site": "booking_attractions", "result": out, "url": recipe["url"], "wishes": {"expect": recipe["expect"]}}], {"expect": recipe["expect"]})


def test_the_real_script_reads_page_one_from_the_pages_own_data_and_asks_the_service_for_the_rest_and_for_the_other_sort():
    seen: list = []
    out, recipe = run_script(seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["place"] == "pt/lisbon" and data["country"] == "pt" and data["ufi"] == UFI and data["filters_match"] is True and data["results_matching"] == 60 and data["results_in_city"] == 60 and data["failed"] is None
    assert data["searched"] == {"place": "pt/lisbon", "day": "2027-03-07", "day_to": "2027-03-07", "adults": 2, "currency": "EUR", "filters": {"filterByLabel": [], "filterByMinRating": [], "filterBySupportedLanguage": []}}
    assert data["sorts"] == [{"sort": "Our top picks", "key": "trending", "read": 30, "has_next": True, "first_page_from": "page"}, {"sort": "Best reviewed", "key": "highest_weighted_rating", "read": 30, "has_next": True, "first_page_from": "api"}]
    assert [(r["input"]["page"], r["input"].get("sortBy")) for r in seen] == [(2, None), (1, "highest_weighted_rating"), (2, "highest_weighted_rating")]       # page 1 of the page's own sort needs no request
    ask = seen[0]
    assert ask["op"] == "SearchResultsProducts" and ask["input"] == {"ufi": UFI, "limit": 15, "page": 2, "source": "search_results"} and ask["query"].startswith("query SearchResultsProducts")
    assert ask["headers"]["x-booking-csrf-token"] == "tok-1" and ask["headers"]["x-booking-pageview-id"] == "pv-1" and ask["headers"]["x-booking-context-aid"] == "304142" and ask["ctx"]["label"] == "mkt1"
    rows = data["rows"]
    assert len(rows) == 60 and rows[0] == {**rows[0], "title": "Tickets into The Lisbon Oceanarium", "from": 25.5, "public_from": 25.5, "rating5": 4.6, "reviews": 4218, "duration": "3 hours", "duration_iso": "PT3H", "best_seller": 1, "slug": SLUG, "cur": "EUR"}
    assert rows[0]["flags"] == ["bestseller"] and rows[0]["best_seller_text"] == "#1 Best seller in Lisbon" and rows[0]["free_cancel"] is True and rows[0]["cancel_until"] == "2027-03-06T10:00:00" and rows[0]["labels"] == ["free_cancellation"]
    offers, sources, problems, _, notes = convert_one(out, recipe)
    assert not problems and len(offers) == 59 and (sources[0].read, sources[0].of) == (59, 60)       # the shared activity is one row
    shared = next(o for o in offers if o.name == "Tickets into The Lisbon Oceanarium")
    assert shared.details["from_tab"] == "Top picks and Best reviewed" and shared.price_total == 25.5 and shared.details["rating"] == "9.2 (4,218 reviews)" and shared.link == f"https://www.booking.com/attractions/pt/{SLUG}.en-gb.html"


def test_the_filters_go_in_the_requests_input_and_a_page_opened_without_them_still_gives_the_right_activities():
    recipe = booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 30, ["tour"], True, None, 9.0, True, "en")
    filters = {"filterByLabel": ["free_cancellation", "skip_the_line"], "filterByMinRating": ["4.5"], "filterBySupportedLanguage": ["en"]}
    seen: list = []
    out, _ = run_script(recipe, store=apollo_store(filters, total=60, matching=12, has_next=False), seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["filters_match"] is True and data["results_matching"] == 12 and data["results_in_city"] == 60 and data["sorts"][0]["has_next"] is False and data["sorts"][0]["read"] == 15
    assert all(r["input"].get("filterByLabel") == ["free_cancellation", "skip_the_line"] and r["input"]["filterByMinRating"] == ["4.5"] and r["input"]["filterBySupportedLanguage"] == ["en"] for r in seen)
    assert not convert_one(out, recipe)[2]
    seen.clear()
    out, _ = run_script(recipe, store=apollo_store({}, total=60), seen=seen)             # the page was opened without the filters: its embedded list is NOT used for them
    data = json.loads(out)
    assert data["filters_match"] is False and data["results_matching"] is None and data["sorts"][0]["first_page_from"] == "api" and [r["input"]["page"] for r in seen][:2] == [1, 2]
    assert all(r["input"]["filterByLabel"] == ["free_cancellation", "skip_the_line"] for r in seen)


def test_a_failing_second_sort_or_page_is_said_and_never_hides_what_was_read():
    out, recipe = run_script(fail_sort="highest_weighted_rating")
    data = json.loads(out)
    assert data["ok"] is True and data["failed"] and "Best reviewed page 1" in data["failed"][0] and data["sorts"][0]["read"] == 30 and data["sorts"][1]["read"] == 0
    problems = convert_one(out, recipe)[2]
    assert any("no activity of the Best reviewed sort was read" in p and "answered 500" in p for p in problems)
    out, recipe = run_script(fail_all=True)
    data = json.loads(out)
    assert data["ok"] is True and data["sorts"][0]["read"] == 15 and any("Our top picks page 2" in f for f in data["failed"])       # the 15 of the page's own data stay


def test_the_script_stops_on_a_human_check_a_page_without_data_and_a_page_that_is_not_an_attractions_page():
    assert "human check" in json.loads(run_script(check=True)[0])["error"]
    assert "no activity data" in json.loads(run_script(html="<html><body><h1>Lisbon</h1></body></html>")[0])["error"]
    bad = json.loads(run_script(path="/hotel/pt/ritz.html")[0])
    assert bad["ok"] is False and "not a Booking.com attractions results page" in bad["error"]
