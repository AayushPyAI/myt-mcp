"""Booking.com flights (comparison only): the recipe's address, the converter that turns the flights service's offers into comparison rows, and the tool. The offers have the structure Booking.com's own
flights service returned live on 5 Nov 2026 (GET /api/flights/: priceBreakdown, travellerPrices, includedProducts, extraProducts, segments with legs, aggregation)."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.booking_flights import booking_flights_recipe

DAY = date(2026, 12, 10)
RECIPE = booking_flights_recipe("LIS", "OPO", DAY, 2, False, "economy", 2)
EXPECT = RECIPE["expect"]


def money(v, cur="EUR"):
    return {"currencyCode": cur, "units": int(v), "nanos": int(round((v - int(v)) * 1e9))}


def offer(flight="TP1926", dep="2026-12-10T12:30:00", arr="2026-12-10T13:30:00", mins=60, total=102.0, list_total=None, carrier="TAP Portugal", code="TP", n=2, hand=True, checked=False, flex=True, via=None, cabin="ECONOMY", cur="EUR", extras=None, tech=0):
    flights = [flight] + ([f"{code}999"] if via else [])
    legs = [{"departureTime": dep, "arrivalTime": arr, "departureAirport": {"code": "LIS"}, "arrivalAirport": {"code": via or "OPO"}, "cabinClass": cabin, "flightStops": [{}] * tech if i == 0 else [],
             "flightInfo": {"flightNumber": int(f[2:]), "carrierInfo": {"operatingCarrier": code, "marketingCarrier": code}}, "carriersData": [{"name": carrier, "code": code}]} for i, f in enumerate(flights)]
    included = [{"luggageType": "PERSONAL_ITEM", "maxPiece": 2, "piecePerPax": 1}]
    if hand:
        included.append({"luggageType": "HAND", "maxPiece": 2, "maxWeightPerPiece": 10, "massUnit": "KG", "piecePerPax": 1})
    if checked:
        included.append({"luggageType": "CHECKED_IN", "ruleType": "PIECE_BASED", "maxPiece": 2, "maxWeightPerPiece": 23, "massUnit": "KG", "piecePerPax": 1})
    return {"token": f"tok-{flight}-{total}", "segments": [{"departureAirport": {"code": "LIS", "name": "Humberto Delgado Airport"}, "arrivalAirport": {"code": "OPO", "name": "Francisco Sa Carneiro Airport"}, "departureTime": dep, "arrivalTime": arr, "totalTime": mins * 60, "legs": legs}],
            "priceBreakdown": {"total": money(total, cur), "totalWithoutDiscount": money(list_total or total, cur), "baseFare": money(32.44), "tax": money(79.08), "fee": money(0)},
            "travellerPrices": [{"travellerType": "ADULT" if i < n - (1 if n == 3 else 0) else "CHILD", "travellerPriceBreakdown": {"total": money(round(total / n, 2))}} for i in range(n)],
            "includedProducts": {"areAllSegmentsIdentical": True, "segments": [included]}, "extraProducts": [{"type": t} for t in (extras if extras is not None else (["checkedInBaggage", "flexibleTicket"] if flex else []))]}


def row(sort="Best", page=1, **kw):
    """The row the script makes of one offer (kept in step with booking_flights.js by the integration test)."""
    o = offer(**kw)
    seg = o["segments"][0]
    ls = seg["legs"]
    ip = o["includedProducts"]["segments"][0]
    bag = lambda t: next(({"per_pax": b.get("piecePerPax"), "kg": b.get("maxWeightPerPiece")} for b in ip if b["luggageType"] == t), None)      # noqa: E731
    return {"sort": sort, "page": page, "carriers": ", ".join(dict.fromkeys(c["name"] for l in ls for c in l["carriersData"])), "cur": o["priceBreakdown"]["total"]["currencyCode"],
            "legs": [{"dep": seg["departureTime"].replace("T", " ")[:16], "from": "LIS", "from_name": seg["departureAirport"]["name"], "arr": seg["arrivalTime"].replace("T", " ")[:16], "to": "OPO", "to_name": seg["arrivalAirport"]["name"], "mins": seg["totalTime"] // 60,
                      "stops": len(ls) - 1, "tech_stops": sum(len(l["flightStops"]) for l in ls), "flights": [f"{l['flightInfo']['carrierInfo']['marketingCarrier']}{l['flightInfo']['flightNumber']}" for l in ls],
                      "ops": list(dict.fromkeys(l["flightInfo"]["carrierInfo"]["operatingCarrier"] for l in ls)), "cabins": list(dict.fromkeys(l["cabinClass"] for l in ls)), "via": [l["arrivalAirport"]["code"] for l in ls[:-1]]}],
            "total": kw.get("total", 102.0), "list_total": kw.get("list_total") or kw.get("total", 102.0), "base": 32.44, "tax": 79.08, "fee": 0.0,
            "trav": [{"type": t["travellerType"], "total": t["travellerPriceBreakdown"]["total"]["units"] + t["travellerPriceBreakdown"]["total"]["nanos"] / 1e9} for t in o["travellerPrices"]], "personal_item": True, "hand": bag("HAND"), "checked": bag("CHECKED_IN"),
            "extras": [e["type"] for e in o["extraProducts"]], "flexible_upgrade": any(e["type"] == "flexibleTicket" for e in o["extraProducts"])}


def answer(rows=None, **over):
    base = {"ok": True, "searched": {"type": "ONEWAY", "origin": "LIS", "destination": "OPO", "day": "2026-12-10", "adults": 2, "children": 0, "cabin": "ECONOMY", "currency": "EUR", "stops": None, "airlines": [], "dep_hours": None, "max_hours": None, "checked_bag": False}, "cabin_back": "ECONOMY",
            "results_total": 155, "unfiltered_total": 155, "sorts": [{"sort": "Best", "pages_read": 2, "pages_seen": 11}, {"sort": "Cheapest", "pages_read": 2, "pages_seen": 11}], "no_direct_notice": False, "failed": None,
            "rows": rows if rows is not None else [row("Best", 1), row("Cheapest", 1, flight="TP1928", total=122.12, list_total=130.0, checked=True, n=2)]}
    base.update(over)
    return json.dumps(base)


def convert_one(data, recipe=RECIPE):
    return convert_all([{"site": "booking_flights", "result": data, "url": recipe["url"], "wishes": {"expect": recipe["expect"]}}], {"expect": recipe["expect"]})


def test_the_address_asks_the_cabin_the_euro_the_best_sort_for_the_legs_airports_and_no_stops_filter_unless_direct():
    q = parse_qs(urlparse(RECIPE["url"]).query)
    assert RECIPE["url"].startswith("https://flights.booking.com/flights/LIS.AIRPORT-OPO.AIRPORT/?") and q == {"type": ["ONEWAY"], "adults": ["2"], "cabinClass": ["ECONOMY"], "from": ["LIS.AIRPORT"], "to": ["OPO.AIRPORT"], "depart": ["2026-12-10"], "sort": ["BEST"], "currency": ["EUR"]}
    direct = booking_flights_recipe("lis", "opo", DAY, 2, True, "business", 3, [8, 10])
    dq = parse_qs(urlparse(direct["url"]).query)
    assert dq["stops"] == ["0"] and dq["cabinClass"] == ["BUSINESS"] and dq["children"] == ["8,10"] and direct["expect"]["children"] == 2 and direct["expect"]["ages"] == [8, 10] and direct["expect"]["stops"] == "0"
    assert '"stops": 0' in direct["script"] and '"children_ages": [8, 10]' in direct["script"] and "__REQUEST__" not in direct["script"] and "window.__mytParts" in direct["script"]


@pytest.mark.parametrize("args", [("TL", "LIS"), ("TLV", "TLV"), ("TLV", "LIS1")])
def test_bad_airport_codes_are_refused(args):
    with pytest.raises(ValueError, match="AIRPORT codes"):
        booking_flights_recipe(*args, DAY)


def test_bad_travellers_cabin_or_pages_are_refused():
    for kw in ({"cabin": "luxury"}, {"adults": 0}, {"adults": 9}, {"pages": 0}, {"pages": 6}, {"adults": 7, "children_ages": [3, 4]}, {"children_ages": [18]}):
        with pytest.raises(ValueError):
            booking_flights_recipe("LIS", "OPO", DAY, **kw)


def test_an_offer_becomes_a_comparison_only_row_with_the_exact_total_the_breakdown_the_bags_and_the_flight_numbers():
    offers, sources, problems, _, notes = convert_one(answer())
    assert not problems and len(offers) == 2 and (sources[0].read, sources[0].of) == (2, 155) and not any(o.quotable for o in offers)
    first, second = offers
    assert first.name == "TAP Portugal TP1926 12:30-13:30 (1h 00)" and first.price_total == 102.0 and first.currency == "EUR" and first.supplier == "TAP Portugal"
    assert "whole group (2 travellers)" in first.price_basis and "the airline's own page has the price to quote" in first.price_basis and "discount" not in first.price_basis
    d = first.details
    assert d["stops"] == "Direct" and d["cabin_bag"] == "personal item, hand bag up to 10 kg, 1 per traveller" and d["checked_bag"] == "no; a checked bag is offered as a paid extra (price not in the list)"
    assert d["fare"].startswith("flexible ticket offered as a paid extra") and d["price_parts"] == "base fare 32.44 EUR, taxes 79.08 EUR" and d["per_person"] == "ADULT 51 EUR / ADULT 51 EUR" and d["operated_by"] == "TP" and d["from_tab"] == "Best"
    assert second.price_total == 122.12 and "list price 130 EUR, Booking.com's discount 7.88 EUR" in second.price_basis and second.details["checked_bag"] == "yes: 1 bag(s) per traveller up to 23 kg"
    assert any("Booking.com only compares" in n for n in notes) and any("Booking.com says it found 155 flight options" in n for n in notes) and any("Best 2 of 11 page(s)" in n for n in notes)


def test_the_same_flight_in_the_best_and_the_cheapest_lists_is_one_row_with_both_labels():
    rows = [row("Best", 1), row("Cheapest", 1), row("Cheapest", 1, flight="TP1928", total=122.12)]
    offers = convert_one(answer(rows))[0]
    assert len(offers) == 2 and offers[0].details["from_tab"] == "Best and Cheapest" and offers[1].details["from_tab"] == "Cheapest"


def test_a_connection_a_next_day_arrival_and_technical_stops_are_told_from_the_flights_own_data():
    r = row("Best", 1, flight="KL1234", dep="2026-12-10T23:30:00", arr="2026-12-11T09:40:00", mins=610, total=140.0, carrier="KLM", code="KL", via="AMS", tech=1)
    o = convert_one(answer([r]))[0][0]
    assert o.connecting is True and "arrives 11/12" in o.name and o.details["stops"] == "1 stop(s) via AMS, 1 technical stop(s)" and o.name.startswith("KLM KL1234 + KL999 23:30-09:40")


def test_direct_only_marks_a_connection_as_not_fitting_and_a_direct_flight_as_fitting():
    direct = booking_flights_recipe("LIS", "OPO", DAY, 2, True, "economy", 2)
    rows = [row("Best", 1), row("Best", 1, flight="KL1234", total=140.0, carrier="KLM", code="KL", via="AMS")]
    offers = convert_one(answer(rows, searched={**json.loads(answer())["searched"], "stops": "0"}), direct)[0]
    assert [o.fits for o in offers] == [True, False]
    assert [o.fits for o in convert_one(answer(rows))[0]] == [None, None] or all(o.fits in (True, None) for o in convert_one(answer(rows))[0])       # no wish: nothing is judged


def test_a_route_with_no_direct_flight_says_so_and_none_of_its_rows_meets_the_wish():
    direct = booking_flights_recipe("LIS", "OPO", DAY, 2, True, "economy", 2)
    rows = [row("Best", 1, flight="KL1234", total=140.0, carrier="KLM", code="KL", via="AMS")]
    offers, _, problems, _, notes = convert_one(answer(rows, searched={**json.loads(answer())["searched"], "stops": "0"}, no_direct_notice=True, results_total=0), direct)
    assert not problems and offers[0].fits is False and any("no direct flight for this search" in n for n in notes)


def test_a_child_is_sent_and_priced_and_the_wrong_cabin_does_not_fit():
    rec = booking_flights_recipe("LIS", "OPO", DAY, 2, False, "business", 2, [8])
    search = {**json.loads(answer())["searched"], "children": 1, "cabin": "BUSINESS"}
    rows = [row("Best", 1, n=3, cabin="BUSINESS", total=151.16), row("Best", 1, n=3, flight="TP1930", cabin="ECONOMY", total=120.0)]
    offers, _, problems, _, notes = convert_one(answer(rows, searched=search, cabin_back="BUSINESS"), rec)
    assert not problems and [o.fits for o in offers] == [True, False] and offers[0].details["per_person"] == "ADULT 50.39 EUR / ADULT 50.39 EUR / CHILD 50.39 EUR" and any("1 child(ren) (ages 8)" in n for n in notes)


@pytest.mark.parametrize("change,fragment", [
    ({"searched": {**json.loads(answer())["searched"], "day": "2026-12-11"}}, "searched day 2026-12-11 instead of 2026-12-10"),
    ({"searched": {**json.loads(answer())["searched"], "adults": 3}}, "searched adults 3 instead of 2"),
    ({"searched": {**json.loads(answer())["searched"], "stops": "0"}}, "searched stops 0 instead of None"),
    ({"cabin_back": "BUSINESS"}, "answered for the cabin BUSINESS, not ECONOMY"),
    ({"sorts": [{"sort": "Best", "pages_read": 1, "pages_seen": 2}]}, "both the Best and the Cheapest sorts must be read"),
    ({"sorts": [{"sort": "Best", "pages_read": 0, "pages_seen": 1}, {"sort": "Cheapest", "pages_read": 1, "pages_seen": 1}], "failed": ["Best page 1: answered 500"]}, "no page of the Best sort was read (Best page 1: answered 500)"),
])
def test_an_answer_for_something_else_or_with_a_sort_missing_is_refused_with_the_fix(change, fragment):
    problems = convert_one(answer(**change))[2]
    assert any(fragment in p for p in problems), problems


def test_a_price_in_another_currency_a_wrong_traveller_count_and_a_round_trip_card_are_refused_never_converted():
    assert any("not euro" in p for p in convert_one(answer([row("Best", 1, cur="ILS", total=400.0)]))[2])
    wrong = row("Best", 1)
    wrong["trav"] = wrong["trav"][:1]
    assert any("for 1 traveller(s), not 2" in p for p in convert_one(answer([wrong]))[2])
    two = row("Best", 1)
    two["legs"] = two["legs"] * 2
    offers, _, problems, _, _ = convert_one(answer([two]))
    assert not offers and any("2 legs, not one" in p for p in problems)


def test_a_script_error_and_a_text_that_is_not_json_come_back_as_a_readable_problem():
    assert any("script reported" in p and "check" in p for p in convert_one(json.dumps({"ok": False, "error": "human check"}))[2])
    assert any("not the script's JSON text" in p for p in convert_one("<html>")[2])


def test_the_converter_is_found_by_the_server_and_works_through_convert_all():
    from myt_mcp.sites import modules
    assert "booking_flights" in modules()
    offers, sources, problems, _, _ = convert_one(answer())
    assert len(offers) == 2 and not problems and sources[0].name.startswith("Booking.com flights")


@pytest.mark.anyio
async def test_the_tool_asks_direct_only_and_cabin_first_takes_children_and_returns_the_address_and_wishes():
    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("booking_flights_recipe", {"origin": "LIS", "destination": "OPO", "day": "2026-12-10"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 2 and "url" not in asked
        r = (await c.call_tool("booking_flights_recipe", {"origin": "LIS", "destination": "OPO", "day": "2026-12-10", "adults": 2, "children_ages": [8], "direct_only": True, "cabin": "business"})).structured_content
        q = parse_qs(urlparse(r["url"]).query)
        assert q["children"] == ["8"] and q["stops"] == ["0"] and q["cabinClass"] == ["BUSINESS"] and r["wishes"]["expect"]["children"] == 1 and any("Direct flights only" in f for f in r["filters_used"])


def test_the_flights_a_page_is_only_said_when_the_list_has_more_than_one_page():
    one = answer(sorts=[{"sort": "Best", "pages_read": 1, "pages_seen": 1}, {"sort": "Cheapest", "pages_read": 1, "pages_seen": 1}], results_total=2)
    notes = convert_one(one)[4]
    assert any(n == "Pages read: Best 1 of 1 page(s), Cheapest 1 of 1 page(s)." for n in notes)


def test_the_airline_departure_hours_duration_and_bag_wishes_go_in_the_address_and_are_judged_by_the_server():
    r = booking_flights_recipe("LIS", "OPO", DAY, 2, False, "economy", 2, None, ["tp", "FR"], "6-11", 2.5, True)
    q = parse_qs(urlparse(r["url"]).query)
    assert q["airlines"] == ["FR,TP"] and q["depTimeInt"] == ["06-11"] and q["duration"] == ["3"] and q["includedBaggage"] == ["CHECKIN"]      # whole hours for the site's filter (rounded up), the exact 2.5 is judged here
    assert r["expect"]["airlines"] == ["FR", "TP"] and r["expect"]["dep_hours"] == "06-11" and r["expect"]["max_hours"] == 3 and r["expect"]["max_hours_wish"] == 2.5 and r["expect"]["checked_bag"] is True
    assert '"airlines": ["FR", "TP"]' in r["script"] and '"dep_hours": "06-11"' in r["script"] and '"checked_bag": true' in r["script"]
    search = {**json.loads(answer())["searched"], "airlines": ["FR", "TP"], "dep_hours": "06-11", "max_hours": 3, "checked_bag": True}
    rows = [row("Best", 1, flight="TP1926", dep="2026-12-10T08:00:00", arr="2026-12-10T09:00:00", mins=60, total=150.0, checked=True),
            row("Best", 1, flight="TP1928", dep="2026-12-10T14:00:00", arr="2026-12-10T15:00:00", mins=60, total=140.0, checked=True),       # outside the hours
            row("Best", 1, flight="TP1930", dep="2026-12-10T09:00:00", arr="2026-12-10T10:00:00", mins=60, total=130.0, checked=False),      # no checked bag
            row("Best", 1, flight="KL1234", dep="2026-12-10T07:00:00", arr="2026-12-10T08:00:00", mins=60, total=120.0, carrier="KLM", code="KL"),  # another airline
            row("Best", 1, flight="TP1932", dep="2026-12-10T07:30:00", arr="2026-12-10T11:00:00", mins=210, total=160.0, checked=True)]     # 3.5 h > 2.5 h
    offers, _, problems, _, notes = convert_one(answer(rows, searched=search), r)
    assert not problems and [o.fits for o in offers] == [True, False, False, False, False]
    assert any("airlines FR, TP; departures 06:00 to 11:59; at most 3 hours" in n and "a checked bag included" in n for n in notes)
    for bad in ({"airlines": ["TAP"]}, {"departure_hours": "25-26"}, {"departure_hours": "11-06"}, {"max_hours": 0}):
        with pytest.raises(ValueError):
            booking_flights_recipe("LIS", "OPO", DAY, **bad)


def test_the_cabin_of_each_flight_is_shown_and_a_mixed_cabin_flight_still_fits_when_the_cabin_asked_is_in_it():
    rec = booking_flights_recipe("LIS", "JFK", DAY, 2, False, "premium", 2)
    r = row("Best", 1, flight="TP200", cabin="PREMIUM_ECONOMY", total=900.0)
    r["legs"][0]["cabins"] = ["PREMIUM_ECONOMY", "ECONOMY"]
    search = {**json.loads(answer())["searched"], "destination": "JFK", "cabin": "PREMIUM_ECONOMY"}
    o = convert_one(answer([r], searched=search, cabin_back="PREMIUM_ECONOMY"), rec)[0][0]
    assert o.fits is True and o.details["cabin"] == "premium economy + economy"


def test_a_route_without_direct_flights_is_told_by_the_services_own_flag_and_still_lists_the_other_options():
    direct = booking_flights_recipe("LIS", "OPO", DAY, 2, True, "economy", 2)
    rows = [row("Best", 1, flight="KL1234", total=140.0, carrier="KLM", code="KL", via="AMS")]
    offers, _, problems, _, notes = convert_one(answer(rows, searched={**json.loads(answer())["searched"], "stops": "0"}, no_direct_notice=True, results_total=348), direct)
    assert not problems and len(offers) == 1 and offers[0].fits is False and any("ignored" in n or "no direct flight for this search" in n for n in notes)


DETAIL = {"fare": "DISCOUNT", "features": [{"n": "PERSONAL_BAGGAGE", "a": "INCLUDED"}, {"n": "CABIN_BAGGAGE", "a": "INCLUDED"}, {"n": "CHANGEABLE_TICKET", "a": "INCLUDED"}], "change": True, "cancel": False,
          "no_flex": {"title": "Standard ticket", "excluded": ["No refund if you cancel"]}, "baggage_url": "https://www.flytap.com/en-se/baggage",
          "options": [{"name": "DISCOUNT", "total": 102.0, "checked_bag": False, "refundable": False, "changeable": True, "seat": False, "fast_track": False},
                      {"name": "CLASSIC", "total": 159.0, "checked_bag": True, "refundable": False, "changeable": True, "seat": False, "fast_track": False},
                      {"name": "PLUS", "total": 201.0, "checked_bag": True, "refundable": True, "changeable": True, "seat": True, "fast_track": True}]}


def test_the_details_of_a_flight_give_its_fare_name_refund_and_change_rules_features_and_the_whole_fare_ladder():
    """Read live 5 Nov 2026 (GET /api/flight/<token>, what 'View details' opens): TAP's Discount fare 102 EUR for 2 adults, change before departure allowed, cancel not; Classic 159, Plus 201 (refundable, changeable)."""
    first = row("Best", 1)
    first["detail"] = DETAIL
    other = row("Best", 1, flight="TP1928", total=122.12)
    offers, _, problems, _, notes = convert_one(answer([first, other]))
    assert not problems and len(offers) == 2
    a, b = offers
    assert a.details["fare"] == "DISCOUNT: personal item, cabin bag, changeable" and a.details["refund_change"] == "change before departure allowed (a fee may apply); no refund if you cancel (Booking.com's own fare rules, fare DISCOUNT)"
    assert a.details["fare_options"] == "DISCOUNT 102 EUR (changeable) / CLASSIC 159 EUR (checked bag, changeable) / PLUS 201 EUR (checked bag, refundable, changeable, premium seat, fast track)" and a.flexible is False
    assert b.details["refund_change"].startswith("not read for this flight") and b.details["fare_options"] is None and b.flexible is None
    ok = convert_one(answer([first], details_read=1))[4]
    assert any("were read for the 1 cheapest flight(s)" in n for n in ok)
    plus = {**DETAIL, "fare": "PLUS", "cancel": True, "features": DETAIL["features"] + [{"n": "REFUNDABLE_TICKET", "a": "INCLUDED"}]}
    r = row("Best", 1)
    r["detail"] = plus
    o = convert_one(answer([r]))[0][0]
    assert o.flexible is True and o.details["refund_change"].startswith("change before departure allowed (a fee may apply); cancel before departure allowed")


def test_a_details_setting_is_validated():
    assert '"details": 5' in booking_flights_recipe("LIS", "OPO", DAY)["script"] and '"details": 0' in booking_flights_recipe("LIS", "OPO", DAY, details=0)["script"]
    with pytest.raises(ValueError):
        booking_flights_recipe("LIS", "OPO", DAY, details=11)
