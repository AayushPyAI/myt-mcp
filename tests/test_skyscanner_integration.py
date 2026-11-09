"""Skyscanner recipe, read from the page's own search service.

The REAL script runs in a real browser (Playwright's Chromium) on a skyscanner.net results page that serves what the real site served on 7 Nov 2026: the page state window.__internal (viewId, culture and, on a results page, searchParams with the entity ids), the place lookup GET /g/autosuggest-search/api/v1/search-flight/<market>/<locale>/<code> (GeoId = the airport's entity id)
and the search service POST /g/radar/api/v2/web-unified-search/ (answers "incomplete" with a session id and the first tickets) then GET .../<session id> (answers "complete" with every itinerary: price.raw
of the whole group, legs with segments, stop count, duration, sellers, score). Nothing leaves the machine. The mock prices nothing by itself: the checks are on what the script SENDS (entity ids, date parts, ages, headers)
and on what it makes of the answer (Best = score descending, Cheapest = price ascending, direct only on the stop count, windows, refusals)."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import unquote, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.skyscanner import skyscanner_recipe

DAY = date(2027, 3, 6)
SID = "session-abc-123"


def agent(i, name, carrier=False):
    return {"id": f"a{i}", "name": name, "isCarrier": carrier, "updateStatus": "current", "rating": 4, "feedbackCount": 10}


AGENTS = [agent(1, "Vueling Airlines", True), agent(2, "Booking.com"), agent(3, "Mytrip"), agent(4, "TAP Air Portugal", True)]


def seg(frm, to, dep, arr, mins, code, num, mk="Vueling Airlines", op=None):
    return {"id": f"{frm}-{to}-{num}", "origin": {"entityId": "1", "flightPlaceId": frm, "displayCode": frm, "name": frm}, "destination": {"entityId": "2", "flightPlaceId": to, "displayCode": to, "name": {"BCN": "Barcelona", "LIS": "Lisbon", "FCO": "Rome Fiumicino"}.get(to, to)},
            "departure": dep, "arrival": arr, "durationInMinutes": mins, "flightNumber": num, "marketingCarrier": {"id": 1, "name": mk, "alternateId": code, "displayCode": code}, "operatingCarrier": {"id": 2, "name": op or mk}, "transport": {"mode": "TRANSPORT_MODE_FLIGHT"}}


def itin(i, raw, score, stops=1, dep="13:10", arr="16:55", mins=285, mk="Vueling Airlines", op=None, code="VY", options=None, self_transfer=False, delta=0, **extra):
    if stops == 0:
        segs = [seg("FLR", "LIS", f"2027-03-06T{dep}:00", f"2027-03-06T{arr}:00", mins, code, str(100 + i), mk, op)]
    else:
        segs = [seg("FLR", "BCN", f"2027-03-06T{dep}:00", "2027-03-06T14:55:00", 105, code, str(6075 + i), mk, op), seg("BCN", "LIS", "2027-03-06T15:50:00", f"2027-03-06T{arr}:00", mins - 105 - 55, code, str(8000 + i), mk, op)]
    return {"id": f"it{i}", "token": "tok", "price": {"raw": raw, "formatted": f"{raw:.0f} €", "pricingOptionId": "po"}, "score": score, "isSelfTransfer": self_transfer, "isProtectedSelfTransfer": False,
            "legs": [{"id": f"it{i}", "origin": {"id": "FLR"}, "destination": {"id": "LIS"}, "durationInMinutes": mins, "stopCount": stops, "isSmallestStops": False, "departure": f"2027-03-06T{dep}:00", "arrival": f"2027-03-06T{arr}:00",
                      "timeDeltaInDays": delta, "carriers": {"marketing": [{"name": mk}]}, "segments": segs}],
            "farePolicy": {}, "emissions": {"emissionsKg": 188.9, "emissionsLevel": "typical"}, "fareAttributes": {}, "tags": [], "pricingOptions": options or [
                {"agentIds": ["a1"], "price": {"amount": raw}, "items": [{"agentId": "a1", "price": {"amount": raw}}], "pricingOptionId": "po"},
                {"agentIds": ["a2"], "price": {"amount": round(raw + 6.4, 2)}, "items": [{"agentId": "a2", "price": {"amount": round(raw + 6.4, 2)}}], "pricingOptionId": "po2"}], **extra}


ITINERARIES = [itin(1, 325.34, 9.0, stops=0, dep="12:20", arr="14:30", mins=190, mk="TAP Air Portugal", op="Portugalia Airlines", code="TP"),
               itin(2, 215.68, 8.0), itin(3, 146.0, 3.0, dep="21:00", arr="08:30", mins=690, delta=1, self_transfer=True), itin(4, 174.07, 7.0, dep="09:50", arr="16:55", mins=425),
               itin(5, 300.0, 6.0, stops=0, dep="06:00", arr="08:10", mins=130, mk="Azores Airlines", code="S4"), itin(6, 250.0, 5.0)]


IDS = {"FLR": "95673830", "LIS": "95565055", "FCO": "95673559"}


def page_html(adults=2, children=(6,), cabin="economy", date_="2027-03-06", legs=1, state="full", body="Florence to Lisbon", origin="FLR", destination="LIS", **kw):
    """state: "full" = a results page (searchParams + viewId + culture), "session" = any other Skyscanner page (viewId + culture only), "none" = no Skyscanner state at all."""
    leg = {"originId": origin, "destinationId": destination, "originEntityId": IDS[origin], "destinationEntityId": IDS[destination], "date": date_}
    internal = {"viewId": "view-1", "culture": {"currency": "EUR", "locale": "en-GB", "market": "UK"}}
    if state == "full":
        internal["searchParams"] = {"adultsV2": adults, "childrenV2": list(children), "cabinClass": cabin, "legs": [leg] * legs}
    script = f"window.__internal = {json.dumps(internal)};" if state != "none" else ""
    return f"<html><head><title>Skyscanner</title></head><body><h1>{body}</h1><script>{script}</script></body></html>"


def run_script(itineraries=ITINERARIES, status_flow=("incomplete", "complete"), seen=None, post_status=200, get_status=200, html=None, limit=20, offset=0, direct=False, final_context=None, lookup_status=200, lookup_ids=None, origin="flr", destination="lis", **kw):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = skyscanner_recipe(origin, destination, DAY, 2, [6], "economy", direct, limit, offset)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"
    polls = {"n": 0}

    def answer(status, results):
        return {"context": {"status": status, "sessionId": SID}, "itineraries": {"context": {"status": "success" if status == "complete" else "incomplete", "totalResults": len(results), **(final_context or {})},
                "results": results, "agents": AGENTS if results else [], "buckets": [], "filterStats": {}}, "carHire": {}}

    def serve(route):
        r = route.request
        u = urlparse(r.url)
        if u.hostname != "www.skyscanner.net":
            route.abort()
        elif u.path.startswith("/g/autosuggest-search/api/v1/search-flight/"):
            code = unquote(u.path.rsplit("/", 1)[1])
            if seen is not None:
                seen.append({"method": "LOOKUP", "path": u.path, "headers": r.headers})
            ids = lookup_ids if lookup_ids is not None else IDS
            if lookup_status != 200:
                route.fulfill(status=lookup_status, content_type="application/json", body="[]")
            else:      # the real lookup answers the airport first and then the places around it
                hits = ([{"PlaceId": code, "PlaceName": code, "GeoId": ids[code]}] if code in ids else []) + [{"PlaceId": code + "X", "PlaceName": "Somewhere else", "GeoId": "1"}]
                route.fulfill(status=200, content_type="application/json", body=json.dumps(hits))
        elif u.path == "/g/radar/api/v2/web-unified-search/" and r.method == "POST":
            if seen is not None:
                seen.append({"method": "POST", "body": json.loads(r.post_data or "{}"), "headers": r.headers})
            if post_status != 200:
                route.fulfill(status=post_status, content_type="application/json", body=json.dumps({"errors": ["blocked"]}))
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(answer(status_flow[0], itineraries[:2] if status_flow[0] != "complete" else itineraries)))
        elif u.path.startswith("/g/radar/api/v2/web-unified-search/") and r.method == "GET":
            polls["n"] += 1
            if seen is not None:
                seen.append({"method": "GET", "session": unquote(u.path.rsplit("/", 1)[1]), "headers": r.headers})
            if get_status != 200:
                route.fulfill(status=get_status, content_type="application/json", body="{}")
            else:
                st = status_flow[min(polls["n"], len(status_flow) - 1)]
                route.fulfill(status=200, content_type="application/json", body=json.dumps(answer(st, itineraries)))
        elif u.path.startswith("/transport/flights/"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or page_html(**kw))
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


def test_the_script_sends_the_pages_own_search_and_reads_every_ticket_in_both_orders():
    seen: list = []
    out, recipe = run_script(seen=seen)
    data = read(out)
    assert data["ok"] is True and data["status"] == "complete" and data["results_total"] == 6 and data["matching_total"] == 6 and data["polls"] >= 1
    post = seen[0]
    assert post["method"] == "POST" and post["body"] == {"cabinClass": "economy", "childAges": [6], "adults": 2, "legs": [{"legOrigin": {"@type": "entity", "entityId": "95673830"}, "legDestination": {"@type": "entity", "entityId": "95565055"},
                                                                                                                       "dates": {"@type": "date", "year": "2027", "month": "03", "day": "06"}}]}
    h = post["headers"]
    assert h["x-skyscanner-viewid"] == "view-1" and h["x-skyscanner-trustedfunnelid"] == "view-1" and h["x-skyscanner-currency"] == "EUR" and h["x-skyscanner-market"] == "UK" and h["x-skyscanner-locale"] == "en-GB" and h["x-skyscanner-channelid"] == "website"
    assert seen[1]["method"] == "GET" and seen[1]["session"] == SID and seen[1]["headers"]["x-skyscanner-viewid"] == "view-1"        # the poll carries the session id the first answer gave
    best = [r for r in data["rows"] if r["sort"] == "Best"]
    cheap = [r for r in data["rows"] if r["sort"] == "Cheapest"]
    assert [r["id"] for r in best] == ["it1", "it2", "it4", "it5", "it6", "it3"] and [r["total"] for r in best] == [325.34, 215.68, 174.07, 300.0, 250.0, 146.0]       # score descending: 9, 8, 7, 6, 5, 3
    assert [r["total"] for r in cheap] == [146.0, 174.07, 215.68, 250.0, 300.0, 325.34]                                                                      # price ascending
    top = best[0]
    assert top["mk"] == ["TAP Air Portugal"] and top["op"] == ["Portugalia Airlines"] and top["flights"] == ["TP 101"] and top["stops"] == 0 and top["sellers"][0] == {"n": "Vueling Airlines", "a": True, "p": 325.34}
    two = next(r for r in best if r["id"] == "it2")
    assert two["via"] == [{"code": "BCN", "name": "Barcelona"}] and two["layover"] == 55 and two["flights"] == ["VY 6077", "VY 8002"] and two["airline_price"] == 215.68 and two["seller_count"] == 2
    night = next(r for r in best if r["id"] == "it3")
    assert night["plus"] == 1 and night["self_transfer"] is True
    assert data["route"] == ["FLR", "LIS"] and data["date"] == "2027-03-06" and data["adults"] == 2 and data["children_ages"] == [6] and data["cabin"] == "economy"


def test_the_answer_converts_to_offers_for_the_asked_search():
    out, recipe = run_script()
    wishes = {"expect": recipe["expect"]}
    offers, _, problems, _, notes = convert_all([{"site": "skyscanner", "result": out, "url": recipe["url"]}], wishes)
    assert not problems and len(offers) == 6 and all(o.quotable is False and o.currency == "EUR" for o in offers)         # 12 rows (two lists of 6) are 6 tickets
    top = next(o for o in offers if o.price_total == 325.34)
    assert top.name == "TAP Air Portugal (operated by Portugalia Airlines) 12:20-14:30 (3 h 10 min)" and top.details["flights"] == "TP 101" and top.details["per_person"].startswith("108.45 EUR")
    assert any("Skyscanner lists 6 tickets for this search" in n for n in notes)


def test_the_search_is_polled_until_it_is_complete():
    seen: list = []
    data = read(run_script(status_flow=("incomplete", "incomplete", "incomplete", "complete"), seen=seen)[0])
    assert data["ok"] is True and data["polls"] == 3 and data["results_total"] == 6 and [s["method"] for s in seen] == ["POST", "GET", "GET", "GET"]


def test_direct_only_is_applied_on_the_stop_count_and_reported():
    out, recipe = run_script(direct=True)
    data = read(out)
    assert data["direct_only"] is True and data["results_total"] == 6 and data["matching_total"] == 2 and {r["stops"] for r in data["rows"]} == {0}
    offers, _, problems, _, notes = convert_all([{"site": "skyscanner", "result": out, "url": recipe["url"]}], {"expect": recipe["expect"]})
    assert not problems and len(offers) == 2 and all(o.fits is True for o in offers) and any("(2 of them direct)" in n for n in notes)


def test_the_window_per_list_starts_after_the_tickets_already_shown():
    data = read(run_script(limit=2, offset=2)[0])
    best = [r for r in data["rows"] if r["sort"] == "Best"]
    cheap = [r for r in data["rows"] if r["sort"] == "Cheapest"]
    assert [r["rank"] for r in best] == [3, 4] and [r["rank"] for r in cheap] == [3, 4] and [r["total"] for r in cheap] == [215.68, 250.0] and data["offset"] == 2


def test_a_human_check_or_a_block_stops_the_script_and_is_never_retried():
    seen: list = []
    data = read(run_script(post_status=403, seen=seen)[0])
    assert data["ok"] is False and "human check or block, HTTP 403" in data["error"] and "do not work around it" in data["error"] and len(seen) == 1
    poll = read(run_script(get_status=429, seen=[])[0])
    assert poll["ok"] is False and "HTTP 429" in poll["error"]
    shown = read(run_script(html=page_html(body="Are you a person or a robot? Press & Hold"))[0])
    assert shown["ok"] is False and "human check (captcha)" in shown["error"]


def test_a_search_that_never_completes_or_fails_is_said_not_guessed():
    failed = read(run_script(status_flow=("complete",), final_context={"status": "failure"})[0])
    assert failed["ok"] is False and "search failed" in failed["error"]
    http = read(run_script(get_status=500)[0])
    assert http["ok"] is False and "could not be read (answered 500" in http["error"]


SEARCH_BODY = {"cabinClass": "economy", "childAges": [6], "adults": 2, "legs": [{"legOrigin": {"@type": "entity", "entityId": "95673830"}, "legDestination": {"@type": "entity", "entityId": "95565055"}, "dates": {"@type": "date", "year": "2027", "month": "03", "day": "06"}}]}


def test_the_results_pages_own_ids_are_used_when_it_is_the_same_airports_and_no_lookup_is_made():
    seen: list = []
    data = read(run_script(seen=seen)[0])
    assert data["ok"] is True and data["entities"] == {"origin": "page", "destination": "page"} and [x["method"] for x in seen][0] == "POST" and "LOOKUP" not in {x["method"] for x in seen}
    assert seen[0]["body"] == SEARCH_BODY


def test_any_skyscanner_page_works_the_airport_ids_come_from_the_places_own_lookup():
    seen: list = []
    data = read(run_script(html=page_html(state="session"), seen=seen)[0])      # the home page: no search in its state
    assert data["ok"] is True and data["entities"] == {"origin": "lookup", "destination": "lookup"} and data["results_total"] == 6
    lookups = [x for x in seen if x["method"] == "LOOKUP"]
    assert [x["path"] for x in lookups] == ["/g/autosuggest-search/api/v1/search-flight/UK/en-GB/FLR", "/g/autosuggest-search/api/v1/search-flight/UK/en-GB/LIS"]       # the page's market and locale, the exact airport code
    assert lookups[0]["headers"]["x-skyscanner-viewid"] == "view-1" and next(x for x in seen if x["method"] == "POST")["body"] == SEARCH_BODY


def test_a_results_page_of_other_airports_is_not_trusted_for_these_airports():
    seen: list = []
    data = read(run_script(html=page_html(origin="FCO", destination="LIS"), seen=seen)[0])
    assert data["ok"] is True and data["entities"] == {"origin": "lookup", "destination": "page"}      # LIS is the same airport on that page, FCO is not
    assert [x["path"].rsplit("/", 1)[1] for x in seen if x["method"] == "LOOKUP"] == ["FLR"] and next(x for x in seen if x["method"] == "POST")["body"] == SEARCH_BODY


def test_the_place_lookup_that_knows_no_such_airport_or_is_blocked_is_said_not_guessed():
    unknown = read(run_script(html=page_html(state="session"), lookup_ids={"LIS": "95565055"})[0])
    assert unknown["ok"] is False and "no airport with the code FLR" in unknown["error"]
    seen: list = []
    blocked = read(run_script(html=page_html(state="session"), lookup_status=403, seen=seen)[0])
    assert blocked["ok"] is False and "HTTP 403" in blocked["error"] and "do not work around it" in blocked["error"] and "POST" not in {x["method"] for x in seen}       # no search is sent after a block
    down = read(run_script(html=page_html(state="session"), lookup_status=500)[0])
    assert down["ok"] is False and "place lookup could not be read" in down["error"]


def test_a_page_without_a_skyscanner_session_or_another_site_is_refused():
    gone = read(run_script(html=page_html(state="none"))[0])
    assert gone["ok"] is False and "no Skyscanner session" in gone["error"]


def test_the_answer_says_what_was_sent_so_the_converter_can_check_it_against_the_wish():
    out, recipe = run_script(html=page_html(state="session"))
    data = read(out)
    assert data["route"] == ["FLR", "LIS"] and data["date"] == "2027-03-06" and data["adults"] == 2 and data["children_ages"] == [6] and data["cabin"] == "economy"
    offers, _, problems, _, _ = convert_all([{"site": "skyscanner", "result": out, "url": recipe["url"]}], {"expect": recipe["expect"]})
    assert not problems and offers


def test_a_ticket_without_a_price_is_counted_not_invented():
    bad = {**itin(9, 100.0, 4.0), "price": {"formatted": "100 €"}}
    data = read(run_script(itineraries=ITINERARIES + [bad])[0])
    assert data["ok"] is True and data["unparsed"] == 1 and data["results_total"] == 7 and all(r["id"] != "it9" for r in data["rows"])      # left out of the lists, counted
    offers, _, problems, _, _ = convert_all([{"site": "skyscanner", "result": json.dumps(data), "url": "u"}], {"expect": skyscanner_recipe("flr", "lis", DAY, 2, [6])["expect"]})
    assert any("1 Skyscanner ticket(s) came without a price" in p for p in problems)
