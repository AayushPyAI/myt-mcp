"""Europcar cars (europcar.com): the address, the converter on the shape of Europcar's own offers answer (read live 5 Nov 2026) and the tool."""

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
from myt_mcp.sites.europcar_cars import convert, europcar_cars_recipe, results_url, site_filter, stations

FX = {"factors": {"USD": 0.8885, "GBP": 1.15, "ILS": 0.2876}, "date": "2026-10-26", "age_days": 1, "source": "Bank of Israel representative rates"}


@pytest.fixture(autouse=True)
def no_exchange_feed(monkeypatch):
    """A test never calls the Bank of Israel: the tool gets no rate unless a test gives one."""
    async def none():
        return None
    monkeypatch.setattr("myt_mcp.sites.europcar_cars.eur_factors", none)


EXPECT = {"pickup": "Lisbon Airport", "pickup_station": "LIST01", "dropoff_station": "LIST01", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00", "age": 30, "residency": "IL"}
WISHES = {"expect": EXPECT}


def offer(model="CITROEN C4 AUTOMATIC", acriss="CDAR", category="Compact", seats=5, auto=True, total=108.34, per_day=54.17, excess=3000.0, cur="EUR", customer=("USD", 124.75), min_age=19, mileage=None, confirm="instant",
          packages=None, features=None, fuel="unleaded 95", cancel=None):
    """One element of the answer's `data`, with the fields the live answer has (photos and links left out)."""
    pkgs = packages if packages is not None else [{"code": "BASIC", "packageComposition": [{"code": "LDW"}], "excessInCustomerCurrency": {"amount": round(excess * 1.1514, 2), "currency": customer[0]},
                                                 "excessInDestinationCurrency": {"amount": excess, "currency": cur}, "level": 1}]
    return {"car": {"acriss": acriss, "model": model, "category": category, "modelGuaranteed": False, "doors": "5", "airConditioning": True, "capacity": {"seats": seats, "luggageItems": "2", "luggages": 2},
                    "engine": {"fuel": fuel, "automatic": auto}, "premiumBrandGuaranteed": False, "segments": [{"code": "MEDIUM", "name": "Medium"}], "features": [{"code": c, "name": c.title()} for c in (features or (["AUTOMATIC"] if auto else []))]},
            "rates": [{"brand": "EUROPCAR", "type": "PAY_ON_ARRIVAL", "discount": {"rate": 0, "type": "PUBLIC"}, "priceInDestinationCurrency": {"amount": total, "amountPerDay": per_day, "currency": cur},
                       "priceInCustomerCurrency": {"amount": customer[1], "amountPerDay": round(customer[1] / 3, 2), "currency": customer[0]}, "minimumDriverAgeRequired": min_age,
                       "ancillaries": {"packages": pkgs, "standalones": [], "equipments": [], "surcharges": [], "additionalMileages": []},
                       "policies": {"bookingConfirmation": confirm, "cancellationFees": cancel or [], "fuel": "full-to-full", "mileage": mileage or {"isUnlimited": True, "included": 0, "includedPerDay": 0, "unit": ""}}}]}


def rows_from(offers):
    """What the script makes of the answer, in Python (kept in step with europcar_cars.js by the integration test)."""
    rows = []
    for o in offers:
        car = o["car"]
        for r in o["rates"]:
            pol, mil, dest, cust = r["policies"], r["policies"]["mileage"], r["priceInDestinationCurrency"], r["priceInCustomerCurrency"]
            rows.append({"car": car["model"], "acriss": car["acriss"], "category": car["category"], "segments": [s["code"] for s in car["segments"]], "features": [f["code"] for f in car["features"]],
                         "seats": car["capacity"]["seats"], "bags": car["capacity"]["luggages"], "bag_items": car["capacity"]["luggageItems"], "doors": car["doors"], "ac": car["airConditioning"], "automatic": car["engine"]["automatic"],
                         "fuel_type": car["engine"]["fuel"], "model_guaranteed": car["modelGuaranteed"], "premium_brand": car["premiumBrandGuaranteed"], "total": dest["amount"], "per_day": dest["amountPerDay"], "cur": dest["currency"],
                         "total_customer": cust["amount"], "per_day_customer": cust["amountPerDay"], "cur_customer": cust["currency"], "pay": r["type"], "brand": r["brand"], "discount": r["discount"]["type"],
                         "min_age": r["minimumDriverAgeRequired"],
                         "packages": [{"code": x["code"], "level": x["level"], "excess": x["excessInDestinationCurrency"]["amount"], "excess_cur": x["excessInDestinationCurrency"]["currency"],
                                       "excess_customer": x["excessInCustomerCurrency"]["amount"], "excess_customer_cur": x["excessInCustomerCurrency"]["currency"]} for x in r["ancillaries"]["packages"]],
                         "upgrades": [], "surcharges": 0, "fuel_policy": pol["fuel"], "mileage_unlimited": mil["isUnlimited"], "mileage_included": mil["included"], "mileage_per_day": mil["includedPerDay"],
                         "mileage_unit": mil["unit"] or None, "cancellation_fees": len(pol["cancellationFees"]), "confirmation": pol["bookingConfirmation"]})
    return rows


def _data(offers=None, **kw):
    offers = offers if offers is not None else [offer(), offer("PEUGEOT 2008", "CFMR", "Compact", 5, False, 95.0, 47.5, 2900.0), offer("FIAT 500 ELECTRIC", "MDAE", "Mini", 4, True, 130.0, 65.0, 0.0)]
    base = {"ok": True, "form": {"pickup_station": "LIST01", "dropoff_station": "LIST01", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00"}, "age": 30, "residency": "IL", "days": 2, "young_driver_fee": False,
            "currencies": {"customer": "USD", "destination": "EUR"}, "filter_sent": None, "total": len(offers), "unfiltered_total": len(offers), "complete": True, "cars_read": len(offers), "rows": rows_from(offers)}
    base.update(kw)
    return json.dumps(base)


def test_the_address_carries_every_search_value_and_stations_are_known_by_code():
    url = results_url("LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", 30, "IL")
    assert url.startswith("https://www.europcar.com/en-us/reservation/vehicles?vehicleType=CR&") and all(x in url for x in (
        "pickupLocation=LIST01", "dropoffLocation=LIST01", "pickupYear=2027", "pickupMonth=03", "pickupDay=06", "dropoffDay=08", "pickupHour=10", "pickupMinute=00", "driverAge=30", "countryOfResidence=IL"))
    assert stations() == {"lisbon airport": "LIST01"}


def test_the_recipe_holds_the_expected_search_and_refuses_bad_values():
    out = europcar_cars_recipe("Lisbon Airport", "LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", 30, "IL")
    assert out["expect"] == EXPECT and "__EXPECT__" not in out["script"] and "emit(" in out["script"] and '"residency": "IL"' in out["script"] and '"filter": ""' in out["script"] and out["site_filter"] == ""
    assert '"filter": "feature:contains:AUTOMATIC,seats:gte:5"' in europcar_cars_recipe("Lisbon Airport", "LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", 30, "IL", "feature:contains:AUTOMATIC,seats:gte:5")["script"]
    for bad in ({"pickup_time": "10"}, {"dropoff_date": "2027-03-05"}, {"age": 12}, {"residency": "Israel"}):
        args = {"pickup": "Lisbon Airport", "pickup_code": "LIST01", "dropoff_code": "LIST01", "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00", "age": 30, "residency": "IL", **bad}
        with pytest.raises(ValueError):
            europcar_cars_recipe(**args)


def test_only_the_wishes_europcars_filter_can_narrow_are_sent():
    assert site_filter("automatic", None) == "feature:contains:AUTOMATIC" and site_filter("automatic", 5) == "feature:contains:AUTOMATIC,seats:gte:5" and site_filter(None, 7) == "seats:gte:7"
    assert site_filter("manual", None) == "" and site_filter(None, None) == "" and site_filter(None, 1) == ""            # manual, bags, zero excess and the budget are judged by the server


def test_every_car_becomes_a_comparison_row_in_the_stations_own_euro_price_with_the_policies():
    rows = convert(_data(), WISHES, "Cars")
    by = {o.name: o for o in rows.offers}
    c4 = by["CITROEN C4 AUTOMATIC (Compact)"]
    assert rows.problems == [] and len(rows.offers) == 3 and rows.read == 3
    assert (c4.price_total, c4.currency, c4.quotable, c4.supplier) == (108.34, "EUR", False, "Europcar")
    d = c4.details
    assert d["gearbox"] == "Automatic" and d["seats_bags"] == "5 seats / 2 bags / 5 doors" and d["mileage"] == "Unlimited mileage" and d["fuel"] == "unleaded 95; policy full to full"
    assert d["excess"] == "BASIC with an excess of EUR 3,000.00; no zero-excess option is offered in the list" and d["price_in_driver_currency"] == "USD 124.75" and d["min_driver_age"] == 19
    assert d["cancellation"].startswith("no cancellation fee listed") and d["booking_confirmation"] is None and d["original_price"] is None
    assert "2 days" in c4.price_basis and "pay on arrival" in c4.price_basis and "station's currency" in c4.price_basis
    notes = " ".join(rows.extra_notes)
    assert "public website price" in notes and "driver's currency" in notes and "does not show a deposit" in notes and "converted" not in notes


def test_a_station_in_another_currency_is_converted_by_the_server_and_a_currency_without_a_rate_is_left_alone():
    gbp = [offer(total=100.0, per_day=50.0, excess=1000.0, cur="GBP", customer=("USD", 125.0))]
    rows = convert(_data(gbp), {**WISHES, "fx": FX}, "Cars")
    row = rows.offers[0]
    assert (row.price_total, row.currency) == (115.0, "EUR") and row.details["original_price"] == "GBP 100.00" and "converted from GBP 100.00 at 1 GBP = 1.1500 EUR (Bank of Israel representative rates, 2026-10-26)" in row.price_basis
    assert "EUR 1,150.00 (converted from GBP 1,000.00" in row.details["excess"] and any("Do not convert them yourself" in n for n in rows.extra_notes)
    assert any("5 days old" in n for n in convert(_data(gbp), {**WISHES, "fx": {**FX, "age_days": 5}}, "Cars").extra_notes)
    none = convert(_data(gbp), {**WISHES, "fx": {"factors": {}, "date": "x", "age_days": 0, "source": "s"}}, "Cars")
    assert none.offers[0].currency == "GBP" and none.offers[0].price_total == 100.0 and any("no euro rate was available" in n for n in none.extra_notes)
    euro = convert(_data([offer()]), {**WISHES, "fx": FX}, "Cars").offers[0]
    assert (euro.price_total, euro.currency) == (108.34, "EUR") and "converted" not in euro.price_basis                    # a euro price is never touched


def test_a_euro_budget_is_judged_on_the_stations_euro_price_and_never_on_a_price_without_a_rate():
    judged = lambda cars, wishes: [o.fits for o in convert(_data(cars), {**WISHES, **wishes}, "Cars").offers]
    assert judged([offer()], {"max_total": 110}) == [True] and judged([offer()], {"max_total": 100}) == [False]
    gbp = [offer(total=100.0, cur="GBP")]
    assert judged(gbp, {"fx": FX, "max_total": 120}) == [True] and judged(gbp, {"fx": FX, "max_total": 110}) == [False] and judged(gbp, {"max_total": 500}) == [False]


def test_the_operators_wishes_are_judged_and_zero_excess_is_never_assumed():
    fits = lambda wishes: {o.name.split(" (")[0]: o.fits for o in convert(_data(), {**WISHES, **wishes}, "Cars").offers}
    assert fits({"automatic": True}) == {"CITROEN C4 AUTOMATIC": True, "PEUGEOT 2008": False, "FIAT 500 ELECTRIC": True}
    assert fits({"manual": True}) == {"CITROEN C4 AUTOMATIC": False, "PEUGEOT 2008": True, "FIAT 500 ELECTRIC": False}
    assert fits({"min_seats": 5}) == {"CITROEN C4 AUTOMATIC": True, "PEUGEOT 2008": True, "FIAT 500 ELECTRIC": False}
    assert fits({"zero_excess": True}) == {"CITROEN C4 AUTOMATIC": False, "PEUGEOT 2008": False, "FIAT 500 ELECTRIC": True}       # only a package listed with an excess of 0 meets it
    assert fits({"max_total": 100}) == {"CITROEN C4 AUTOMATIC": False, "PEUGEOT 2008": True, "FIAT 500 ELECTRIC": False}
    notes = " ".join(convert(_data(), {**WISHES, "zero_excess": True, "min_large_bags": 2}, "Cars").extra_notes)
    assert "no zero-excess package" in notes and "2 large bags" in notes
    no_package = convert(_data([offer(packages=[])]), {**WISHES, "zero_excess": True}, "Cars").offers[0]
    assert no_package.fits is False and no_package.details["excess"] == "not shown"          # no package listed: never assumed to be zero excess


def test_mileage_confirmation_and_badges_are_shown_as_the_offer_gives_them():
    row = convert(_data([offer(mileage={"isUnlimited": False, "included": 900, "includedPerDay": 300, "unit": "Km"}, confirm="on-request", features=["AUTOMATIC", "PREMIUM"], min_age=25, cancel=[{"x": 1}])]), WISHES, "Cars").offers[0]
    assert row.details["mileage"] == "900 Km included" and row.details["booking_confirmation"] == "booking confirmation: on request (not instant)" and row.details["badges"] == "PREMIUM"
    assert row.details["min_driver_age"] == 25 and row.details["cancellation"].startswith("1 cancellation fee rule(s) listed")


def test_a_wrong_page_a_failed_script_a_minimum_age_answer_and_an_empty_list_are_named():
    problems = lambda **kw: " ".join(convert(_data(**kw), WISHES, "Cars").problems)
    form = {"pickup_station": "LIST01", "dropoff_station": "LIST01", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00"}
    assert "pick-up station 'FAO01', not 'LIST01'" in problems(form={**form, "pickup_station": "FAO01"})
    assert "pick-up '2027-03-06 11:00'" in problems(form={**form, "pickup_when": "2027-03-06 11:00"})
    assert "driver age 26, not 30" in problems(age=26) and "residency IN, not IL" in problems(residency="IN")
    assert "script reported: no cars" in convert(json.dumps({"ok": False, "error": "no cars are shown"}), WISHES, "Cars").problems[0]
    young = convert(json.dumps({"ok": False, "error": "Europcar's offers service answered 409 MINIMUM_DRIVER_AGE: Driver's age 18 below minimum", "code": "MINIMUM_DRIVER_AGE"}), WISHES, "Cars").problems[0]
    assert "does not rent to a driver of this age" in young and "never say sold out" in young
    assert "could not be read (never say sold out)" in problems(rows=[], total=0)
    assert "not the script's JSON" in convert("not json", WISHES, "Cars").problems[0]
    assert "europcar_cars" in modules() and convert_all([{"site": "europcar_cars", "result": _data(), "url": "u"}], WISHES)[0]


def test_the_notes_say_what_europcar_narrowed_the_young_driver_flag_and_a_filter_with_no_car():
    sent = "feature:contains:AUTOMATIC"
    done = convert(_data([offer()], filter_sent=sent, total=17, unfiltered_total=32), WISHES, "Cars")
    assert any("narrowed the list (feature:contains:AUTOMATIC): 17 of 32 cars" in n for n in done.extra_notes) and done.total == 17
    none = convert(_data([], filter_sent=sent, total=0, unfiltered_total=32), WISHES, "Cars")
    assert none.problems == [] and any("no car matches" in n and "never sold out" in n for n in none.extra_notes)
    assert any("young-driver surcharge is included" in n for n in convert(_data(young_driver_fee=True), WISHES, "Cars").extra_notes)
    cut = convert(_data(complete=False, cars_read=3, total=40), WISHES, "Cars")
    assert any("counted more cars than were read" in n for n in cut.extra_notes) and cut.total == 40


@pytest.mark.anyio
async def test_the_tool_asks_first_learns_unknown_stations_and_returns_the_url_wishes_and_filters():
    settings = Settings()
    base = {"pickup": "Lisbon Airport", "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00"}
    async with Client(create_server(settings, Services(settings))) as c:
        asked = (await c.call_tool("europcar_cars_recipe", base)).structured_content
        unknown = (await c.call_tool("europcar_cars_recipe", {**base, "pickup": "Faro Airport", "operator_answered": True})).structured_content
        ok = (await c.call_tool("europcar_cars_recipe", {**base, "gearbox": "automatic", "min_seats": 5, "zero_excess": True, "max_total": 300})).structured_content
        learned = (await c.call_tool("europcar_cars_recipe", {**base, "pickup": "Faro Airport", "station_code": "FAOA01", "operator_answered": True})).structured_content
    assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 4
    assert unknown["ok"] is False and unknown["needs_station_code"] == ["Faro Airport"] and any("pickupLocation" in s for s in unknown["steps"])
    assert "pickupLocation=LIST01" in ok["url"] and "driverAge=30" in ok["url"] and "countryOfResidence=IL" in ok["url"] and ok["pickup_time"] == "10:00" and "script" in ok
    assert ok["wishes"]["automatic"] is True and ok["wishes"]["zero_excess"] is True and ok["wishes"]["min_seats"] == 5 and ok["wishes"]["max_total"] == 300 and ok["wishes"]["expect"]["pickup"] == "Lisbon Airport"
    assert ok["site_filter"] == "feature:contains:AUTOMATIC,seats:gte:5" and '"filter": "feature:contains:AUTOMATIC,seats:gte:5"' in ok["script"]
    filters = " ".join(ok["filters_used"])
    assert "Automatic gearbox (operator)" in filters and "default 30" in filters and "country of residence IL" in filters and "at least 5 seats" in filters and "sent to Europcar's own filter" in filters
    assert "pickupLocation=FAOA01" in learned["url"] and ok["wishes"]["fx"] is None
    assert any("no euro exchange rate was available" in f for f in ok["filters_used"])


@pytest.mark.anyio
async def test_the_tool_carries_the_rate_in_the_wishes_and_names_it_in_the_filters(monkeypatch):
    async def rate():
        return FX
    monkeypatch.setattr("myt_mcp.sites.europcar_cars.eur_factors", rate)
    settings = Settings()
    base = {"pickup": "Lisbon Airport", "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00", "operator_answered": True}
    async with Client(create_server(settings, Services(settings))) as c:
        out = (await c.call_tool("europcar_cars_recipe", base)).structured_content
    assert out["wishes"]["fx"] == FX and any("converted to EUR by the server" in f and "USD 1 = EUR 0.8885" in f and "2026-10-26" in f for f in out["filters_used"])


def test_the_script_is_valid_javascript(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    script = europcar_cars_recipe("Lisbon Airport", "LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", 30, "IL")["script"]
    path = Path(tmp_path) / "europcar.mjs"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


@pytest.mark.anyio
async def test_a_refused_value_reaches_the_assistant_as_its_own_message_not_as_an_unexpected_error():
    settings = Settings()
    base = {"pickup": "Lisbon Airport", "pickup_date": "2027-03-06", "pickup_time": "10", "dropoff_date": "2027-03-08", "dropoff_time": "10:00", "operator_answered": True}
    async with Client(create_server(settings, Services(settings))) as c:
        bad = await c.call_tool("europcar_cars_recipe", base)
    assert bad.is_error and "times must be HH:MM" in bad.content[0].text and "unexpectedly" not in bad.content[0].text


def test_a_row_whose_large_bags_the_list_cannot_show_is_marked_not_confirmed_and_never_a_pick():
    """28 Oct 2026: Ofran's 'x/y' bags and Europcar's luggage count cannot say which are large, and the Best fit still 'met every wish'."""
    offers = convert(_data(), {**WISHES, "min_large_bags": 2}, "Cars").offers
    assert offers and all(o.unconfirmed == ["large bags"] and o.fits is not True for o in offers)
    assert all(not o.unconfirmed for o in convert(_data(), WISHES, "Cars").offers)


def test_the_converted_excess_cell_passes_the_servers_own_currency_check():
    """28 Oct 2026: check_answer refused the server's own text ('basic protection with an excess of $2,650') and the assistant could not change it."""
    from myt_mcp.composed import ComposedStore, currency_problems
    rows = convert(_data([offer(total=100.0, per_day=50.0, excess=1000.0, cur="GBP")]), {**WISHES, "fx": FX}, "Cars")
    row = rows.offers[0]
    store = ComposedStore()
    store.remember("cars", f"| {row.name} | {row.price_total:.2f} EUR | {row.price_basis} |")
    table = f"| Car | Excess | Price |\n|---|---|---|\n| {row.name} | {row.details['excess']} | {row.price_total:.2f} EUR |"
    assert currency_problems(table, store) == []
