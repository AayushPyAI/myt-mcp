"""Booking.com flights (flights.booking.com): the address, the converter on what the real page gave (27 Oct 2026) and the tool."""

import json
from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.sites import convert_all, modules
from myt_mcp.sites.booking_flights import booking_flights_recipe, convert

DAY = date(2027, 3, 6)
RECIPE = booking_flights_recipe("TLV", "LIS", DAY, 2)
EXPECT = RECIPE["expect"]
FORM = {"type": "ONEWAY", "origin": "TLV", "destination": "LIS", "day": "2027-03-06", "adults": 2, "children": 0, "cabin": "ECONOMY", "currency": "EUR", "sort": "BEST", "stops": None}
FILTERS = {"stops": "-1", "airlines_off": 0, "times_on": 0}
SORTS = [{"sort": "Best", "shown_as": "Best", "pages_read": 2, "pages_seen": 9}, {"sort": "Cheapest", "shown_as": "Cheapest", "pages_read": 2, "pages_seen": 9}]


def row(sort="Cheapest", page=1, carriers="SKY express", dep="23:30", arr="22:30", stops="1 stop", duration="25h", dep_date="6 Mar", arr_date="7 Mar", total=313.0, per=157.0, cur="€", flexible=True):
    """A card as the script reads it; the first one is the real cheapest card of 27 Oct 2026 (TLV to LIS, 6 Mar 2027, 2 adults)."""
    return {"sort": sort, "page": page, "legs": [{"dep": dep, "from": "TLV", "dep_date": dep_date, "stops": stops, "duration": duration, "arr": arr, "to": "LIS", "arr_date": arr_date}],
            "carriers": carriers, "cur": cur, "total": total, "per_adult": per, "flexible_upgrade": flexible}


def answer(rows=None, **over):
    base = {"ok": True, "form": dict(FORM), "filters": dict(FILTERS), "no_direct_notice": False, "results_total": 133, "per_page": 15, "sorts": [dict(s) for s in SORTS], "unparsed": [],
            "rows": rows if rows is not None else [row()]}
    base.update(over)
    return json.dumps(base)


def test_the_address_asks_the_cabin_the_euro_the_best_sort_for_the_legs_airports_and_no_stops_filter_unless_direct():
    url = RECIPE["url"]
    assert url == ("https://flights.booking.com/flights/TLV.AIRPORT-LIS.AIRPORT/?type=ONEWAY&adults=2&cabinClass=ECONOMY&from=TLV.AIRPORT&to=LIS.AIRPORT&depart=2027-03-06&sort=BEST&currency=EUR")
    assert EXPECT["leg"] == "TLV to LIS, 06 Mar 2027" and EXPECT["stops"] is None and EXPECT["pages"] == 2
    direct = booking_flights_recipe("TLV", "ATH", DAY, 2, True, "business", 5)
    assert direct["url"].endswith("&sort=BEST&currency=EUR&stops=0") and "cabinClass=BUSINESS" in direct["url"] and direct["expect"]["stops"] == "0" and direct["expect"]["cabin_name"] == "Business"
    for placeholder in ("__EXPECT__", "__PAGES__", "__SORTS__"):
        assert placeholder not in RECIPE["script"]
    assert '"Best", "Cheapest"' in RECIPE["script"] or '["Best", "Cheapest"]' in RECIPE["script"]


@pytest.mark.parametrize("args", [("TL", "LIS"), ("TLV", "TLV"), ("TLV", "LIS1")])
def test_bad_airport_codes_are_refused(args):
    with pytest.raises(ValueError):
        booking_flights_recipe(*args, DAY, 2)


def test_bad_travellers_cabin_or_pages_are_refused():
    for kw in ({"adults": 0}, {"adults": 9}, {"pages": 0}, {"pages": 6}, {"cabin": "luxury"}):
        with pytest.raises(ValueError):
            booking_flights_recipe("TLV", "LIS", DAY, **{"adults": 2, **kw})


def test_a_card_becomes_a_comparison_only_row_with_the_pages_own_total():
    rows = convert(answer(), {"expect": EXPECT}, "Flights")
    assert rows.problems == [] and rows.read == 1 and rows.total == 133 and rows.sorted_by_price is True
    o = rows.offers[0]
    assert o.price_total == 313.0 and o.currency == "EUR" and o.quotable is False and o.connecting is True
    assert o.name == "SKY express 23:30-22:30 (arrives 7 Mar) (25h)" and o.details["stops"] == "1 stop" and o.details["from_tab"] == "Cheapest"
    assert o.details["per_person"] == "157 EUR (as the page says: per adult)" and o.details["checked_bag"] == "not shown on the list" and "flexible" in o.details["fare"]
    assert o.group == EXPECT["leg"] and "2 travellers" in o.price_basis
    assert any("Pages read: Best 2 of 9 page(s), Cheapest 2 of 9 page(s)" in n for n in rows.extra_notes) and any("found 133 flight options" in n for n in rows.extra_notes)


def test_the_same_flight_in_the_best_and_the_cheapest_lists_is_one_row_with_both_labels():
    rows = convert(answer([row("Best", 1), row("Cheapest", 1), row("Cheapest", 2, carriers="Iberia", dep="05:30", arr="16:05", arr_date="6 Mar", duration="12h 35m", total=366.0, per=183.0)]), {"expect": EXPECT}, "Flights")
    assert len(rows.offers) == 2 and rows.offers[0].details["from_tab"] == "Best and Cheapest" and rows.offers[1].details["from_tab"] == "Cheapest"


def test_direct_only_marks_a_connection_as_not_fitting_and_a_direct_flight_as_fitting():
    exp = booking_flights_recipe("TLV", "ATH", DAY, 2, True)["expect"]
    form = {**FORM, "destination": "ATH", "stops": "0"}
    rows = convert(answer([row(), row(carriers="Aegean", dep="06:10", arr="08:00", stops="Direct", duration="1h 50m", dep_date="6 Mar", arr_date="6 Mar", total=212.0, per=106.0, flexible=False)],
                          form=form, filters={**FILTERS, "stops": "0"}), {"expect": exp}, "Flights")
    by = {o.name.split(" ")[0]: o for o in rows.offers}
    assert rows.problems == [] and by["SKY"].fits is False and by["Aegean"].fits is True and by["Aegean"].connecting is False and "arrives" not in by["Aegean"].name
    assert any("direct-only filter was set in the address (stops=0)" in n for n in rows.extra_notes)


def test_a_route_with_no_direct_flight_says_so_and_none_of_its_rows_meets_the_wish():
    exp = booking_flights_recipe("TLV", "LIS", DAY, 2, True)["expect"]
    rows = convert(answer(form={**FORM, "stops": "0"}, filters={**FILTERS, "stops": "-1"}, no_direct_notice=True), {"expect": exp}, "Flights")
    assert rows.problems == [] and rows.offers[0].fits is False
    assert any("no direct flights for this search" in n for n in rows.extra_notes)


def test_a_stops_wording_that_is_not_known_is_never_assumed_direct():
    rows = convert(answer([row(stops="Multi")]), {"expect": {**EXPECT, "direct_only": True}}, "Flights")
    assert rows.offers[0].fits is None and rows.offers[0].connecting is False


@pytest.mark.parametrize("change,fragment", [
    ({"form": {**FORM, "day": "2027-03-07"}}, "day 2027-03-07 instead of 2027-03-06"),
    ({"form": {**FORM, "adults": 3}}, "adults 3 instead of 2"),
    ({"form": {**FORM, "currency": "USD"}}, "currency USD instead of EUR"),
    ({"form": {**FORM, "cabin": "BUSINESS"}}, "cabin BUSINESS instead of ECONOMY"),
    ({"form": {**FORM, "stops": "1"}}, "stops 1 instead of None"),
    ({"filters": {**FILTERS, "stops": "1"}}, "stops filter 1 instead of -1"),
    ({"filters": {**FILTERS, "airlines_off": 2}}, "2 airline box(es) switched off"),
    ({"filters": {**FILTERS, "times_on": 1}}, "1 flight-time box(es) ticked"),
    ({"sorts": [SORTS[0]]}, "both the Best and the Cheapest sorts must be read"),
    ({"sorts": [SORTS[0], {**SORTS[1], "shown_as": "Best"}]}, "page showed 'Best' instead of Cheapest"),
    ({"sorts": [SORTS[0], {**SORTS[1], "pages_read": 0}]}, "no page of the Cheapest sort was read"),
    ({"unparsed": ["Cheapest | something new"]}, "does not know"),
])
def test_a_page_that_searched_something_else_or_has_other_filters_or_changed_is_refused_with_the_fix(change, fragment):
    problems = convert(answer(**change), {"expect": EXPECT}, "Flights").problems
    assert any(fragment in p for p in problems), problems


def test_a_price_in_another_currency_and_a_round_trip_card_are_refused_never_converted():
    other = convert(answer([row(cur="$")]), {"expect": EXPECT}, "Flights")
    assert other.offers == [] and any("not euro" in p for p in other.problems)
    two = row(); two["legs"] = two["legs"] * 2
    assert any("2 legs, not one" in p for p in convert(answer([two]), {"expect": EXPECT}, "Flights").problems)


def test_a_script_error_and_a_text_that_is_not_json_come_back_as_a_readable_problem():
    assert "reported: Booking.com shows a human check" in convert(json.dumps({"ok": False, "error": "Booking.com shows a human check (captcha)."}), {"expect": EXPECT}, "Flights").problems[0]
    assert "not the script's JSON text" in convert("Cheapest | 23:30", {"expect": EXPECT}, "Flights").problems[0]


def test_the_converter_is_found_by_the_server_and_works_through_convert_all():
    assert "booking_flights" in modules()
    offers, sources, problems, by_price, notes = convert_all([{"site": "booking_flights", "result": answer(), "url": RECIPE["url"], "wishes": {"expect": EXPECT}}], {"expect": EXPECT})
    assert problems == [] and len(offers) == 1 and sources[0].read == 1 and sources[0].of == 133 and by_price is True
    assert any("price to quote comes from the airline" in n for n in notes)


@pytest.mark.anyio
async def test_the_tool_asks_direct_only_and_cabin_first_refuses_children_and_returns_the_address_and_wishes():
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("booking_flights_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-03-06"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 2 and "Direct only" in asked["ask_operator"][0] and "Cabin" in asked["ask_operator"][1]
        got = (await c.call_tool("booking_flights_recipe", {"origin": "TLV", "destination": "ATH", "day": "2027-03-06", "direct_only": True, "cabin": "business", "pages": 5})).structured_content
        assert got["url"].endswith("&stops=0") and "cabinClass=BUSINESS" in got["url"] and got["wishes"]["expect"]["pages"] == 5 and "Direct flights only (operator" in got["filters_used"][0] and "Business cabin (operator)" in got["filters_used"]
        none = (await c.call_tool("booking_flights_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-03-06", "operator_answered": True})).structured_content
        assert "default: no preference" in none["filters_used"][0] and "Economy cabin (default)" in none["filters_used"]
        kids = await c.call_tool("booking_flights_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-03-06", "direct_only": False, "cabin": "economy", "children_ages": [8]})
        assert kids.is_error and "adults only" in kids.content[0].text
        bad = await c.call_tool("booking_flights_recipe", {"origin": "TLV", "destination": "TLV", "day": "2027-03-06", "direct_only": False, "cabin": "economy"})
        assert bad.is_error and "two different" in bad.content[0].text


def test_the_flights_a_page_is_only_said_when_the_list_has_more_than_one_page():
    """28 Oct 2026: with one direct flight the note said 'the site lists 1 flights a page' (the page's 'Flight option 1 of 1' is the size of the list, not the page size)."""
    one_page = [dict(s, pages_seen=1) for s in SORTS]
    rows = convert(answer(per_page=1, results_total=1, sorts=one_page), {"expect": EXPECT}, "Flights")
    notes = " ".join(rows.extra_notes)
    assert "Pages read: Best 2 of 1 page(s)" in notes and "flights a page" not in notes
    many = " ".join(convert(answer(per_page=1), {"expect": EXPECT}, "Flights").extra_notes)
    assert "(the site lists 15 flights a page)" in many
