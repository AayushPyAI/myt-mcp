"""CP trains, integration: the REAL script runs in a real browser (Playwright's Chromium) on a cp.pt page that serves what the real site serves (read live 5 Nov 2026): /fe-config.json with the travel service's keys,
GET .../travel-api/stations and POST .../travel-api/journeys (200 with `outwardTrip`, or 401 without the keys). Nothing leaves the machine. The rows the script makes go through the server's converter, and are compared
with the rows these tests derive in Python from the same answer."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.cp_trains import cp_trains_recipe

CFG = {"travelApiUrl": "https://api-gateway.cp.pt/cp/services/travel-api", "travelApiKey": "K" * 36, "xcck": "a" * 32, "xccs": "b" * 32}
STATIONS = [{"code": "94-31039", "designation": "Lisboa Oriente", "region": "Lisboa"}, {"code": "94-36004", "designation": "Coimbra-B", "region": None}, {"code": "94-2006", "designation": "Porto Campanha", "region": "Porto"}]
RULES = [{"ruleKey": "min_tickets_qty", "value": "1"}, {"ruleKey": "calendar_limit", "value": "60"}, {"ruleKey": "max_tickets_qty", "value": "9"}, {"ruleKey": "dep_after_arr_limit", "value": "15"}]
CORS = {"access-control-allow-origin": "*", "access-control-allow-headers": "*"}


def trip(dep, arr, dur, code="IC", design="Intercidades", n=0, promo=True, saleable=True, first=False):
    cls = 1 if first else 2
    base = [{"travelClass": cls, "priceType": 1, "centsValue": 2805, "constraints": []}, {"travelClass": cls, "priceType": 100, "centsValue": 5610, "constraints": []}]
    if promo:
        base += [{"travelClass": cls, "priceType": 4, "centsValue": 1700, "constraints": [{"code": "NON_REFUNDABLE"}]}, {"travelClass": cls, "priceType": 104, "centsValue": 3400, "constraints": [{"code": "NON_REFUNDABLE"}]}]
    base += [{"travelClass": 3 - cls, "priceType": 100, "centsValue": 99999, "constraints": []}]          # the other class: never read
    sections = [{"sequenceNumber": 1, "trainNumber": 521, "serviceCode": {"code": code, "designation": design}}] + ([{"sequenceNumber": 2, "trainNumber": 130, "serviceCode": {"code": "R", "designation": "Regional"}}] if n else [])
    return {"arrivalTime": arr, "departureTime": dep, "duration": dur, "services": code, "transferCount": n, "saleableOnline": saleable, "travelSections": sections, "basePrices": base, "bike": 1}


TRIPS = [trip("06:39", "09:43", "03h04"), trip("07:09", "09:48", "02h39", "AP", "Alfa Pendular", promo=False), trip("12:39", "16:10", "03h31", "IC", "Intercidades", n=1, saleable=False)]


def rows_from(trips, cls=2):
    """What the script makes of the answer, in Python (kept in step with cp_trains.js by the test below)."""
    rows = []
    for t in trips:
        prices = {p["priceType"]: p for p in t["basePrices"] if p["travelClass"] == cls}
        c = lambda k: prices[k]["centsValue"] / 100 if k in prices else None          # noqa: E731
        lim = lambda k: [x["code"] for x in prices[k]["constraints"]] if k in prices else []          # noqa: E731
        promo_limits = lim(104) or lim(4)
        rows.append({"leg": "out", "dep": t["departureTime"], "arr": t["arrivalTime"], "dur": t["duration"], "changes_n": t["transferCount"], "services": [s["serviceCode"]["designation"] for s in t["travelSections"]],
                     "codes": [s["serviceCode"]["code"] for s in t["travelSections"]], "trains": [s["trainNumber"] for s in t["travelSections"]], "cls": cls, "price_normal": c(100), "price_promo": c(104), "pp_normal": c(1), "pp_promo": c(4),
                     "promo_limits": promo_limits, "normal_limits": lim(100) or lim(1), "price_types": [p["priceType"] for p in t["basePrices"] if p["travelClass"] == cls], "saleable": t["saleableOnline"], "bike": t["bike"], "mobility": t.get("mobility"), "from_window": False})
    return rows


BACK = [trip("08:45", "12:00", "03h15", "IC", "Intercidades", promo=False), trip("10:45", "13:50", "03h05", "AP", "Alfa Pendular", promo=False), trip("15:10", "18:20", "03h10", "IC", "Intercidades", promo=True)]


def run_script(trips=TRIPS, back=None, back_extra=None, return_day=None, train_types=None, back_earliest=None, back_latest=None, window_extra=None, earliest=None, latest=None, html="<html><body><h1>CP</h1></body></html>", config=CFG, journeys_status=200, seen=None, first_class=False, messages=None, stations=STATIONS, origin="Lisboa Oriente", destination="Coimbra-B"):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = cp_trains_recipe(origin, destination, date(2026, 11, 25), 2, first_class=first_class, earliest=earliest, latest=latest, return_day=return_day, train_types=train_types, back_earliest=back_earliest, back_latest=back_latest)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def serve(route):
        u = urlparse(route.request.url)
        if u.hostname == "www.cp.pt" and u.path == "/fe-config.json":
            route.fulfill(status=200, content_type="application/json", body=json.dumps(config))
        elif u.hostname == "www.cp.pt":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif u.hostname == "api-gateway.cp.pt":
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=CORS)
                return
            h = route.request.headers
            ok = h.get("x-api-key") == CFG["travelApiKey"] and h.get("x-cp-connect-id") == CFG["xcck"] and h.get("x-cp-connect-secret") == CFG["xccs"]
            if seen is not None:
                seen.append({"path": u.path.rsplit("/", 1)[-1], "keys_ok": ok, "body": json.loads(route.request.post_data) if route.request.post_data else None})
            if not ok:
                route.fulfill(status=401, content_type="application/json", headers=CORS, body=json.dumps({"message": "Unauthorized"}))
            elif u.path.endswith("/rules"):
                route.fulfill(status=200, content_type="application/json", headers=CORS, body=json.dumps(RULES))
            elif u.path.endswith("/stations"):
                route.fulfill(status=200, content_type="application/json", headers=CORS, body=json.dumps(stations))
            elif u.path.endswith("/journeys"):
                asked = json.loads(route.request.post_data)
                limit = asked["timeLimit"]["limitType"]
                shown = list(trips) + (list(window_extra or []) if limit == 2 else [])          # a departure window also brings connections the plain list lacks (read live 5 Nov 2026)
                wanted = asked.get("services") or []
                only = lambda ts: [t for t in ts if all(s["serviceCode"]["code"] in wanted for s in t["travelSections"])] if wanted else ts          # the service's own filter: trains made of those services alone
                shown = only(shown)
                way_back = only(list(back if back is not None else BACK) + (list(back_extra or []) if asked["returnTimeLimit"]["limitType"] == 2 else [])) if asked.get("returnDate") else []
                body = {"departureStation": {"code": "94-31039"}, "arrivalStation": {"code": "94-36004"}, "travelDate": "2026-11-25", "returnDate": None, "outwardTrip": shown, "returnTrip": way_back, "messages": messages or []}
                route.fulfill(status=journeys_status, content_type="application/json", headers=CORS, body=json.dumps(body if journeys_status == 200 else {"message": "Bad Request"}))
            else:
                route.abort()
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto("https://www.cp.pt/en")
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def test_the_real_script_sends_cps_own_request_with_the_pages_keys_and_makes_the_same_rows_the_unit_tests_expect():
    seen: list = []
    out, recipe = run_script(seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["origin"] == {"code": "94-31039", "name": "Lisboa Oriente"} and data["destination"]["name"] == "Coimbra-B" and data["day"] == "2026-11-25" and data["passengers"] == 2 and data["cls"] == 2
    assert data["trips_total"] == 3 and data["no_results"] is False and data["rows"] == json.loads(json.dumps(rows_from(TRIPS)))          # the JavaScript and the Python read the answer the same way
    journeys = next(s for s in seen if s["path"] == "journeys")
    assert all(s["keys_ok"] for s in seen) and journeys["body"]["departureStationCode"] == "94-31039" and journeys["body"]["arrivalStationCode"] == "94-36004" and journeys["body"]["travelDate"] == "2026-11-25"
    assert journeys["body"]["classes"] == [2] and journeys["body"]["quantities"] == [{"quantity": 2, "type": 1}]
    wishes = {"expect": {**recipe["expect"], "direct_only": True}}
    offers, sources, problems, _, notes = convert_all([{"site": "cp_trains", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)
    assert problems == [] and [o.price_total for o in offers] == [34.0, 56.1, 34.0] and [o.fits for o in offers] == [True, True, False]       # the third train changes
    assert "NOT sold online" in offers[2].details["conditions"]
    refundable = convert_all([{"site": "cp_trains", "result": out, "url": recipe["url"], "wishes": {"expect": {**recipe["expect"], "refundable": True}}}], {"expect": {**recipe["expect"], "refundable": True}})[0]
    assert [o.price_total for o in refundable] == [56.1, 56.1, 56.1]


def test_first_class_reads_the_first_class_prices_and_notices_are_carried():
    t = [trip("06:39", "09:43", "03h04", first=True)]
    data = json.loads(run_script(t, first_class=True, messages=[{"type": "WARNING", "text": "<p qw-selector='x'>Oeste line:  replacement bus</p>"}])[0])
    assert data["cls"] == 1 and data["rows"] == json.loads(json.dumps(rows_from(t, cls=1))) and data["rows"][0]["price_normal"] == 56.1 and data["notices"] == ["Oeste line: replacement bus"]


def test_no_trains_is_an_answer_a_failed_service_a_missing_key_and_an_unknown_station_are_each_named():
    empty = json.loads(run_script([])[0])
    assert empty["ok"] is True and empty["no_results"] is True and empty["rows"] == []
    refused = json.loads(run_script(journeys_status=400)[0])
    assert refused["ok"] is False and "answered 400" in refused["error"] and "Bad Request" in refused["error"]
    nokeys = json.loads(run_script(config={"travelApiUrl": CFG["travelApiUrl"]})[0])
    assert nokeys["ok"] is False and "no travel service entries" in nokeys["error"]
    badkeys = json.loads(run_script(config={**CFG, "xccs": "wrong"})[0])
    assert badkeys["ok"] is False and "answered 401" in badkeys["error"]
    unknown = json.loads(run_script(stations=[STATIONS[0]])[0])
    assert unknown["ok"] is False and "no station with the code 94-36004" in unknown["error"]
    blocked = json.loads(run_script(html="<html><body>Access denied</body></html>")[0])
    assert blocked["ok"] is False and "human check or refuses" in blocked["error"]


def test_a_time_wish_also_asks_cps_own_departure_window_and_joins_the_extra_trains():
    extra = [trip("12:39", "16:48", "04h09", "IC", "Intercidades", n=1)]
    seen: list = []
    data = json.loads(run_script(window_extra=extra, earliest="08:00", latest="14:00", seen=seen)[0])
    sent = [s["body"]["timeLimit"] for s in seen if s["path"] == "journeys"]
    assert sent == [{"startTime": "00:00", "endTime": "23:59", "limitType": 0}, {"startTime": "08:00", "endTime": "14:00", "limitType": 2}]
    assert data["window_sent"] == {"startTime": "08:00", "endTime": "14:00", "limitType": 2} and data["trips_unfiltered"] == 3 and data["window_extra"] == 1 and data["trips_total"] == 4
    assert [r["from_window"] for r in data["rows"]] == [False, False, False, True] and data["rows"][3]["dep"] == "12:39"
    plain = json.loads(run_script(window_extra=extra, seen=[])[0])
    assert plain["window_sent"] is None and plain["trips_total"] == 3 and plain["window_extra"] == 0          # no time wish: one request
    only_latest = []
    run_script(window_extra=extra, latest="12:00", seen=only_latest)
    assert [s["body"]["timeLimit"] for s in only_latest if s["path"] == "journeys"][1] == {"startTime": "00:00", "endTime": "12:00", "limitType": 2}


def test_cps_own_rules_are_read_for_the_days_ahead_and_the_ticket_limit():
    data = json.loads(run_script()[0])
    assert data["calendar_limit_days"] == 60 and data["max_tickets"] == 9


def test_a_return_trip_is_one_call_with_its_own_leg_rows_window_and_group():
    seen: list = []
    extra_back = [trip("12:50", "16:00", "03h10", "IC", "Intercidades", promo=False)]
    out, recipe = run_script(return_day=date(2026, 11, 27), back_earliest="10:00", back_latest="14:00", back_extra=extra_back, seen=seen)
    data = json.loads(out)
    sent = [s["body"] for s in seen if s["path"] == "journeys"]
    assert all(b["returnDate"] == "2026-11-27" for b in sent) and sent[0]["returnTimeLimit"]["limitType"] == 0 and sent[1]["returnTimeLimit"] == {"startTime": "10:00", "endTime": "14:00", "limitType": 2}
    assert sent[1]["timeLimit"]["limitType"] == 0          # no outward time wish: its window is the plain one
    assert data["return_day"] == "2026-11-27" and data["out_total"] == 3 and data["back_total"] == 4 and data["trips_total"] == 7 and data["window_back_sent"]["limitType"] == 2 and data["window_extra"] == 1
    assert [r["leg"] for r in data["rows"]] == ["out"] * 3 + ["back"] * 4 and [r["from_window"] for r in data["rows"][3:]] == [False, False, False, True]
    wishes = {"expect": {**recipe["expect"], "back_earliest": "10:00", "back_latest": "14:00"}}
    offers, _, problems, _, notes = convert_all([{"site": "cp_trains", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)
    assert problems == [] and len(offers) == 7
    assert {o.group for o in offers[:3]} == {"Lisboa Oriente to Coimbra-B, 25 Nov 2026"} and {o.group for o in offers[3:]} == {"Coimbra-B to Lisboa Oriente, 27 Nov 2026"}
    assert [o.fits for o in offers[3:]] == [False, True, False, True]          # return times are judged against the return window, not the outward one
    assert any("Each leg is priced alone" in n for n in notes) and any("time filter was also asked for the return" in n for n in notes)


def test_a_return_leg_with_no_trains_is_said_for_that_leg_and_a_same_day_return_names_the_waiting_rule():
    out, recipe = run_script(back=[], return_day=date(2026, 11, 27))
    offers, _, problems, _, notes = convert_all([{"site": "cp_trains", "result": out, "url": recipe["url"]}], {"expect": recipe["expect"]})
    assert problems == [] and len(offers) == 3 and any("no trains for the return leg (Coimbra-B to Lisboa Oriente, 27 Nov 2026)" in n for n in notes)
    same = run_script(return_day=date(2026, 11, 25))
    s_offers, _, _, _, s_notes = convert_all([{"site": "cp_trains", "result": same[0], "url": same[1]["url"]}], {"expect": same[1]["expect"]})
    assert any("Same-day return" in n and "less than 15 minutes after the earliest fitting outward train arrives is marked not fitting" in n for n in s_notes)


def test_train_types_go_to_cps_own_filter_international_included_and_every_train_is_judged_here_too():
    seen: list = []
    out, recipe = run_script(train_types=["intercidades", "alfa pendular"], seen=seen)
    data = json.loads(out)
    assert all(s["body"]["services"] == ["IC", "AP"] for s in seen if s["path"] == "journeys") and data["services_sent"] == ["IC", "AP"]
    assert [r["codes"] for r in data["rows"]] == [["IC"], ["AP"]]          # the 12:39 connection (IC + Regional) is not a train of those types alone
    intl = trip("09:00", "15:00", "06h00", "IN", "Internacionais", promo=False)
    s2: list = []
    data2 = json.loads(run_script(trips=TRIPS + [intl], train_types=["international"], seen=s2)[0])
    assert all(b["body"]["services"] == ["IN"] for b in s2 if b["path"] == "journeys") and data2["services_sent"] == ["IN"] and [r["codes"] for r in data2["rows"]] == [["IN"]]          # CP's code is IN (INT is an unknown code CP ignores)
    wishes = {"expect": {**recipe["expect"], "train_types": ["IN"]}}
    offers = convert_all([{"site": "cp_trains", "result": json.dumps(data2), "url": "u", "wishes": wishes}], wishes)[0]
    assert [o.fits for o in offers] == [True]
    other = convert_all([{"site": "cp_trains", "result": out, "url": "u", "wishes": wishes}], wishes)[0]
    assert [o.fits for o in other] == [False, False]          # IC and AP trains are not international


def test_the_bicycle_and_wheelchair_flags_are_read_and_the_station_count_is_reported():
    t = [{**trip("06:39", "09:43", "03h04"), "mobility": 1}]
    data = json.loads(run_script(t)[0])
    assert data["stations_total"] == 3 and data["rows"][0]["bike"] == 1 and data["rows"][0]["mobility"] == 1
