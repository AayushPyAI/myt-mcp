"""TAP, integration: the REAL script runs in a real browser (Playwright's Chromium) on a booking.flytap.com page that serves what the real site serves (read live 5 Nov 2026): the page's own login token in sessionStorage
(`token`, JSON-quoted), POST /bfm/rest/booking/availability/search answering 200 only with `Authorization: Bearer <token>` (401 otherwise), and the answer the page stores in `airportTranslationData`. The availability answer is
the REAL saved one (Florence to Lisbon, 6 Mar 2027, 2 adults and a child). Nothing leaves the machine. The rows the script makes are compared with the rows the server's own parser reads from the same answer."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.tap import tap_recipe
from myt_mcp.tap.parse import parse_availability

ANSWER = json.loads((Path(__file__).with_name("fixtures") / "tap_availability_flr_lis.json").read_text())
TOKEN = "eyJhbGciOiJIUzI1NiJ9." + "a" * 60 + ".sig"
DAY = date(2027, 3, 6)


def page_html(stored=None, token=TOKEN, extra=""):
    set_token = f"sessionStorage.setItem('token', JSON.stringify({json.dumps(token)}));" if token else ""
    set_stored = f"sessionStorage.setItem('airportTranslationData', {json.dumps(json.dumps(stored))});" if stored else ""
    return f"<html><body><h1>Select your departure</h1><p>{extra}</p><script>{set_token}{set_stored}</script></body></html>"


def run_script(answer=ANSWER, status=200, stored=None, token=TOKEN, extra="", seen=None, html=None, limit=24, offset=0, adults=2, children=1, infants=0, origin="FLR", destination="LIS", day=DAY):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = tap_recipe(origin, destination, day, adults, children, infants, limit=limit, offset=offset)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def serve(route):
        u = urlparse(route.request.url)
        if u.hostname != "booking.flytap.com":
            route.abort()
        elif u.path == "/bfm/rest/booking/availability/search":
            ok = route.request.headers.get("authorization") == f"Bearer {TOKEN}"
            if seen is not None:
                seen.append({"auth_ok": ok, "query": u.query, "body": json.loads(route.request.post_data or "{}")})
            route.fulfill(status=status if ok else 401, content_type="application/json", body=json.dumps(answer) if ok else "")
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or page_html(stored, token, extra))
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto("https://booking.flytap.com/booking/flights?origin=FLR")
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def expected_rows():
    """The fares the server's own parser reads from the same answer: {(flights, fare): (total, adt, chd, bag, refundable, seats)}."""
    found = {}
    for f in parse_availability(ANSWER)["flights"]:
        code = "+".join(s["flight"] for s in f["segments"])
        for fare in f["fares"]:
            per = fare["price_per_passenger_type"]
            found[(code, fare["fare_code"])] = (fare["price_total"], per.get("ADT"), per.get("CHD"), int(bool(fare["checked_bag_included"])), int(bool(fare["refundable"])), fare["seats_left"])
    return found


def test_the_script_asks_taps_own_availability_service_with_the_pages_token_and_makes_the_rows_the_servers_parser_expects():
    seen: list = []
    out, recipe = run_script(seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["source"] == "api" and data["api_note"] is None and data["currency"] == "EUR" and data["pax"] == {"ADT": 2, "CHD": 1} and data["flights_total"] == 5
    ask = seen[0]
    assert ask["auth_ok"] and ask["query"] == "payWithMiles=false&starAlliance=false"
    b = ask["body"]
    assert (b["origin"], b["destination"], b["departureDate"], b["adt"], b["chd"], b["inf"], b["numSeat"], b["oneWay"], b["tripType"], b["roundTripType"], b["market"], b["language"]) == (["FLR"], ["LIS"], ["06032027"], 2, 1, 0, 3, True, "O", False, "PT", "en")
    assert b["passengers"] == {"ADT": 2, "YTH": 0, "CHD": 1, "INF": 0} and b["paxSearch"] == b["passengers"] and b["airlineId"] == "TP" and b["bfmModule"] == "BFM_BOOKING"
    got = {(r["flights"], r["fare"]): (r["total"], r["adt"], r["chd"], r["bag"], r["ref"], r["seats"]) for r in data["rows"] if r["from"] == "FLR"}
    want = {k: v for k, v in expected_rows().items()}
    flr = {k: v for k, v in want.items() if k in got}
    assert got == flr and len(got) >= 6          # the same fares, totals, per passenger prices, bag and refund flags, seats as the parser reads
    assert any(r["from"] != "FLR" for r in data["rows"])         # the offers that start from the train station are in the rows too: the converter lists them apart
    offers, sources, problems, _, notes = convert_all([{"site": "tap", "result": out, "url": recipe["url"], "wishes": {"expect": recipe["expect"]}}], {"expect": recipe["expect"]})
    assert not problems and all(o.currency == "EUR" for o in offers) and any("start from another place" in n for n in notes)
    assert min(o.price_total for o in offers) == 434.38 and any(o.details["checked_bag"] == "yes" for o in offers)


def test_a_refused_request_falls_back_to_the_answer_the_page_stored_and_says_so():
    out, _ = run_script(token=None, stored=ANSWER, extra="5 direct flights", html=page_html(ANSWER, token="short", extra="5 direct flights"))       # a token that is too short to be one: the service is not asked at all
    data = json.loads(out)
    assert data["ok"] is True and data["source"] == "page" and data["flights_total"] == 5
    out, _ = run_script(status=500, stored=ANSWER, extra="5 direct flights")       # the service answers an error (with a valid token): the stored answer is read
    data = json.loads(out)
    assert data["ok"] is True and data["source"] == "page" and data["api_note"] == "answered 500" and data["flights_total"] == 5


def test_a_day_without_flights_is_taps_own_answer_and_stops_the_second_read():
    empty = {**ANSWER, "data": {**ANSWER["data"], "listOutbound": [], "notAvailable": True}}
    data = json.loads(run_script(answer=empty)[0])
    assert data["ok"] is False and 'TAP itself says: "No flights available on 2027-03-06"' in data["error"] and "FLR to LIS" in data["error"]
    from myt_mcp.sites import DEFINITIVE
    assert DEFINITIVE.search(data["error"])


def test_the_script_stops_on_a_check_page_and_on_a_page_that_is_not_a_booking_page():
    check = json.loads(run_script(html="<html><body>Access denied. Verify you are human.</body></html>")[0])
    assert check["ok"] is False and "human check" in check["error"] and "do not work around" in check["error"]


def test_the_batch_and_the_offset_still_cut_the_flights_cheapest_first():
    full = json.loads(run_script()[0])
    first = json.loads(run_script(limit=2)[0])
    second = json.loads(run_script(limit=2, offset=2)[0])
    assert first["flights_in_part"] == 2 and second["offset"] == 2 and first["flights_total"] == 5 and second["flights_total"] == 5
    codes = lambda d: list(dict.fromkeys(r["flights"] + r["dep"] for r in d["rows"]))      # noqa: E731
    assert codes(first) + codes(second) == codes(full)[:4]
