"""RateHawk hotels recipe, read from the results page's own search service.

The REAL script runs in a real browser (Playwright's Chromium) on a ratehawk.com results page that serves what the real site served on 7 Nov 2026: the page's dataLayer (the logged-in user's mail, the partner slug,
the search_uuid), the csrftoken cookie, a script from f.worldota.net/partner/sp/branch/<build>/ (the build address the page sends as X-Singlepage-Id), the page's own first call POST /hotel/search/v2/b2bsite/serp?session=<id>
(so the session id is in the page's resource log) and the service itself, answering 20 hotels a page with total_av_hotels, search_finished and per hotel its static data and its cheapest rate. Nothing leaves the machine.
The checks are on what the script SENDS (body, headers, address) and on what it makes of the answer."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.ratehawk_hotels import ratehawk_hotels_recipe

SESSION = "11111111-2222-3333-4444-555555555555"
UUID = "99999999-8888-7777-6666-000000000000"
BUILD = "//f.worldota.net/partner/sp/branch/bb33fff-749d149"
CSRF = "csrfvalue0123456789abcdef01234567"
IN, OUT = date(2027, 5, 3), date(2027, 5, 5)


def hotel(i, price, free_before="2027-05-01T00:00:00Z", meal=("breakfast",), stars=40, score=8.1, reviews=100, taxes=True, kind="Hotel", penalties=None):
    pens = penalties if penalties is not None else ([{"start_at": None, "end_at": free_before, "penalty": {"amount": "0.00", "percent": "0.00"}}, {"start_at": free_before, "end_at": None, "penalty": {"amount": f"{price:.2f}", "percent": "100.00"}}]
                                                     if free_before else [{"start_at": None, "end_at": None, "penalty": {"amount": f"{price:.2f}", "percent": "100.00"}}])
    tax = [{"name": "city_tax", "included_in_show": False, "amount": "8.00", "currency_code": "EUR"}, {"name": "vat", "included_in_show": True, "amount": "3.00", "currency_code": "EUR"}] if taxes else []
    return {"requested_hotel_id": f"h{i}", "master_id": 1000 + i, "sort_score": 1,
            "static_vm": {"name": f"Hotel {i}", "star_rating": stars, "rating_total": score, "ta_rating": {"num_reviews": reviews, "rating": 4.0}, "search_region_center_distance": 1.2345, "kind": kind, "otahotel_id": f"hotel_{i}",
                          "region_catalog_slug": "portugal/lisbon"},
            "rates": [{"room_name": "Double room (full double bed)", "meal": list(meal), "cancellation_info": {"free_cancellation_before": free_before, "policies": pens}, "allotment": 2,
                       "payment_options": {"payment_types": [{"type": "deposit", "show_amount": f"{price:.2f}", "show_currency_code": "EUR", "currency_code": "EUR", "average_show_price_per_day": f"{price / 2:.2f}", "tax_data": {"taxes": tax}}]}}]}


HOTELS = [hotel(i, 100 + i * 10) for i in range(1, 26)]       # 25 hotels: page 1 holds 20, page 2 holds 5


def page_html(user=True, session=True, text="Lisbon: 25 accommodation options available"):
    layer = [{"user_email": "agent@example.test", "partner_slug": "132573.b2b.63ad"}, {"funnel": {"context": {"search_uuid": UUID}}}] if user else []
    first = (f"fetch('/hotel/search/v2/b2bsite/serp?session={SESSION}', {{method: 'POST', body: '{{}}'}});") if session else ""
    return (f"<html><head><title>Lisbon</title><script src='https://f.worldota.net/partner/sp/branch/bb33fff-749d149/module.js'></script></head><body><h1>{text}</h1>"
            f"<script>window.dataLayer = {json.dumps(layer)}; document.cookie = 'csrftoken={CSRF}; path=/'; {first}</script></body></html>")


def run_script(hotels=HOTELS, finished=(True,), seen=None, status=200, html=None, offset=0, limit=30, children=(), stars=None, breakfast=False, free_cancellation=False, sort="price_asc", text=None, patch_wait=True):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = ratehawk_hotels_recipe("portugal", "lisbon", IN, OUT, 2, sort, breakfast, free_cancellation, stars, 3, list(children), offset, limit)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"
    if patch_wait:
        script = script.replace("i < 90 &&", "i < 3 &&")       # the real wait is 45 s for a search RateHawk has not cached
    calls = {"n": 0}

    def serve(route):
        r = route.request
        u = urlparse(r.url)
        if u.hostname == "f.worldota.net":
            route.fulfill(status=200, content_type="text/javascript", body="")
        elif u.hostname != "www.ratehawk.com":
            route.abort()
        elif u.path == "/hotel/search/v2/b2bsite/serp" and r.method == "POST":
            body = json.loads(r.post_data or "{}")
            if body.get("page") is None:      # the page's own first call (empty body): only makes the session appear in the page's log
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"hotels": []}))
                return
            if seen is not None:
                seen.append({"query": parse_qs(u.query), "headers": r.headers, "body": body})
            if status != 200:
                route.fulfill(status=status, content_type="application/json", body=json.dumps({"data": None, "error": "session query parameter is required" if status == 400 else "forbidden"}))
                return
            calls["n"] += 1
            done = finished[min(calls["n"] - 1, len(finished) - 1)]
            page = body["page"]
            chunk = hotels[(page - 1) * 20: page * 20]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"hotels": chunk, "map_hotels": [], "total_hotels": 7343, "total_av_hotels": len(hotels), "total_av_hotels_no_filter": len(hotels) + 5, "search_finished": done}))
        elif u.path.startswith("/hotel/"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or page_html(**({"text": text} if text else {})))
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto(recipe["url"] + "&q=2080")       # RateHawk adds q=<region id> itself
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def read(out):
    return json.loads(out)


def test_the_script_builds_the_pages_own_call_from_the_pages_state_and_reads_every_hotel_of_the_window():
    seen: list = []
    out, recipe = run_script(seen=seen, children=(6,), stars=4, breakfast=True, free_cancellation=True)
    data = read(out)
    assert data["ok"] is True and data["results_total"] == 25 and data["search_finished"] is True and len(data["rows"]) == 25 and data["offset"] == 0 and data["page_header_count"] == 25
    call = seen[0]
    assert call["query"] == {"session": [SESSION]} and call["body"] == {
        "session_params": {"currency": "EUR", "language": "en", "search_uuid": UUID, "partner_slug_force": "132573.b2b.63ad", "arrival_date": "2027-05-03", "departure_date": "2027-05-05", "region_id": 2080, "residency": "en-il",
                           "paxes": [{"adults": 2, "child_ages": [6]}]},
        "page": 1, "filters": {"stars": [40, 50], "free_cancellation": True, "meals": ["breakfast"]}, "sort": "price_asc", "session_id": SESSION}
    h = call["headers"]
    assert h["x-csrftoken"] == CSRF and h["x-user-mail"] == "agent@example.test" and h["x-singlepage-id"] == BUILD and h["x-requested-with"] == "XMLHttpRequest" and h["content-type"] == "application/json"
    assert [c["body"]["page"] for c in seen] == [1, 2]                      # 25 hotels: page 2 has 5 (fewer than 20) so there is no page 3
    row = data["rows"][0]
    assert row["name"] == "Hotel 1" and row["stars"] == 4 and row["dist_km"] == 1.23 and row["score"] == 8.1 and row["reviews"] == 100 and row["amount"] == 110 and row["cur"] == "EUR" and row["per_night"] == 55
    assert row["taxes_extra"] == [{"n": "city_tax", "a": 8.0, "c": "EUR"}] and row["path"] == "/hotel/portugal/lisbon/mid1001/hotel_1/" and row["meal"] == ["breakfast"] and row["free_before"] == "2027-05-01T00:00:00Z"
    assert data["child_ages"] == [6] and data["filters"] == {"stars": [40, 50], "free_cancellation": True, "meals": ["breakfast"]} and data["sort"] == "price_asc" and "unparsed" not in data


def test_an_unfiltered_search_for_adults_only_sends_no_filters_and_no_child_ages():
    seen: list = []
    data = read(run_script(seen=seen)[0])
    body = seen[0]["body"]
    assert data["ok"] is True and "filters" not in body and body["session_params"]["paxes"] == [{"adults": 2}] and data["filters"] == {}


def test_the_window_runs_across_pages_and_the_offset_is_reported():
    seen: list = []
    data = read(run_script(seen=seen, offset=15, limit=10)[0])
    assert [r["rank"] for r in data["rows"]] == list(range(16, 26)) and data["offset"] == 15 and [c["body"]["page"] for c in seen] == [1, 2]
    one = read(run_script(seen=[], offset=20, limit=5)[0])
    assert [r["rank"] for r in one["rows"]] == [21, 22, 23, 24, 25] and one["offset"] == 20


def test_a_search_that_is_not_finished_is_asked_again_until_it_is():
    seen: list = []
    data = read(run_script(finished=(False, True), seen=seen, limit=20)[0])
    assert data["ok"] is True and data["search_finished"] is True and len(seen) == 2 and seen[0]["body"]["page"] == seen[1]["body"]["page"] == 1


def test_a_refusal_a_logged_out_page_and_a_page_that_never_searched_are_said_not_worked_around():
    seen: list = []
    refused = read(run_script(status=403, seen=seen)[0])
    assert refused["ok"] is False and "HTTP 403" in refused["error"] and "do not work around it" in refused["error"] and len(seen) == 1
    bad = read(run_script(status=400)[0])
    assert bad["ok"] is False and "answered 400" in bad["error"] and "session query parameter is required" in bad["error"]
    out = read(run_script(html=page_html(user=False))[0])
    assert out["ok"] is False and "no logged-in RateHawk user" in out["error"] and "never type a password" in out["error"]
    none = read(run_script(html=page_html(session=False))[0])
    assert none["ok"] is False and "has not started its search" in none["error"]


def test_a_hotel_without_a_rate_is_counted_not_invented():
    broken = dict(hotel(99, 100), rates=[])
    data = read(run_script(hotels=HOTELS[:3] + [broken])[0])
    assert data["ok"] is True and data["unparsed"] == 1 and len(data["rows"]) == 3
    _, recipe = run_script(hotels=HOTELS[:3], limit=3)
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_hotels", "result": json.dumps(data), "url": "u"}], {"expect": recipe["expect"]})
    assert any("1 RateHawk hotel(s) came without a rate" in p for p in problems)


def test_the_answer_converts_to_offers_with_deadlines_taxes_and_a_breakfast_that_may_not_cover_everyone():
    hs = [hotel(1, 200), hotel(2, 250, meal=("breakfast-for-2",)), hotel(3, 300, free_before=None, meal=("nomeal",), taxes=False)]
    out, recipe = run_script(hotels=hs, children=(6,), breakfast=True, free_cancellation=True, text="Lisbon: 3 accommodation options available")
    wishes = {"breakfast": True, "free_cancellation": True, "expect": recipe["expect"]}
    offers, sources, problems, by_price, _ = convert_all([{"site": "ratehawk_hotels", "result": out, "url": "https://www.ratehawk.com/hotel/portugal/lisbon/"}], wishes)
    assert not problems and by_price and sources[0].of == 3 and sources[0].read == 3
    one, two, three = offers
    assert one.fits is True and one.price_total == 200 and one.details["cancellation"].startswith("Free cancellation until 2027-05-01 00:00 UTC; then a fee: 200.00 EUR (100%) from 2027-05-01 00:00 UTC")
    assert one.details["taxes_not_in_price"] == "city_tax 8 EUR payable at the property" and one.price_basis == "whole stay: 2 nights for 3 guests" and one.link.endswith("/hotel/portugal/lisbon/mid1001/hotel_1/")
    assert two.details["meal"] == "Breakfast included for 2 guests only" and two.fits is False                    # 3 guests (2 adults and a child), breakfast for two
    assert three.fits is False and three.details["cancellation"] == "No free cancellation: 100% penalty (non-refundable)" and three.details["taxes_not_in_price"] == "none listed by RateHawk" and three.flexible is None


def test_a_page_header_that_disagrees_with_the_service_means_another_search_and_is_refused():
    out, recipe = run_script(text="Lisbon: 999 accommodation options available")
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_hotels", "result": out, "url": "u"}], {"expect": recipe["expect"]})
    assert any("header says 999 options and the search service 25" in p for p in problems)
