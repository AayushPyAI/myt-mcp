"""Ofran, integration: the REAL script runs in a real browser (Playwright's Chromium) on an ofran.co.il page that answers what the real site answered on 5 Nov 2026: GET /api/locations (the place list) and
POST /api/get_full_dynamic_result (the cars, or `errors[]` with HTTP 200). Nothing leaves the machine. The rows the script makes are compared with the rows these tests derive in Python from the same answer,
and its place choice with the server's own LocationIndex (tests/test_ofran.py)."""

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.ofran.locations import LocationIndex, parse_locations
from myt_mcp.sites import convert_all
from myt_mcp.sites.ofran import ofran_recipe
from tests.test_ofran import RAW_LOCATIONS

HOME_HTML = "<html><body><a>התנתקות</a><h1>Ofran</h1></body></html>"
ENGLISH_HTML = "<html><body><a>Logout</a><h1>Ofran</h1></body></html>"
LOGGED_OUT_HTML = "<html><body><a>התחברות</a><h1>Ofran</h1></body></html>"
DENIED_HTML = "<html><body>Ofran - Access Denied</body></html>"


def car(model="Fiat 500", sipp="MBMR", supplier="Autatlantis Azores Islands", price="34.47", offline="48.28", plan="תכנית בסיס", cdw="700.00", adults="2", kids="1", extras=True, station="Airport", one_way=None):
    contract = {"contractname": plan, "basicprice": price, "nettotal": price, "OfflineRate": offline, "currency": "EUR", "IsLiveRate": "true", "CDWExcess": cdw, "TPExcess": cdw, "Deposit": "700.00", "PolicyCurrency": "EUR", "OneWayFee": one_way if one_way is not None else []}
    if extras:
        contract["AdditionalProducts"] = {"Products": {"AdditionalProduct": {"Name": "Ofran Plus II", "RateInReservationPQCurrency": "28.00", "ReservationPQCurrencyCode": "EUR"}}}      # one product comes back as an object
    return {"contracts": [contract], "cargroup": {"suppliername": supplier, "carmodel": model, "sippcode": sipp, "ofranCarGroupName": "Small", "reccnumofadults": adults, "reccnumofkids": kids, "numdoors": "2/4", "reccnumofsuitcases": "1",
                                                  "reccnumofhandbags": "0", "SupplierRating": "8.50", "Filters": {"StationType": {"StationTypeId": "1", "StationTypeName": station}}}}


RESULT = [car("Opel Corsa", "EDAR", "Hertz Portugal", "89.26", "112.78", extras=False), car(), car("Fiat 500", "MBMR", "Autatlantis Azores Islands", "41.00", "55.00", "תכנית ביטול השתתפות עצמית", "0.00")]


def rows_from(result):
    """What the script makes of the site's answer, in Python (kept in step with ofran.js by the test below): one row per contract, cheapest first."""
    rows = []
    for it in result:
        g = it["cargroup"]
        for c in it["contracts"]:
            extras = c.get("AdditionalProducts", {}).get("Products", {}).get("AdditionalProduct")
            extras = [extras] if isinstance(extras, dict) else (extras or [])
            rows.append({"supplier": g["suppliername"], "supplier_score": g["SupplierRating"], "size": g["ofranCarGroupName"], "acriss": g["sippcode"], "car": g["carmodel"], "seats": g["reccnumofadults"], "kids": g["reccnumofkids"],
                         "doors": g["numdoors"], "suitcases": g["reccnumofsuitcases"], "handbags": g["reccnumofhandbags"], "station_type": g["Filters"]["StationType"]["StationTypeName"], "price": c["nettotal"],
                         "price_before": c["OfflineRate"], "currency": c["currency"], "package": c["contractname"], "live_rate": True, "cdw_excess": c["CDWExcess"], "theft_excess": c["TPExcess"], "deposit": c["Deposit"],
                         "excess_currency": c["PolicyCurrency"], "one_way_fee": json.dumps(c["OneWayFee"]) if c["OneWayFee"] else None,
                         "extras": [{"name": e["Name"], "price": e["RateInReservationPQCurrency"], "currency": e["ReservationPQCurrencyCode"]} for e in extras]})
    return sorted(rows, key=lambda r: float(r["price"]))


def run_script(pickup="Porto Airport", result=None, html=HOME_HTML, locations=None, search=None, search_status=200, seen=None, **kw):
    sync_api = pytest.importorskip("playwright.sync_api")
    args = {"pickup": pickup, "pickup_date": "2027-03-08", "pickup_time": "17:00", "dropoff_date": "2027-03-11", "dropoff_time": "16:00", **kw}
    recipe = ofran_recipe(**args)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"
    answer = search if search is not None else {"result": RESULT if result is None else result, "errors": None}

    def serve(route):
        url = urlparse(route.request.url)
        if url.path == "/":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        elif url.path == "/api/locations":
            route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(RAW_LOCATIONS if locations is None else locations))
        elif url.path == "/api/get_full_dynamic_result":
            if seen is not None:
                seen.append({"body": json.loads(route.request.post_data), "uuid": parse_qs(url.query).get("order_uuid", [""])[0], "method": route.request.method})
            route.fulfill(status=search_status, content_type="application/json", body=json.dumps(answer))
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto("https://ofran.co.il/")
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out


def test_the_real_script_sends_ofrans_own_search_and_makes_the_same_rows_the_unit_tests_expect():
    seen: list = []
    data = json.loads(run_script(seen=seen))
    assert data["ok"] is True and data["cars_total"] == 3 and data["logged_in"] is True and data["form"]["pickup_place"] == "Porto Airport (OPO)" and data["form"]["pickup_when"] == "08.03.27 | 17:00" and data["form"]["age"] is None
    assert data["rows"] == json.loads(json.dumps(rows_from(RESULT)))                      # the JavaScript and the Python read the answer the same way
    body = seen[0]["body"]
    assert seen[0]["method"] == "POST" and len(seen[0]["uuid"]) >= 30 and body == {"CountryId": "69", "PickupIataId": "490", "PickupDate": "08.03.2027", "PickupHour": "17:00", "DropoffIataId": "490", "DropoffDate": "11.03.2027",
                                                                                   "DropoffHour": "16:00", "Age": "", "GoTos": {"Countries": []}}
    recipe = ofran_recipe("Porto Airport", "2027-03-08", "17:00", "2027-03-11", "16:00")
    wishes = {"expect": recipe["expect"], "automatic": True, "zero_excess": True, "min_seats": 3, "max_total": 60}
    offers, sources, problems, _, notes = convert_all([{"site": "ofran", "result": json.dumps(data), "url": "https://ofran.co.il/"}], wishes)
    assert problems == [] and len(offers) == 3 and sources[0].read == 3
    by = {(o.name, o.price_total): o for o in offers}
    assert [o.fits for o in offers] == [False, False, False]                              # Fiat 500 is manual; the Corsa is too dear and in the base plan
    manual = convert_all([{"site": "ofran", "result": json.dumps(data), "url": "u"}], {"expect": recipe["expect"], "manual": True, "zero_excess": True})[0]
    assert {(o.price_total, o.fits) for o in manual} == {(34.47, False), (41.0, True), (89.26, False)}      # only the excess-cancelled plan with an excess of 0 meets zero excess
    assert by[("Fiat 500 (MBMR, Small)", 41.0)].details["plan"] == "תכנית ביטול השתתפות עצמית"


def test_the_script_sends_the_drivers_age_and_another_return_place_and_names_other_matching_places():
    seen: list = []
    data = json.loads(run_script("Lisbon", dropoff="Porto Airport", driver_years=25, seen=seen))
    assert data["ok"] is True and seen[0]["body"]["Age"] == "25" and seen[0]["body"]["PickupIataId"] == "488" and seen[0]["body"]["DropoffIataId"] == "490" and data["form"]["age"] == "25"
    assert data["form"]["pickup_place"] == "Lisbon Airport (LIS)" and [p["code"] for p in data["other_places"]] == ["LISDT"]        # the airport first, the city centre named as another match


def test_the_scripts_place_choice_is_the_same_as_the_servers_location_index():
    index = LocationIndex(parse_locations(RAW_LOCATIONS))
    for text in ("Lisbon", "lis", "Porto", "Florence Airport", "  Lisbon   Airport ", "ליסבון"):
        data = json.loads(run_script(text))
        expected = index.match(text)
        assert data["ok"] is True and data["form"]["pickup_place"] == f"{expected[0].name} ({expected[0].code})", text
        assert [p["code"] for p in data["other_places"]] == [x.code for x in expected[1:4]], text


def test_an_unknown_place_an_error_in_a_200_answer_a_block_and_no_cars_are_each_named_not_hidden():
    assert json.loads(run_script("Atlantis"))["needs_place"] is True
    errors = json.loads(run_script(search={"result": [], "errors": ["Age must be between 21 and 85"]}))
    assert errors["ok"] is False and "answer still said 200" in errors["error"] and "Age must be" in errors["error"]
    assert "answered 403" in json.loads(run_script(search_status=403))["error"]
    assert "Access Denied" in json.loads(run_script(html=DENIED_HTML))["error"] and "VPN" in json.loads(run_script(html=DENIED_HTML))["error"]
    none = json.loads(run_script(search={"result": None, "errors": None}))
    assert none["ok"] is True and none["rows"] == [] and none["cars_total"] == 0
    empty = convert_all([{"site": "ofran", "result": json.dumps(none), "url": "u"}], {"expect": ofran_recipe("Porto Airport", "2027-03-08", "17:00", "2027-03-11", "16:00")["expect"]})
    assert empty[2] == [] and any("no cars for this search" in n and "never 'sold out'" in n for n in empty[4])
    out = json.loads(run_script(html=LOGGED_OUT_HTML))
    assert out["logged_in"] is False and out["rows"] and out["diag"]["login_link"] is True and out["diag"]["page"] == "https://ofran.co.il/" and "התחברות" in out["diag"]["text_start"]       # still read, and what the page showed is returned
    assert json.loads(run_script(html=ENGLISH_HTML))["logged_in"] is True and json.loads(run_script(html=ENGLISH_HTML))["diag"] is None        # the English page says "Logout"
    assert json.loads(run_script(result=[{"cargroup": {}}, car(price="")]))["rows"] == []        # a car without a price or contracts is left out


def test_the_script_is_valid_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    path = Path(tmp_path) / "ofran.mjs"
    path.write_text(ofran_recipe("Faro Airport", "2027-03-08", "17:00", "2027-03-11", "16:00")["script"], encoding="utf-8")
    result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
