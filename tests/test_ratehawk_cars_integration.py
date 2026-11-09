"""RateHawk cars recipe, read from the page's own "load more" server action.

The REAL script runs in a real browser (Playwright's Chromium) on a ratehawk.com/cars results page that serves what the real site served on 7 Nov 2026: the page's first cars inside an inline
self.__next_f.push("...") string (so the quotes are escaped, as on the real page) holding {"sessionId": ..., "offers": [...]}, the page's cars script (static/chunks/app/cars/page-<hash>.js) with
createServerReference("<id>", ..., "getFilteredOffers"), and the server action itself: POST to the page's own address with the header next-action, answering text/x-component whose line "1:" is
{"offers": [...], "count": N} (10 a call; the filters in the body are applied by the mock the way RateHawk applied them live; count is the whole search's, as live). Nothing leaves the machine."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.ratehawk_cars import ratehawk_cars_recipe

SESSION = "6c995fb3-1cb1-442a-a03d-d10f1f878a3e"
ACTION = "40b9a99ceac4d113645549c22dabbc29e9a04669fd"
CHUNK = "/_next/static/chunks/app/cars/page-3dbf6b75e9359683.js"


def offer(i, gearbox="manual", ins="excess", sub="meet_greet", price=None, free=True):
    price = price if price is not None else 10 + i
    return {"id": None, "identifier": f"id-{i}",
            "pick_up": {"date_time": "2027-04-12T10:00:00Z", "office": {"type": "airport", "subtype": sub, "name": "Faro Airport", "address": "Rua X", "iata_code": "FAO"}},
            "drop_off": {"date_time": "2027-04-17T10:00:00Z", "office": {"type": "airport", "subtype": sub, "name": "Faro Airport"}},
            "vehicle": {"model": f"Car {i} ", "sipp_code": "MCMR", "category": "mini", "transmission_type": gearbox, "seats_number": 4, "doors_number": 3, "has_air_conditioning": True, "is_electric": False,
                        "small_bags_number": 2, "medium_bags_number": 0, "large_bags_number": 1},
            "rate": {"rental_company": {"label": "Bravacar", "rating": "5.4"}, "supplier": {"slug": "bsp_auto"}, "deposit": {"amount": "1400.00", "currency_code": "EUR"},
                     "insurance": {"type": ins, "cdw_excess": "1400.00", "theft_excess": "1400.00"}, "fuel_policy": "full_full", "mileage": 0,
                     "cancellation_policies": [{"amount_penalty": "0.00", "is_refundable": True, "start_at": "2027-04-01T10:00:00Z", "end_at": "2027-04-10T10:00:00Z"}] if free else [],
                     "fees": [{"label": "Additional driver", "is_included_in_rate": False, "payment": "on_site", "amount": "20.00", "type": "additional_driver"}], "additional_services": [{"label": "GPS", "is_included_in_rate": False, "payment": "on_site", "amount": "21.00"}],
                     "driver_requirements": {"minimum_age": 21, "maximum_age": 74, "minimum_driving_experience": 2, "young_driver_age": 26}},
            "total": {"partner": {"amount_sell": f"{price:.2f}", "currency_code": "EUR", "amount_service_fee": "8.94"}}}


def catalogue():
    out = []
    for i in range(25):
        out.append(offer(i, gearbox="automatic" if i % 2 == 0 else "manual", ins="zero_excess" if i % 5 == 0 else "excess", sub="in_terminal" if i % 3 == 0 else "meet_greet"))
    return out


OFFERS = catalogue()


def page_html(session=True, chunk=True, text="Search for cars"):
    first = json.dumps('6:[["$","$L51",null,{"sessionId":"' + SESSION + '","offers":[' + json.dumps(OFFERS[0]) + ']}]]\n') if session else json.dumps("6:[]\n")
    tag = f"<script src='{CHUNK}'></script>" if chunk else ""
    return f"<html><head><title>Cars</title>{tag}</head><body><h1>{text}</h1><script>self.__next_f = self.__next_f || []; self.__next_f.push([1,{first}])</script></body></html>"


def run_script(seen=None, status=200, html=None, limit=30, offset=0, automatic=False, zero_excess=False, airport_in_terminal=False, action_in_chunk=True, bare_answer=False, patch_wait=True):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = ratehawk_cars_recipe("Faro Airport", None, "2027-04-12", "10:00", "2027-04-17", "10:00", None, None, "26,69", "il", automatic, zero_excess, airport_in_terminal, 40, False, offset, limit)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"
    if patch_wait:
        script = script.replace("i < 60 &&", "i < 3 &&")       # the real wait is 30 s for a search RateHawk has not cached
    chunk_js = f'(0,Y.createServerReference)("{ACTION}",Y.callServer,void 0,Y.findSourceMapURL,"getFilteredOffers")' if action_in_chunk else "var x = 1;"

    def serve(route):
        r = route.request
        u = urlparse(r.url)
        if u.hostname != "www.ratehawk.com":
            route.abort()
        elif u.path == CHUNK:
            route.fulfill(status=200, content_type="text/javascript", body=chunk_js)
        elif u.path == "/cars/" and r.method == "POST":
            body = json.loads(r.post_data or "[]")[0]
            if seen is not None:
                seen.append({"query": u.query, "headers": r.headers, "body": body})
            if status != 200:
                route.fulfill(status=status, content_type="text/plain", body="denied")
                return
            if bare_answer:
                route.fulfill(status=200, content_type="text/x-component", body='0:{"a":"$@1"}\n')
                return
            f = body["filters"]
            pool = [o for o in OFFERS if all(o["vehicle"]["transmission_type"] in v for k, v in f.items() if k == "vehicle_transmission_type") and all(o["rate"]["insurance"]["type"] in v for k, v in f.items() if k == "rate_insurance_type")
                    and all(o["pick_up"]["office"]["subtype"] in v for k, v in f.items() if k == "pick_up_office_subtype")]
            part = pool[body.get("offset", 0): body.get("offset", 0) + body.get("limit", 10)]
            route.fulfill(status=200, content_type="text/x-component", body='0:{"a":"$@1","f":"","b":"x"}\n1:' + json.dumps({"offers": part, "count": len(OFFERS)}) + "\n")
        elif u.path == "/cars/":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or page_html())
        else:
            route.abort()
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


def read(out):
    return json.loads(out)


def test_the_script_finds_the_session_and_the_action_in_the_page_and_calls_it_in_batches_of_ten():
    seen: list = []
    out, recipe = run_script(seen=seen, limit=25)
    data = read(out)
    assert data["ok"] is True and len(data["rows"]) == 25 and data["search_total"] == 25 and data["offset"] == 0 and data["reached_cap"] is False and data["filters"] == {}
    assert [c["body"]["offset"] for c in seen] == [0, 10, 20] and all(c["body"] == {"filters": {}, "sessionId": SESSION, "offset": c["body"]["offset"], "limit": 10} for c in seen)
    h = seen[0]["headers"]
    assert h["next-action"] == ACTION and h["accept"] == "text/x-component" and h["content-type"].startswith("text/plain") and seen[0]["query"] == urlparse(recipe["url"]).query
    row = data["rows"][0]
    assert row["model"] == "Car 0" and row["sipp"] == "MCMR" and row["gearbox"] == "automatic" and row["price"] == 10 and row["currency"] == "EUR" and row["company"] == "Bravacar" and row["rating"] == 5.4
    assert row["deposit"] == 1400 and row["ins_type"] == "zero_excess" and row["mileage"] == 0 and row["fuel"] == "full_full" and row["pickup"]["at"] == "2027-04-12T10:00:00Z" and row["pickup"]["sub"] == "in_terminal"
    assert row["fees"] == [{"n": "Additional driver", "a": 20.0, "in": False, "pay": "on_site", "t": "additional_driver"}] and row["driver"] == {"min": 21, "max": 74, "years": 2, "young": 26}
    assert data["search"] == {"route": "965846144,965846144", "date": "2027-04-12T10:00,2027-04-17T10:00", "age": "26,69", "residency": "il"}


def test_the_filters_go_in_the_body_and_only_those_cars_come_back():
    seen: list = []
    data = read(run_script(seen=seen, limit=30, automatic=True, zero_excess=True, airport_in_terminal=True)[0])
    assert seen[0]["body"]["filters"] == {"vehicle_transmission_type": ["automatic"], "rate_insurance_type": ["zero_excess"], "pick_up_office_subtype": ["in_terminal"]}
    assert data["filters"] == seen[0]["body"]["filters"] and data["rows"] and all(r["gearbox"] == "automatic" and r["ins_type"] == "zero_excess" and r["pickup"]["sub"] == "in_terminal" for r in data["rows"])
    assert data["search_total"] == 25            # RateHawk's count is the whole search's: it does not shrink with the filters


def test_the_window_asks_only_for_the_batches_it_needs_and_says_when_more_exist():
    seen: list = []
    data = read(run_script(seen=seen, offset=10, limit=10)[0])
    assert [c["body"]["offset"] for c in seen] == [10] and [r["model"] for r in data["rows"]] == [f"Car {i}" for i in range(10, 20)] and data["offset"] == 10 and data["reached_cap"] is True
    odd = read(run_script(seen=[], offset=5, limit=10)[0])
    assert [r["model"] for r in odd["rows"]] == [f"Car {i}" for i in range(5, 15)]           # a window that starts inside a batch


def test_a_refusal_and_a_page_that_changed_are_said_not_worked_around():
    seen: list = []
    refused = read(run_script(status=403, seen=seen)[0])
    assert refused["ok"] is False and "HTTP 403" in refused["error"] and "do not work around it" in refused["error"] and len(seen) == 1
    assert "answered 500" in read(run_script(status=500)[0])["error"]
    assert "without a list" in read(run_script(bare_answer=True)[0])["error"]
    assert "no search session" in read(run_script(html=page_html(session=False))[0])["error"]
    assert "cars script was not found" in read(run_script(html=page_html(chunk=False))[0])["error"]
    assert "action was not found" in read(run_script(action_in_chunk=False)[0])["error"]
    login = read(run_script(html=page_html(text="Log in to RateHawk"))[0])
    assert login["ok"] is False and "never type a password" in login["error"]


def test_the_answer_converts_to_offers_for_the_asked_search_and_a_wrong_search_is_refused():
    out, recipe = run_script(limit=10, automatic=True)
    wishes = {"automatic": True, "expect": recipe["expect"]}
    offers, sources, problems, _, notes = convert_all([{"site": "ratehawk_cars", "result": out, "url": recipe["url"]}], wishes)
    assert not problems and len(offers) == 10 and all(o.fits is True and o.currency == "EUR" for o in offers) and offers[0].name == "Car 0 (MCMR • Mini)" and sources[0].read == 10
    assert offers[0].details["fees_not_in_price"] == "Additional driver 20 EUR (on site)" and offers[0].details["extras_on_site"] == "GPS 21 EUR (on site)" and offers[0].details["pickup_place"] == "Faro Airport (in the terminal)"
    wrong = dict(recipe["expect"], route="1,2", filters={})
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_cars", "result": out, "url": "u"}], {"expect": wrong})
    assert any("route '965846144,965846144', not '1,2'" in p for p in problems) and any("filters" in p for p in problems)
