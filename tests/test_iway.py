"""iWay (iway.io) transfers: the address, the converter on what the real page gave (27 Oct 2026) and the tool."""

import json
from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.sites import convert_all, modules
from myt_mcp.sites.iway_transfers import convert, find_place, iway_transfers_recipe, places

DAY = date(2027, 3, 6)
RECIPE = iway_transfers_recipe("Lisbon Airport", "Praça do Comércio", DAY, "10:00", 2)
EXPECT = RECIPE["expect"]
FX = {"factors": {"USD": 0.8932}, "date": "2026-10-26", "age_days": 1, "source": "Bank of Israel representative rates"}
FORM = {"from_id": EXPECT["from_id"], "to_id": EXPECT["to_id"], "from_name": "Airport Lisbon Portela", "to_name": "Praça do Comércio", "header_currency": "USD", "logged_in": True, "route": ["9", "30m"]}
ROWS = [{"klass": "Standard", "passengers": 3, "bags": 3, "car": "Toyota Corolla and similar", "symbol": "$", "price": 28.41},
        {"klass": "Business", "passengers": 3, "bags": 3, "car": "Mercedes-Benz E-class w213 and similar", "symbol": "$", "price": 37.16},
        {"klass": "Minivan", "passengers": 6, "bags": 4, "car": "Mercedes-Benz Vito and similar", "symbol": "$", "price": 41.53},
        {"klass": "Minivan VIP", "passengers": 6, "bags": 4, "car": "Mercedes-Benz V-class and similar", "symbol": "$", "price": 65.57}]      # the real list of 27 Oct 2026, Lisbon airport to Praça do Comércio


def answer(rows=None, **over):
    base = {"ok": True, "form": dict(FORM), "unparsed": [], "rows": rows if rows is not None else [dict(r) for r in ROWS]}
    base.update(over)
    return json.dumps(base)


def wishes(**extra):
    return {"expect": EXPECT, "fx": FX, **extra}


def test_known_places_put_both_google_place_ids_in_the_address_and_an_unknown_one_gets_steps():
    assert RECIPE["url"] == "https://iway.io/booking?from=ChIJgwHZFkYyGQ0RRm0DWD6lZgo&to=ChIJY0ulMHo0GQ0RROAoa18vUzA" and "steps" not in RECIPE
    assert EXPECT["leg"] == "Lisbon Airport to Praça do Comércio, 06 Mar 2027 10:00" and EXPECT["total"] == 2
    other = iway_transfers_recipe("Lisbon Airport", "Hotel Avenida Palace", DAY, "10:00", 2)
    assert other["url"] == "https://iway.io/booking" and other["expect"]["from_id"] and other["expect"]["to_id"] is None and "NOT press Order now" in " ".join(other["steps"]) or "Do NOT press Order now" in " ".join(other["steps"])
    given = iway_transfers_recipe("Lisbon Airport", "Hotel X", DAY, "10:00", 2, to_place_id="ChIJxxxx")
    assert given["url"].endswith("&to=ChIJxxxx") and "steps" not in given
    assert "__EXPECT__" not in RECIPE["script"] and "Order now" in RECIPE["script"]
    assert find_place("Aeroporto de Lisboa")["id"] == EXPECT["from_id"] and find_place("Terreiro do Paço")["id"] == EXPECT["to_id"] and find_place("Porto airport") is None and len(places()) == 2


@pytest.mark.parametrize("bad", [dict(time="9:30"), dict(time="25:00"), dict(adults=0), dict(adults=17), dict(destination="lisbon airport"), dict(destination=" ")])
def test_a_bad_time_group_or_the_same_place_twice_is_refused(bad):
    args = dict(origin="Lisbon Airport", destination="Praça do Comércio", day=DAY, time="10:00", adults=2)
    args.update(bad)
    with pytest.raises(ValueError):
        iway_transfers_recipe(**args)


def test_each_vehicle_class_becomes_a_comparison_only_row_in_euro_with_the_original_price_and_rate():
    rows = convert(answer(), wishes(), "Transfers")
    assert rows.problems == [] and rows.read == 4
    by = {o.name.split(":")[0]: o for o in rows.offers}
    std, vip = by["Standard"], by["Minivan VIP"]
    assert std.price_total == round(28.41 * 0.8932, 2) and std.currency == "EUR" and std.quotable is False and std.supplier == "iWay" and std.group == EXPECT["leg"]
    assert "converted from USD 28.41 at 1 USD = 0.8932 EUR" in std.price_basis and "per vehicle, one way" in std.price_basis and std.details["original_price"] == "USD 28.41"
    assert vip.price_total == round(65.57 * 0.8932, 2) and vip.details["capacity"] == "up to 6 people / 4 bags"       # the real list's last class: the price is $65.57, not the '6' of its capacity
    assert std.details["route"] == "9 km, about 30m" and std.details["cancellation"].startswith("not shown on the list") and std.details["provider"].startswith("iWay")
    assert any("server converted the prices to euro" in n for n in rows.extra_notes) and any("list price for this route" in n for n in rows.extra_notes) and any("place ids read" in n for n in rows.extra_notes)


def test_the_group_the_bags_and_the_budget_decide_which_classes_fit():
    big = {"expect": {**EXPECT, "total": 5}, "fx": FX, "min_bags": 4, "max_total": 40.0}
    by = {o.name.split(":")[0]: o.fits for o in convert(answer(), big, "Transfers").offers}
    assert by == {"Standard": False, "Business": False, "Minivan": True, "Minivan VIP": False}      # 5 people need a minivan; the VIP one is over 40 EUR
    two = {o.name.split(":")[0]: o.fits for o in convert(answer(), wishes(), "Transfers").offers}
    assert two == {"Standard": True, "Business": True, "Minivan": True, "Minivan VIP": True}
    unknown = {"expect": {**EXPECT, "total": 2}, "fx": {}, "max_total": 40.0}      # no euro rate: a euro budget cannot be judged on a dollar price
    assert all(o.fits is False for o in convert(answer(), unknown, "Transfers").offers)


def test_without_a_euro_rate_the_rows_stay_in_dollars_and_say_so():
    rows = convert(answer(), {"expect": EXPECT, "fx": {}}, "Transfers")
    assert {o.currency for o in rows.offers} == {"USD"} and any("no euro rate was available" in n for n in rows.extra_notes)


def test_euro_rows_are_never_touched():
    eur = [{**r, "symbol": "€"} for r in ROWS]
    rows = convert(answer(eur), wishes(), "Transfers")
    assert rows.offers[0].price_total == 28.41 and "converted" not in rows.offers[0].price_basis and not any("server converted" in n for n in rows.extra_notes)


def test_a_logged_out_page_is_said_to_show_possibly_public_prices():
    assert any("did not show the agency account as logged in" in n for n in convert(answer(form={**FORM, "logged_in": False}), wishes(), "Transfers").extra_notes)


def test_the_place_id_in_the_address_decides_not_the_name_iway_writes_for_it():
    live = answer([{**r, "symbol": "€"} for r in ROWS], form={**FORM, "from_name": "Humberto Delgado Airport", "to_name": "Praca do Comercio", "header_currency": "EUR"})      # the same places, written differently, on the euro page of 27 Oct 2026
    rows = convert(live, wishes(), "Transfers")
    assert rows.problems == [] and len(rows.offers) == 4 and rows.offers[0].price_total == 28.41
    unknown = {"expect": {**EXPECT, "from": "Faro Airport", "from_id": None, "to_id": None}, "fx": FX}      # places iWay's table does not know: only the name can say it is the right place
    assert any("searched from 'Humberto Delgado Airport', not 'Faro Airport'" in p for p in convert(live, unknown, "Transfers").problems)
    assert convert(live, {"expect": {**EXPECT, "from_id": None, "to_id": None}, "fx": FX}, "Transfers").problems == []      # 'Lisbon Airport' and 'Humberto Delgado Airport' are one place (place_aliases.json)
    assert convert(answer(form={**FORM, "from_id": "ChIJother", "from_name": "Faro Airport"}), wishes(), "Transfers").problems[0].startswith("the page searched from 'Faro Airport'")      # another id: the name is checked again


@pytest.mark.parametrize("change,fragment", [
    ({"unparsed": ["Standard | sold out"]}, "does not know"),
    ({"rows": []}, "never that there is no transfer"),
    ({"rows": [{**ROWS[0], "symbol": "VIP", "price": 6}]}, "not one the converter knows"),
])
def test_a_page_with_other_places_or_an_unknown_card_or_price_is_refused_with_the_fix(change, fragment):
    problems = convert(answer(**change), wishes(), "Transfers").problems
    assert any(fragment in p for p in problems), problems


def test_a_script_error_and_a_text_that_is_not_json_come_back_as_a_readable_problem():
    assert "reported: iWay shows a human check" in convert(json.dumps({"ok": False, "error": "iWay shows a human check (captcha)."}), wishes(), "Transfers").problems[0]
    assert "not the script's JSON text" in convert("Standard | $28.41", wishes(), "Transfers").problems[0]


def test_the_converter_is_found_by_the_server_and_works_through_convert_all():
    assert "iway_transfers" in modules()
    offers, sources, problems, _, notes = convert_all([{"site": "iway_transfers", "result": answer(), "url": RECIPE["url"], "wishes": wishes()}], wishes())
    assert problems == [] and len(offers) == 4 and sources[0].read == 4 and sources[0].name.startswith("iWay")


@pytest.mark.anyio
async def test_the_tool_returns_the_address_the_wishes_with_the_euro_rate_and_the_filters(monkeypatch):
    async def rate():
        return FX
    monkeypatch.setattr("myt_mcp.sites.iway_transfers.eur_factors", rate)
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        got = (await c.call_tool("iway_transfers_recipe", {"origin": "Lisbon Airport", "destination": "Praça do Comércio", "day": "2027-03-06", "time": "10:00", "adults": 2, "bags": 3, "max_total": 40})).structured_content
        assert got["url"].startswith("https://iway.io/booking?from=ChIJ") and got["wishes"]["fx"] == FX and got["wishes"]["min_bags"] == 3 and got["wishes"]["max_total"] == 40
        text = " ".join(got["filters_used"])
        assert "iWay's list does not use the date and time" in text and "At least 3 bags (operator)" in text and "Max 40 EUR (operator)" in text and "converted to EUR by the server" in text
        assert "server_read" not in got      # the agency's login is in the operator's Chrome: never read by the server
        bad = await c.call_tool("iway_transfers_recipe", {"origin": "Lisbon Airport", "destination": "Lisbon airport", "day": "2027-03-06", "time": "10:00"})
        assert bad.is_error and "two different places" in bad.content[0].text
        tool = next(t for t in (await c.list_tools()).tools if t.name == "iway_transfers_recipe")
        assert tool.description.startswith("[TRANSFERS (airport transfer") and "ONLY" in tool.description


@pytest.mark.anyio
async def test_the_iway_recipe_says_to_use_the_operators_own_tab_in_front_and_its_filter_lines_name_their_source():
    """28 Oct 2026: a new iWay tab stayed blank (the page does not draw in the background) and the recipe's own line 'One way, price per vehicle (iWay)' was refused by compose_answer."""
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.compose import SOURCE_WORDS
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        out = (await c.call_tool("iway_transfers_recipe", {"origin": "Lisbon Airport", "destination": "Praça do Comércio", "day": "2027-03-06", "time": "10:00", "adults": 2, "children_ages": [], "bags": 2})).structured_content
    assert "OWN iWay tab" in out["tab"] and "NEW tab" not in out["tab"] and "in front" in out["tab"]
    assert "WITHOUT parameters" in out["tab"] and "grey placeholders" in out["tab"] and "Never press Order now" in out["tab"]      # what to do when the address with place ids draws no form
    assert all(any(w in f.lower() for w in SOURCE_WORDS) for f in out["filters_used"]), out["filters_used"]
