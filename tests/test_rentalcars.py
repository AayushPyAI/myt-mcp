"""Rentalcars.com (broker, by Booking.com): the address, the converter on the shape of the site's own search answer (read live 27 Oct 2026) and the tool."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.sites import convert_all, modules
from myt_mcp.sites.rentalcars_cars import convert, find_place, rentalcars_cars_recipe, results_url

LIS = {"name": "Humberto Delgado Airport", "iata": "LIS", "coordinates": "38.769901275634766,-9.129509925842285", "fts_type": "A"}
EXPECT = {"iata": "LIS", "drop_iata": "LIS", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00", "age": 30, "pickup": "Humberto Delgado Airport"}
WISHES = {"expect": EXPECT}
FX = {"factors": {"ILS": 0.2876, "USD": 0.8885}, "date": "2026-10-26", "age_days": 1, "source": "Bank of Israel representative rates"}


def fee(name, amount, cur="INR", included=False):
    return {"name": name, "alwaysPayable": False, "includedInDriveAwayPrice": included, "price": {"amount": amount, "currency": cur}, "basePrice": {"amount": amount, "currency": cur}, "isPayableLocally": False,
            "taxIncluded": False, "source": "SUPPLIER"}


def match(i=1, car="Peugeot 2008", klass="SFAE", seats="5", doors="4", big=2, small=1, gearbox="AUTOMATIC", total=3259.28, base=3046.47, cur="INR", damage=287296.68, theft=287296.68, deposit=287296.68,
          free=True, depot="4628045", fuel="Electric", extra=True):
    fees = [fee("DAMAGE_EXCESS", damage, cur), fee("DEPOSIT", deposit, cur), fee("FUEL_POLICY", 2128.12, cur), {"name": "MILEAGE", "price": None}, fee("THEFT_EXCESS", theft, cur)]
    if extra:
        fees += [fee("ENVIRONMENTAL_FEE", 212.81, cur, True), fee("TRANSPONDER_FEE", 474.57, cur)]
    fees = [f for f in fees if f.get("price") is not None and f["price"]["amount"] is not None or f["name"] == "MILEAGE"]
    return {"fees": fees, "route": {"dropOffDepotId": depot, "pickUpDepotId": depot}, "recommendedDisplayOrder": i, "insurance": {}, "provisionalExtras": [], "unfilteredRank": i,
            "vehicle": {"id": str(854497560 + i), "airConditioning": True, "makeAndModel": car, "bigSuitcase": big, "smallSuitcase": small, "suitcaseCount": big + small, "carCategories": ["suvs"], "payWhen": "PAY_NOW",
                        "price": {"amount": base, "currency": cur, "deposit": 0, "discount": 0}, "driveAwayPrice": {"amount": total, "currency": cur}, "creditCardRequired": False, "carClass": klass, "freeCancellation": free,
                        "fuel": fuel, "mileageType": "UNLIMITED", "transmission": gearbox, "numberOfDoors": doors, "numberOfSeats": seats}}


def api_answer(matches=None, cur="INR"):
    return {"aggregates": {"fuelPolicyTypes": [{"available": True, "numVehicles": 530, "priceFrom": 1809.89, "value": "RETURN_SAME"}]},
            "depots": {"4628045": {"locationType": "SHUTTLE_BUS", "name": "Humberto Delgado Airport", "cityNameEn": "Lisbon", "countryIsoCode": "PT", "iataCode": "LIS", "id": "4628045", "address": "Lisbon Airport, Rua Doro 5, Lisbon, Portugal, 2680-032",
                                 "supplierId": "1843", "rating": {"average": 7.5, "numRatings": 14317}},
                       "4627999": {"locationType": "IN_TERMINAL", "name": "Humberto Delgado Airport", "iataCode": "LIS", "id": "4627999", "address": "Arrivals hall, Lisbon Airport", "supplierId": "17", "rating": {"average": 8.1, "numRatings": 9000}}},
            "suppliers": {"1843": {"id": "1843", "name": "Klass Wagen", "type": "INTEGRATED"}, "17": {"id": "17", "name": "Alamo", "type": "INTEGRATED"}},
            "searchContext": {"filterCriteria": {}}, "matches": matches if matches is not None else [
                match(1), match(2, "Fiat 500", "MBMR", "4", "3", 0, 2, "MANUAL", 2100.0, 1900.0, damage=0.0, theft=0.0, deposit=0.0, depot="4627999", fuel="Petrol", free=False, extra=False),
                match(3, "VW Golf", "CWMR", "5", "5", 1, 2, "MANUAL", 3500.0, 3300.0, depot="4627999", fuel="Diesel")]}


def _data(matches=None, **kw):
    out = {"ok": True, "form": {"iata": "LIS", "drop_iata": "LIS", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00", "age": 30}, "cars_shown_by_page": "3", "matches_read": 3, "fuel_policies": ["RETURN_SAME"], "rows": []}
    out["rows"] = rows_from(api_answer(matches))
    out.update(kw)
    return json.dumps(out)


def rows_from(j):
    """What the script makes of the site's answer: the same fields, in Python (kept in step with rentalcars_cars.js by the integration test)."""
    rows = []
    for m in j["matches"]:
        v, depot = m["vehicle"], j["depots"][m["route"]["pickUpDepotId"]]
        f = {x["name"]: x for x in m["fees"]}
        amount = lambda name: (f[name]["price"] or {}).get("amount") if name in f and f[name].get("price") else None      # noqa: E731
        other = "; ".join(f"{x['name']} {x['price']['amount']} ({'in the total' if x['includedInDriveAwayPrice'] else 'not in the total'})" for x in m["fees"]
                          if x["name"] in ("TRANSPONDER_FEE", "VALET_FEE", "ADMINISTRATION_FEE", "CREDIT_CARD_CHARGE", "ENVIRONMENTAL_FEE") and x.get("price")) or None
        rows.append({"id": v["id"], "car": v["makeAndModel"], "klass": v["carClass"], "category": v["carCategories"][0], "seats": v["numberOfSeats"], "doors": v["numberOfDoors"], "big": v["bigSuitcase"], "small": v["smallSuitcase"],
                     "gearbox": v["transmission"], "ac": v["airConditioning"], "fuel": v["fuel"], "mileage": v["mileageType"], "pay": v["payWhen"], "free_cancel": v["freeCancellation"], "card_needed": v["creditCardRequired"],
                     "cur": v["driveAwayPrice"]["currency"], "total": v["driveAwayPrice"]["amount"], "base": v["price"]["amount"], "damage_excess": amount("DAMAGE_EXCESS"), "theft_excess": amount("THEFT_EXCESS"),
                     "deposit": amount("DEPOSIT"), "other_fees": other, "supplier": j["suppliers"][depot["supplierId"]]["name"], "rating": depot["rating"]["average"], "ratings": depot["rating"]["numRatings"],
                     "place": depot["name"], "place_type": depot["locationType"], "address": depot["address"]})
    return rows


def test_the_address_carries_every_search_value_and_places_are_found_by_name_site_name_or_code():
    url = results_url(LIS, LIS, "2027-03-06", "10:00", "2027-03-08", "10:00", 30)
    assert url.startswith("https://www.rentalcars.com/search-results?intent=direct&location=&dropLocation=&locationName=Humberto+Delgado+Airport&locationIata=LIS&") and all(x in url for x in (
        "dropLocationIata=LIS", "coordinates=38.769901275634766%2C-9.129509925842285", "driversAge=30", "puDay=6", "puMonth=3", "puYear=2027", "puHour=10", "puMinute=0", "doDay=8", "doMonth=3", "doYear=2027", "doHour=10", "ftsType=A"))
    assert find_place("Lisbon Airport") == LIS and find_place("humberto delgado airport") == LIS and find_place("LIS") == LIS and find_place("Faro Airport") is None


def test_the_recipe_holds_the_expected_search_and_refuses_bad_values():
    out = rentalcars_cars_recipe(LIS, LIS, "2027-03-06", "10:00", "2027-03-08", "10:00", 30)
    assert out["expect"] == EXPECT and "__EXPECT__" not in out["script"] and '"iata": "LIS"' in out["script"] and "emit(" in out["script"]
    base = {"pickup": LIS, "dropoff": LIS, "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00", "age": 30}
    for bad in ({"pickup_time": "10"}, {"dropoff_date": "2027-03-05"}, {"age": 25}, {"age": 70}):
        with pytest.raises(ValueError):
            rentalcars_cars_recipe(**{**base, **bad})


def test_every_car_becomes_a_comparison_row_with_its_supplier_depot_excess_and_cancellation():
    rows = convert(_data(), WISHES, "Cars")
    by = {o.name: o for o in rows.offers}
    peugeot = by["Peugeot 2008 (SFAE) - Klass Wagen"]
    assert rows.problems == [] and len(rows.offers) == 3 and rows.read == 3
    assert (peugeot.price_total, peugeot.currency, peugeot.quotable, peugeot.supplier, peugeot.flexible) == (3259.28, "INR", False, "Klass Wagen", True)
    d = peugeot.details
    assert d["company"] == "Klass Wagen (rating 7.5, 14,317 reviews)" and d["gearbox"] == "Automatic" and d["seats_bags"] == "5 seats / 2 large + 1 small bags / 4 doors" and d["mileage"] == "Unlimited mileage"
    assert d["excess"] == "damage excess 287,296.68 INR, theft excess 287,296.68 INR" and d["deposit"] == "287,296.68 INR" and d["fuel"] == "Electric; policy like for like (return with the fuel level you started with)"
    assert d["pickup_place"].startswith("Humberto Delgado Airport (shuttle bus from the airport): Lisbon Airport, Rua Doro 5") and d["cancellation"].startswith("free cancellation")
    assert d["other_fees"] == "ENVIRONMENTAL_FEE 212.81 (in the total); TRANSPONDER_FEE 474.57 (not in the total)" and "2 days" in peugeot.price_basis and "pay now" in peugeot.price_basis
    fiat = by["Fiat 500 (MBMR) - Alamo"]
    assert fiat.details["excess"] == "zero excess (damage excess 0)" and fiat.flexible is None and fiat.details["cancellation"].startswith("not shown as free") and "in the terminal" in fiat.details["pickup_place"]
    assert "public website price" in " ".join(rows.extra_notes)


def test_the_server_converts_to_euro_with_the_carried_rate_and_leaves_a_currency_without_a_rate_alone():
    rows = convert(_data(), {**WISHES, "fx": {**FX, "factors": {"INR": 0.0107}}}, "Cars")
    peugeot = next(o for o in rows.offers if o.name.startswith("Peugeot"))
    assert (peugeot.currency, peugeot.price_total) == ("EUR", round(3259.28 * 0.0107, 2)) and "converted from INR 3,259.28 at 1 INR = 0.0107 EUR (Bank of Israel representative rates, 2026-10-26)" in peugeot.price_basis
    assert "about 3,074 EUR" in peugeot.details["excess"] and peugeot.details["original_price"] == "INR 3,259.28" and any("converted them to euro" in n or "converted" in n for n in rows.extra_notes)
    assert any("Do not convert them yourself" in n for n in rows.extra_notes)
    none = convert(_data(), {**WISHES, "fx": FX}, "Cars")        # the table has no INR
    assert {o.currency for o in none.offers} == {"INR"} and any("no euro rate was available" in n for n in none.extra_notes)
    ils = convert(json.dumps({**json.loads(_data()), "rows": rows_from(api_answer([match(1, cur="ILS", total=100.0, base=90.0)]))}), {**WISHES, "fx": FX}, "Cars").offers[0]
    assert (ils.currency, ils.price_total) == ("EUR", 28.76)
    stale = convert(_data(), {**WISHES, "fx": {**FX, "factors": {"INR": 0.0107}, "age_days": 6}}, "Cars")
    assert any("6 days old" in n for n in stale.extra_notes)


def test_the_operators_wishes_are_judged_and_a_missing_or_unknown_value_is_never_assumed():
    fits = lambda **w: {o.name.split(" (")[0]: o.fits for o in convert(_data(), {**WISHES, **w}, "Cars").offers}
    assert fits(automatic=True) == {"Peugeot 2008": True, "Fiat 500": False, "VW Golf": False} and fits(manual=True) == {"Peugeot 2008": False, "Fiat 500": True, "VW Golf": True}
    assert fits(min_seats=5) == {"Peugeot 2008": True, "Fiat 500": False, "VW Golf": True} and fits(zero_excess=True) == {"Peugeot 2008": False, "Fiat 500": True, "VW Golf": False}
    assert fits(min_large_bags=2) == {"Peugeot 2008": True, "Fiat 500": False, "VW Golf": False}          # the site says which bags are large: Fiat 0, Golf 1
    assert fits(max_total=3000) == {"Peugeot 2008": False, "Fiat 500": False, "VW Golf": False}           # rupees cannot be judged against a euro budget
    euro = convert(_data(), {**WISHES, "fx": {**FX, "factors": {"INR": 0.0107}}, "max_total": 35}, "Cars")
    assert {o.name.split(" (")[0]: o.fits for o in euro.offers} == {"Peugeot 2008": True, "Fiat 500": True, "VW Golf": False}       # 34.87 and 22.47 EUR fit 35; 37.45 does not
    missing = json.loads(_data())
    missing["rows"][0]["damage_excess"] = None
    assert convert(json.dumps(missing), {**WISHES, "zero_excess": True}, "Cars").offers[0].fits is False                               # no excess fee on the page: not zero excess


def test_a_wrong_page_a_failed_script_an_empty_answer_and_a_partial_list_are_named():
    problems = lambda **kw: " ".join(convert(_data(**kw), WISHES, "Cars").problems)
    assert "pick-up place 'FAO', not 'LIS'" in problems(form={"iata": "FAO", "drop_iata": "LIS", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00", "age": 30})
    assert "driver age '25', not '30'" in problems(form={"iata": "LIS", "drop_iata": "LIS", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00", "age": 25})
    assert "script reported: the page has not made" in convert(json.dumps({"ok": False, "error": "the page has not made its search request"}), WISHES, "Cars").problems[0]
    assert "could not be read (never say sold out)" in problems(rows=[])
    assert "not the script's JSON" in convert("not json", WISHES, "Cars").problems[0]
    partial = convert(_data(cars_shown_by_page="530"), WISHES, "Cars")
    assert any("counts 530 cars; its answer holds the first 3" in n for n in partial.extra_notes) and partial.total == 530
    assert "rentalcars_cars" in modules() and convert_all([{"site": "rentalcars_cars", "result": _data(), "url": "u"}], WISHES)[0]


@pytest.fixture(autouse=True)
def no_exchange_feed(monkeypatch):
    """A test never calls the Bank of Israel: the tool gets no rate unless a test gives one."""
    async def none():
        return None
    monkeypatch.setattr("myt_mcp.sites.rentalcars_cars.eur_factors", none)


@pytest.mark.anyio
async def test_the_tool_asks_first_learns_unknown_places_and_returns_the_url_wishes_and_filters(monkeypatch):
    settings = Settings()
    base = {"pickup": "Lisbon Airport", "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00"}
    async with Client(create_server(settings, Services(settings))) as c:
        asked = (await c.call_tool("rentalcars_cars_recipe", base)).structured_content
        unknown = (await c.call_tool("rentalcars_cars_recipe", {**base, "pickup": "Faro Airport", "operator_answered": True})).structured_content
        ok = (await c.call_tool("rentalcars_cars_recipe", {**base, "gearbox": "automatic", "min_seats": 5, "zero_excess": True, "max_total": 300})).structured_content
        learned = (await c.call_tool("rentalcars_cars_recipe", {**base, "pickup": "Faro Airport", "operator_answered": True,
                                                                "pickup_place": {"name": "Faro Airport", "iata": "FAO", "coordinates": "37.01,-7.96", "fts_type": "A"}})).structured_content
        young = await c.call_tool("rentalcars_cars_recipe", {**base, "operator_answered": True, "driver_years": 25})

        async def rate():
            return FX
        monkeypatch.setattr("myt_mcp.sites.rentalcars_cars.eur_factors", rate)
        with_rate = (await c.call_tool("rentalcars_cars_recipe", {**base, "operator_answered": True})).structured_content
    assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 4
    assert unknown["ok"] is False and unknown["needs_place"] == ["Faro Airport"] and any("locationIata" in s for s in unknown["steps"])
    assert "locationIata=LIS" in ok["url"] and "driversAge=30" in ok["url"] and ok["pickup_time"] == "10:00" and "script" in ok and ok["wishes"]["fx"] is None
    assert ok["wishes"]["automatic"] is True and ok["wishes"]["zero_excess"] is True and ok["wishes"]["min_seats"] == 5 and ok["wishes"]["max_total"] == 300 and ok["wishes"]["expect"]["iata"] == "LIS"
    filters = " ".join(ok["filters_used"])
    assert "Automatic gearbox (operator)" in filters and "default 30" in filters and "at least 5 seats" in filters and "no euro exchange rate was available" in filters
    assert "locationIata=FAO" in learned["url"] and young.is_error and "30-65" in young.content[0].text
    assert with_rate["wishes"]["fx"] == FX and any("converted to EUR by the server" in f and "2026-10-26" in f for f in with_rate["filters_used"])


def test_the_script_is_valid_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = rentalcars_cars_recipe(LIS, LIS, "2027-03-06", "10:00", "2027-03-08", "10:00", 30)["script"]
    path = Path(tmp_path) / "rentalcars.mjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_a_very_low_total_in_euro_is_explained_as_the_pages_own_price_and_a_normal_one_is_not():
    """28 Oct 2026: the chat twice called 16-28 EUR for 2 days 'probably a currency problem'; the operator had checked 18 EUR on the page."""
    low = convert(json.dumps({**json.loads(_data()), "rows": rows_from(api_answer([match(1, cur="EUR", total=16.52, base=15.0, damage=1800.0, theft=1800.0, deposit=2100.0)]))}), WISHES, "Cars")
    assert any("not a currency mistake" in n and "16.52 EUR for 2 days" in n for n in low.extra_notes)
    normal = convert(json.dumps({**json.loads(_data()), "rows": rows_from(api_answer([match(1, cur="EUR", total=96.0, base=90.0, damage=1800.0, theft=1800.0, deposit=2100.0)]))}), WISHES, "Cars")
    assert not any("currency mistake" in n for n in normal.extra_notes)
