"""Europcar cars (europcar.com): the address, the converter on what the real page gave (27 Oct 2026) and the tool."""

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
from myt_mcp.sites.europcar_cars import convert, europcar_cars_recipe, results_url, stations

FX = {"factors": {"USD": 0.8885, "GBP": 1.15, "ILS": 0.2876}, "date": "2026-10-26", "age_days": 1, "source": "Bank of Israel representative rates"}


@pytest.fixture(autouse=True)
def no_exchange_feed(monkeypatch):
    """A test never calls the Bank of Israel: the tool gets no rate unless a test gives one."""
    async def none():
        return None
    monkeypatch.setattr("myt_mcp.sites.europcar_cars.eur_factors", none)


EXPECT = {"pickup": "Lisbon Airport", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00", "age": 30, "residency": "IL"}
WISHES = {"expect": EXPECT}


def _row(car="CITROEN C4 AUTOMATIC", klass="OR SIMILAR Compact", seats="5", gearbox="A", total=86.5, per_day=43.25, symbol="$", excess=3458.64, **kw):
    row = {"car": car, "klass": klass, "seats": seats, "doors": "5", "bags": "2", "gearbox": gearbox, "ac": "A/C", "min_age": "19", "mileage": "Unlimited mileage", "protection": "Basic protection included",
           "pay": "PAY AT DESK", "symbol": symbol, "total": total, "per_day": per_day, "excess_text": f"Excess: {symbol}{excess:,.2f}" if excess is not None else None, "excess": excess}
    row.update(kw)
    return row


def _data(rows=None, **kw):
    base = {"ok": True, "form": {"pickup_place": "Lisbon Airport", "pickup_when": "2027-03-06 10:00", "dropoff_place": "Lisbon Airport", "dropoff_when": "2027-03-08 10:00"}, "age": 30, "residency": "IL",
            "rows": rows if rows is not None else [_row(), _row("PEUGEOT 2008", gearbox="M", total=79.78, per_day=39.89, excess=2900.0), _row("FIAT 500 ELECTRIC", "OR SIMILAR Mini", "4", "A", 120.0, 60.0, excess=0.0)]}
    base.update(kw)
    return json.dumps(base)


def test_the_address_carries_every_search_value_and_stations_are_known_by_code():
    url = results_url("LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", 30, "IL")
    assert url.startswith("https://www.europcar.com/en-us/reservation/vehicles?vehicleType=CR&") and all(x in url for x in (
        "pickupLocation=LIST01", "dropoffLocation=LIST01", "pickupYear=2027", "pickupMonth=03", "pickupDay=06", "dropoffDay=08", "pickupHour=10", "pickupMinute=00", "driverAge=30", "countryOfResidence=IL"))
    assert stations() == {"lisbon airport": "LIST01"}


def test_the_recipe_holds_the_expected_search_and_refuses_bad_values():
    out = europcar_cars_recipe("Lisbon Airport", "LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", 30, "IL")
    assert out["expect"] == EXPECT and "__EXPECT__" not in out["script"] and "emit(" in out["script"] and '"residency": "IL"' in out["script"]
    for bad in ({"pickup_time": "10"}, {"dropoff_date": "2027-03-05"}, {"age": 12}, {"residency": "Israel"}):
        args = {"pickup": "Lisbon Airport", "pickup_code": "LIST01", "dropoff_code": "LIST01", "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00", "age": 30, "residency": "IL", **bad}
        with pytest.raises(ValueError):
            europcar_cars_recipe(**args)


def test_every_car_becomes_a_comparison_row_in_the_currency_the_page_showed():
    rows = convert(_data(), WISHES, "Cars")
    by = {o.name: o for o in rows.offers}
    c4 = by["CITROEN C4 AUTOMATIC (OR SIMILAR Compact)"]
    assert rows.problems == [] and len(rows.offers) == 3 and rows.read == 3
    assert (c4.price_total, c4.currency, c4.quotable, c4.supplier) == (86.5, "USD", False, "Europcar")
    assert c4.details["gearbox"] == "Automatic" and c4.details["seats_bags"] == "5 seats / 2 bags / 5 doors" and c4.details["mileage"] == "Unlimited mileage"
    assert "excess of $3,458.64" in c4.details["excess"] and "2 days" in c4.price_basis and "pay at desk" in c4.price_basis
    notes = " ".join(rows.extra_notes)
    assert "public website price" in notes and "priced this search in USD" in notes and "no euro rate was available" in notes and "Do not convert them yourself" in notes and "does not show fuel policy, deposit or cancellation" in notes


def test_the_server_converts_dollars_to_euro_with_the_rate_it_carried_and_every_row_says_so():
    rows = convert(_data(), {**WISHES, "fx": FX}, "Cars")
    c4 = next(o for o in rows.offers if o.name.startswith("CITROEN"))
    assert (c4.price_total, c4.currency) == (round(86.5 * 0.8885, 2), "EUR") and c4.details["original_price"] == "USD 86.50"
    assert "converted from USD 86.50 at 1 USD = 0.8885 EUR (Bank of Israel representative rates, 2026-10-26)" in c4.price_basis and "excess of $3,458.64" in c4.details["excess"]
    notes = " ".join(rows.extra_notes)
    assert "converted the prices to euro" in notes and "Do not convert them yourself" in notes and "no euro rate" not in notes and "days old" not in notes
    assert all(o.currency == "EUR" for o in rows.offers)
    stale = convert(_data(), {**WISHES, "fx": {**FX, "age_days": 5}}, "Cars")
    assert any("5 days old" in n for n in stale.extra_notes)
    euro = convert(_data([_row(symbol="€")]), {**WISHES, "fx": FX}, "Cars").offers[0]
    assert (euro.price_total, euro.currency, euro.details["original_price"]) == (86.5, "EUR", None) and "converted" not in euro.price_basis        # a euro price is never touched
    inr = convert(_data([_row(symbol="₹", total=8212.8, per_day=4106.4)]), {**WISHES, "fx": FX}, "Cars")
    assert inr.offers[0].currency == "INR" and inr.offers[0].price_total == 8212.8 and any("no euro rate was available" in n for n in inr.extra_notes)       # no rate for INR: left alone


def test_a_euro_budget_is_judged_on_the_converted_price_and_never_on_a_price_without_a_rate():
    judged = lambda wishes: [o.fits for o in convert(_data([_row()]), {**WISHES, **wishes}, "Cars").offers]
    assert judged({"fx": FX, "max_total": 80}) == [True] and judged({"fx": FX, "max_total": 70}) == [False]       # 86.50 USD = 76.85 EUR
    assert judged({"max_total": 80}) == [False]                                                                    # no rate: not judged as met


def test_the_operators_wishes_are_judged_and_zero_excess_is_never_assumed():
    fits = lambda wishes: {o.name.split(" (")[0]: o.fits for o in convert(_data(), {**WISHES, **wishes}, "Cars").offers}
    assert fits({"automatic": True}) == {"CITROEN C4 AUTOMATIC": True, "PEUGEOT 2008": False, "FIAT 500 ELECTRIC": True}
    assert fits({"manual": True}) == {"CITROEN C4 AUTOMATIC": False, "PEUGEOT 2008": True, "FIAT 500 ELECTRIC": False}
    assert fits({"min_seats": 5}) == {"CITROEN C4 AUTOMATIC": True, "PEUGEOT 2008": True, "FIAT 500 ELECTRIC": False}
    assert fits({"zero_excess": True}) == {"CITROEN C4 AUTOMATIC": False, "PEUGEOT 2008": False, "FIAT 500 ELECTRIC": True}       # only a listed excess of 0 meets it
    assert fits({"max_total": 100}) == {"CITROEN C4 AUTOMATIC": False, "PEUGEOT 2008": False, "FIAT 500 ELECTRIC": False}         # dollars cannot be judged against a euro budget
    euro = _data([_row(total=86.5, symbol="€")])
    assert [o.fits for o in convert(euro, {**WISHES, "max_total": 100}, "Cars").offers] == [True] and [o.fits for o in convert(euro, {**WISHES, "max_total": 80}, "Cars").offers] == [False]
    notes = " ".join(convert(_data(), {**WISHES, "zero_excess": True, "min_large_bags": 2}, "Cars").extra_notes)
    assert "no Europcar row meets it" in notes and "2 large bags" in notes


def test_a_car_without_readable_details_has_no_excess_and_is_not_zero_excess():
    row = convert(_data([_row(excess=None)]), {**WISHES, "zero_excess": True}, "Cars").offers[0]
    assert row.details["excess"].startswith("not shown") and row.fits is False


def test_a_wrong_page_a_failed_script_an_empty_list_and_an_unknown_symbol_are_refused():
    problems = lambda **kw: " ".join(convert(_data(**kw), WISHES, "Cars").problems)
    assert "searched 'Faro Airport'" in problems(form={"pickup_place": "Faro Airport", "pickup_when": "2027-03-06 10:00", "dropoff_when": "2027-03-08 10:00"})
    assert "pick-up '2027-03-06 11:00'" in problems(form={"pickup_place": "Lisbon Airport", "pickup_when": "2027-03-06 11:00", "dropoff_when": "2027-03-08 10:00"})
    assert "driver age 26, not 30" in problems(age=26) and "residency IN, not IL" in problems(residency="IN")
    assert "script reported: no cars" in convert(json.dumps({"ok": False, "error": "no cars are shown"}), WISHES, "Cars").problems[0]
    assert "could not be read (never say sold out)" in problems(rows=[])
    assert "not the script's JSON" in convert("not json", WISHES, "Cars").problems[0]
    assert "symbol '¥'" in " ".join(convert(_data([_row(symbol="¥")]), WISHES, "Cars").problems)
    assert "europcar_cars" in modules() and convert_all([{"site": "europcar_cars", "result": _data(), "url": "u"}], WISHES)[0]


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
    filters = " ".join(ok["filters_used"])
    assert "Automatic gearbox (operator)" in filters and "default 30" in filters and "country of residence IL" in filters and "at least 5 seats" in filters
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
