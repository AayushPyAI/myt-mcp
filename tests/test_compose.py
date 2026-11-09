"""compose_answer: the answer, the picks and the checks are built by code, from the rows Claude collected."""

import pytest

from myt_mcp.compose import NotChecked, Offer, SourceRead, compose, picks

pytestmark = pytest.mark.anyio

SRC = [SourceRead(name="TAP", read=7, of=7, link="https://booking.flytap.com/booking/flights/deeplink?x=1"),
       SourceRead(name="Skyscanner", read=11, of=108, link="https://www.skyscanner.net/transport/flights/flr/lis/270306/")]


def offers():
    return [Offer(group="FLR -> LIS", source="TAP", name="DISCNEW", price_total=462.9, currency="EUR", fits=False, details={"stops": 0, "checked_bag": False}, supplier="TAP AIR PORTUGAL"),
            Offer(group="FLR -> LIS", source="TAP", name="CLANEW", price_total=567.9, currency="EUR", fits=True, details={"stops": 0, "checked_bag": True}, supplier="TAP AIR PORTUGAL",
                  preferred_reason="departs 12:20, the trip plans 12:10"),
            Offer(group="FLR -> LIS", source="TAP", name="PLUSNEW", price_total=702.9, currency="EUR", fits=True, flexible=True, details={"refund_change": "refundable"}),
            Offer(group="FLR -> LIS", source="Skyscanner", name="Vueling via BCN", price_total=187, currency="GBP", quotable=False, connecting=True)]


def run(**kw):
    args = dict(kind="flights", filters_used=["direct (trip default)", "checked bag (operator)"], sources_read=SRC,
                not_checked=[NotChecked(name="Israir", reason="route not served by the source")], offers=offers(),
                myt_supplier={"TAP AIR PORTUGAL": "yes"}, pickup_time=None, sorted_by_price=True, notes="")
    args.update(kw)
    return compose(**args)


def test_picks_never_recommend_an_option_that_misses_a_wish_and_use_one_currency():
    rows, notes = picks("flights", offers(), True)
    d = {a: (b, c) for a, b, c in rows}
    assert "DISCNEW" in d["Cheapest"][0] and "does NOT meet every wish" in d["Cheapest"][1]
    assert "CLANEW" in d["Best fit"][0] and d["Best fit"][1] == "departs 12:20, the trip plans 12:10"
    assert "PLUSNEW" in d["Most flexible"][0]
    assert "CLANEW" in d["Recommended"][0]                      # not the bag-less DISCNEW
    assert any("GBP" in n for n in notes)                       # the GBP row is shown but not compared


def test_the_answer_has_every_required_line_and_not_shown_for_gaps():
    r = run()
    assert r["ok"] is True
    text = r["answer"]
    assert text.startswith("Sources checked: TAP (7 of 7 read); Skyscanner (11 of 108 read) | Not checked: Israir (route not served by the source)")
    for need in ("Filters used: direct (trip default); checked bag (operator)", "| Cheapest |", "| Best fit |", "| Most flexible |", "| Recommended |",
                 "In MYT supplier? TAP AIR PORTUGAL: yes", "Not shown by the sources:", "Sources: TAP: https://booking.flytap.com", "comparison only"):
        assert need in text, need
    assert "not shown" in text


@pytest.mark.parametrize("change, expected", [
    ({"sources_read": [SourceRead(name="TAP", read=7, of=7, link="https://www.flytap.com/")]}, "not a home page"),
    ({"sources_read": [SourceRead(name="TAP", read=7, link="https://booking.flytap.com/a?b=1")]}, "N of M"),
    ({"not_checked": [NotChecked(name="El Al", reason="skipped for time")]}, "not an allowed reason"),
    ({"not_checked": [NotChecked(name="El Al", reason="you didn't ask")]}, "not an allowed reason"),
    ({"not_checked": [NotChecked(name="El Al", reason="whatever")]}, "must be one of"),
    ({"filters_used": ["direct only"]}, "where it comes from"),
    ({"filters_used": []}, "filters_used is empty"),
    ({"kind": "cars"}, "pickup_time is required"),
])
def test_bad_inputs_are_refused_with_the_exact_fix(change, expected):
    r = run(**change)
    assert r["ok"] is False and any(expected in p for p in r["problems"]), r


def test_an_offer_from_a_source_not_listed_or_without_a_currency_is_refused():
    bad = offers() + [Offer(source="El Al", name="LY385", price_total=300, currency=None)]
    r = run(offers=bad)
    assert r["ok"] is False and any("not in sources_read" in p for p in r["problems"]) and any("without a currency" in p for p in r["problems"])


def test_a_hotel_cheapest_from_a_rating_sorted_list_says_it_is_not_the_cheapest_overall():
    hotels = [Offer(group="Lisbon", source="RateHawk", name="Hostel", price_total=318, currency="EUR"), Offer(group="Lisbon", source="RateHawk", name="Hotel", price_total=538, currency="EUR")]
    rows, _ = picks("hotels", hotels, sorted_by_price=False)
    assert "NOT read" in rows[0][2] and "not the cheapest overall" in rows[0][2]
    assert "NOT read" not in picks("hotels", hotels, sorted_by_price=True)[0][0][2]


def test_a_hotel_read_to_its_last_row_does_not_carry_the_not_cheapest_overall_caveat_but_a_cut_list_does():
    rows = [Offer(group="Terra Nostra", source="Bensaude", name="Cosy Art Deco FLEX", price_total=322, currency="EUR"), Offer(group="Terra Nostra", source="Bensaude", name="Garden View FLEX", price_total=394, currency="EUR")]
    assert "NOT read" not in picks("hotels", rows, sorted_by_price=False, complete=True)[0][0][2]
    assert "NOT read" in picks("hotels", rows, sorted_by_price=False, complete=False)[0][0][2]
    hotel = lambda read, of: [SourceRead(name="Bensaude", read=read, of=of, link="https://bensaude.e-gds.com/webfrontendcorporate/shoppingcart/availability.aspx?hotelid=29")]
    common = dict(kind="hotels", filters_used=["breakfast (operator)"], not_checked=[NotChecked(name="RateHawk", reason="login/captcha/block"), NotChecked(name="Arbitrip", reason="login/captcha/block")],
                  offers=rows, myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert "NOT read" not in compose(sources_read=hotel(2, 2), **common)["answer"]         # all of the source's rows were read
    assert "NOT read" in compose(sources_read=hotel(2, 40), **common)["answer"]            # 2 of 40: something cheaper may be left


def test_a_hotel_answer_from_one_named_source_is_composed_the_first_time_and_names_what_was_not_compared():
    rows = [Offer(group="Terra Nostra", source="Bensaude", name="Cosy Art Deco FLEX", price_total=322, currency="EUR")]
    r = compose(kind="hotels", filters_used=["breakfast (operator)"], sources_read=[SourceRead(name="Bensaude", read=1, of=1, link="https://bensaude.e-gds.com/webfrontendcorporate/shoppingcart/availability.aspx?hotelid=29")],
                not_checked=[], offers=rows, myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert r["ok"] is True and "RateHawk (not read in this answer: not compared)" in r["answer"] and "Arbitrip (not read in this answer: not compared)" in r["answer"]


async def test_compose_answer_tool_is_registered_and_read_only():
    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    async with Client(create_server(Settings())) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert "compose_answer" in tools and tools["compose_answer"].annotations.read_only_hint
        r = await c.call_tool("compose_answer", {"kind": "lounges", "filters_used": [], "sources_read": [{"name": "Aspire", "read": 1, "of": 1, "link": "https://www.aspirelounges.com/airports/tlv/"}],
                                                 "not_checked": [], "offers": [{"source": "Aspire", "name": "TLV lounge", "price_total": 160, "currency": "EUR"}]})
        assert not r.is_error and r.structured_content["ok"] is True and "Aspire (1 of 1 read)" in r.structured_content["answer"]


def _rh_row(name, stars, dist, score, reviews, room, meal, free_before, amount, path, pct="100.00", taxes=None, kind="Hotel"):
    return {"p": 1, "rank": 1, "name": name, "kind": kind, "stars": stars, "dist_km": dist, "score": score, "reviews": reviews, "room": room, "meal": meal, "free_before": free_before,
            "penalty": [{"from": None, "to": free_before, "amt": "0.00"}, {"from": free_before, "to": None, "pct": pct, "amt": f"{amount:.2f}"}] if free_before else [{"from": None, "to": None, "pct": pct, "amt": f"{amount:.2f}"}],
            "pay": "deposit", "amount": amount, "cur": "EUR", "per_night": amount / 2, "taxes_extra": taxes or [], "left": None, "path": path}


SAMPLE_RH = {"ok": True, "check_in": "2027-05-03", "check_out": "2027-05-05", "adults": 2, "child_ages": [], "residency": "en-il", "sort": "price_asc", "filters": {}, "offset": 0,
             "results_total": 1160, "search_finished": True, "page_header_count": 1160, "unparsed": 0, "rows_read": 3, "rows": [
    _rh_row("White House Lisbon Hostel", 1, 3.0, 9.0, None, "Bed in Dorm", ["nomeal"], None, 61, "/hotel/portugal/lisbon/mid1/white/", kind="Hostel"),
    _rh_row("Hotel Four", 4, 1.2, 8.8, 900, "Twin room (twin beds)", ["breakfast"], "2027-05-01T00:00:00Z", 450, "/hotel/portugal/lisbon/mid3/four/", taxes=[{"n": "city_tax", "a": 8.0, "c": "EUR"}]),
    _rh_row("Hotel Alegria", 3, 0.7, 9.4, 1765, "Double room (full double bed)", ["breakfast"], "2027-05-01T00:00:00Z", 513, "/hotel/portugal/lisbon/mid2/alegria/")]}


def test_ratehawk_recipe_url_and_script_are_built_from_the_search():
    from datetime import date

    from myt_mcp.recipes import ratehawk_hotels_recipe

    r = ratehawk_hotels_recipe("Portugal", "Lisbon", date(2027, 5, 3), date(2027, 5, 5), 2, "price_asc", True, True, 4, 2)
    assert r["url"] == ("https://www.ratehawk.com/hotel/portugal/lisbon/?dates=03.05.2027-05.05.2027&guests=2&residency=en-il&meal_types=breakfast&payment=freecancellation"
                        "&stars=4.5&sort=price.asc&page=1")
    assert r["expect_sort"] == "Price (low to high)" and "__MAX_PAGES__" not in r["script"] and "const MAX_PAGES = 2;" in r["script"]
    assert "/hotel/search/v2/b2bsite/serp" in r["script"] and "zenpagination" not in r["script"] and '"sort": "price_asc"' in r["script"] and '"stars_min": 4' in r["script"] and '"breakfast": true' in r["script"]
    assert r["expect"]["filters"] == {"stars": [40, 50], "free_cancellation": True, "meals": ["breakfast"]} and r["expect"]["nights"] == 2 and r["expect"]["children_ages"] == []
    with pytest.raises(ValueError):
        ratehawk_hotels_recipe("Portugal", "Lisbon", date(2027, 5, 3), date(2027, 5, 5), 2, "price_asc", False, False, None, 99)


def test_ratehawk_rows_become_offers_without_retyping_and_the_cheapest_is_checked_against_the_price_sorted_list():
    import json

    from myt_mcp.recipes import offers_from_ratehawk

    offers, src, problems, by_price = offers_from_ratehawk([json.dumps(SAMPLE_RH)], ["https://www.ratehawk.com/hotel/portugal/lisbon/?x=1"], {"breakfast": True, "free_cancellation": True, "stars_min": 3}, "Hotels")
    assert not problems and by_price is True and src[0].of == 1160 and src[0].read == 3
    names = {o.name: o for o in offers}
    assert names["White House Lisbon Hostel"].fits is False and names["Hotel Alegria"].fits is True and names["Hotel Four"].fits is True
    assert names["Hotel Four"].price_total == 450 and names["Hotel Four"].currency == "EUR" and names["Hotel Four"].details["reviews"] == 900
    assert names["Hotel Alegria"].flexible is True and names["White House Lisbon Hostel"].flexible is None
    assert names["Hotel Alegria"].details["cancellation"].startswith("Free cancellation until 2027-05-01 00:00 UTC; then a fee: 513.00 EUR (100%) from 2027-05-01 00:00 UTC") and names["Hotel Four"].details["taxes_not_in_price"] == "city_tax 8 EUR payable at the property"
    assert names["White House Lisbon Hostel"].details["cancellation"] == "No free cancellation: 100% penalty (non-refundable)" and names["Hotel Four"].price_basis == "whole stay: 2 nights for 2 guests"
    bad = dict(SAMPLE_RH, search_finished=False)
    assert any("had not finished" in p for p in offers_from_ratehawk([json.dumps(bad)], [], None, "Hotels")[2])
    assert any("script reported" in p for p in offers_from_ratehawk([json.dumps({"ok": False, "error": "x"})], [], None, "Hotels")[2])
    assert any("not the script's JSON" in p for p in offers_from_ratehawk(["not json"], [], None, "Hotels")[2])


async def test_compose_answer_takes_the_ratehawk_script_answer_directly():
    import json

    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    async with Client(create_server(Settings())) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        assert "ratehawk_hotels_recipe" in tools
        r = await c.call_tool("compose_answer", {
            "kind": "hotels", "filters_used": ["breakfast (operator)", "free cancellation (operator)"], "sources_read": [],
            "not_checked": [{"name": "Arbitrip", "reason": "login/captcha/block: test"}], "offers": [],
            "ratehawk_results": [json.dumps(SAMPLE_RH)], "ratehawk_urls": ["https://www.ratehawk.com/hotel/portugal/lisbon/?dates=03.05.2027-05.05.2027&guests=2&sort=price.asc&page=1"],
            "hotel_wishes": {"breakfast": True, "free_cancellation": True}, "myt_supplier": {"Hotel Four": "not checked: test"}})
        d = r.structured_content
        assert not r.is_error and d["ok"] is True, d
        assert "RateHawk (3 of 1160 read)" in d["answer"] and "Hotel Four" in d["answer"] and "| Cheapest |" in d["answer"]
        assert "list sorted by price was NOT read" not in d["answer"]


def test_a_hotel_pick_with_a_low_score_or_few_reviews_gets_a_caution_from_its_own_numbers():
    low = Offer(group="L", source="RateHawk", name="Hostel", price_total=117, currency="EUR", details={"score": "6.4", "reviews": 27}, fits=True)
    good = Offer(group="L", source="RateHawk", name="Hotel", price_total=300, currency="EUR", details={"score": "9.1", "reviews": 900}, fits=True)
    _, notes = picks("hotels", [low, good], True)
    assert any("Caution on the Best fit (Hostel)" in n and "6.4" in n and "27" in n for n in notes)
    _, notes = picks("hotels", [good], True)
    assert not any("Caution" in n for n in notes)


def test_ratehawk_recipe_writes_children_into_the_guests_value_and_refuses_bad_ages():
    from datetime import date

    from myt_mcp.recipes import ratehawk_hotels_recipe

    r = ratehawk_hotels_recipe("Portugal", "Lisbon", date(2027, 5, 3), date(2027, 5, 5), 2, "rating", children_ages=[6])
    assert "guests=2and6" in r["url"] and "sort=rating" in r["url"] and "residency" in r["script"]
    assert "guests=2and6and8" in ratehawk_hotels_recipe("Portugal", "Lisbon", date(2027, 5, 3), date(2027, 5, 5), 2, "rating", children_ages=[6, 8])["url"]
    with pytest.raises(ValueError):
        ratehawk_hotels_recipe("Portugal", "Lisbon", date(2027, 5, 3), date(2027, 5, 5), 2, "rating", children_ages=[30])


def _car_row(model, sipp, category, gearbox, seats, large, small, company, price, ins="excess", cdw=None, deposit=1200, free=True, rating=None, sub="meet_greet"):
    cancel = ([{"from": "2027-04-01T10:00:01Z", "to": "2027-04-10T10:00:00Z", "fee": 0.0, "refundable": True}, {"from": "2027-04-10T10:00:01Z", "to": "2027-04-12T10:00:00Z", "fee": 50.0, "refundable": True}] if free
              else [{"from": "2027-04-10T10:00:01Z", "to": "2027-04-12T10:00:00Z", "fee": 50.0, "refundable": False}])
    return {"model": model, "sipp": sipp, "category": category, "gearbox": gearbox, "seats": seats, "doors": 5, "ac": True, "electric": False, "bags_small": small, "bags_medium": 0, "bags_large": large,
            "company": company, "rating": rating, "supplier": "x", "pickup": {"name": "Faro Airport", "type": "airport", "sub": sub, "address": "Rua X", "iata": "FAO", "at": "2027-04-12T10:00:00Z"},
            "dropoff": {"name": "Faro Airport", "sub": sub, "at": "2027-04-17T10:00:00Z"}, "deposit": deposit, "ins_type": ins, "excess_cdw": cdw, "excess_theft": cdw, "mileage": 0, "fuel": "full_full", "cancel": cancel,
            "fees": [{"n": "Additional driver", "a": 20.0, "in": False, "pay": "on_site", "t": "additional_driver"}], "extras": [], "driver": {"min": 21, "max": 74, "years": 2, "young": 26}, "price": price, "currency": "EUR", "fee_service": 8.94}


CARS_RESULT = {"ok": True, "search": {"route": "965846144,965846144", "date": "2027-04-12T10:00,2027-04-17T10:00", "age": "26,69", "residency": "il"}, "filters": {"vehicle_transmission_type": ["automatic"]}, "offset": 0,
               "search_total": 1481, "reached_cap": False, "rows": [
    _car_row("Opel Corsa", "EDAR", "economy", "automatic", 5, 2, 1, "Tangerine", 61.83, cdw=1900, deposit=2100, rating=5.4),
    _car_row("Ford Focus", "CDAR", "compact", "automatic", 4, 1, 1, "Dollar", 150.0, ins="zero_excess", deposit=200, rating=5.8, sub="in_terminal"),
    _car_row("VW Golf", "CDMR", "compact", "manual", 5, 2, 2, "Sixt", 170.0, cdw=1500, deposit=800, free=False, rating=7.0)]}


def test_ratehawk_cars_recipe_needs_known_ids_and_times_and_builds_the_url():
    from myt_mcp.sites.ratehawk_cars import ratehawk_cars_recipe

    r = ratehawk_cars_recipe("Faro Airport", None, "2027-04-12", "10:00", "2027-04-17", "10:00", automatic=True, zero_excess=True, max_cars=20)
    assert r["url"] == "https://www.ratehawk.com/cars/?route=965846144,965846144&date=2027-04-12T10:00,2027-04-17T10:00&age=26,69&residency=il"
    assert r["filters_to_tick"] == ["Automatic", "Zero excess"] and "const MAX_CARS = 20;" in r["script"] and '["Automatic", "Zero excess"]' in r["script"]
    unknown = ratehawk_cars_recipe("Lagos", None, "2027-04-12", "10:00", "2027-04-17", "10:00")
    assert unknown["needs_location_id"] == "Lagos" and "faro airport" in unknown["known_places"] and "route=" in " ".join(unknown["steps"])
    assert "url" in ratehawk_cars_recipe("Lagos", None, "2027-04-12", "10:00", "2027-04-17", "10:00", pickup_id=1)
    for bad in ({"pickup_time": "9am"}, {"dropoff_date": "2027-04-10"}, {"max_cars": 1}):
        args = {"pickup": "Faro Airport", "dropoff": None, "pickup_date": "2027-04-12", "pickup_time": "10:00", "dropoff_date": "2027-04-17", "dropoff_time": "10:00", **bad}
        with pytest.raises(ValueError):
            ratehawk_cars_recipe(**args)


def test_ratehawk_cars_rows_become_offers_and_the_cheapest_that_misses_a_wish_is_not_recommended():
    import json

    from myt_mcp.sites.ratehawk_cars import convert

    rows = convert(json.dumps(CARS_RESULT), {"automatic": True, "zero_excess": True}, "Cars")
    assert not rows.problems and rows.read == 3 and rows.total == 3                       # a filtered list: only what was read is known (RateHawk's count is the whole search's)
    by = {o.name: o for o in rows.offers}
    assert by["Opel Corsa (EDAR \u2022 Economy)"].fits is False and by["Ford Focus (CDAR \u2022 Compact)"].fits is True and by["VW Golf (CDMR \u2022 Compact)"].fits is False
    corsa, focus, golf = by["Opel Corsa (EDAR \u2022 Economy)"], by["Ford Focus (CDAR \u2022 Compact)"], by["VW Golf (CDMR \u2022 Compact)"]
    assert corsa.details["company"] == "Tangerine (rated 5.4)" and focus.details["deposit"] == "200 EUR" and focus.flexible is True and golf.flexible is None
    assert corsa.details["excess"] == "Basic cover with excess: excess 1,900 EUR (theft 1,900)" and focus.details["excess"] == "Zero excess" and corsa.details["mileage"] == "Unlimited mileage" and corsa.details["fuel"] == "Full to full"
    assert corsa.details["pickup_place"] == "Faro Airport (meeting with an agent)" and focus.details["pickup_place"] == "Faro Airport (in the terminal)"
    assert corsa.details["cancellation"].startswith("Free cancellation until 2027-04-10 10:00 UTC; then a fee: 50 EUR from 2027-04-10 10:00 UTC to 2027-04-12 10:00 UTC") and golf.details["cancellation"].startswith("No free cancellation: fee 50 EUR")
    assert corsa.details["fees_not_in_price"] == "Additional driver 20 EUR (on site)" and corsa.details["driver_requirements"] == "age 21-74, licence 2 years, young-driver fee under 26" and corsa.price_basis.startswith("whole rental")
    assert corsa.details["seats_bags"] == "5 seats / 2 large + 1 small bags"
    unfiltered = convert(json.dumps({**CARS_RESULT, "filters": {}}), {}, "Cars")
    assert unfiltered.total == 1481                                                       # without filters the whole search's count is the real "of M"
    assert not convert(json.dumps({"ok": False, "error": "x"}), {}, "Cars").offers and convert("nope", {}, "Cars").problems


async def test_compose_answer_builds_a_car_answer_from_the_recipe_result():
    import json

    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    async with Client(create_server(Settings())) as c:
        assert "ratehawk_cars_recipe" in {t.name for t in (await c.list_tools()).tools}
        r = await c.call_tool("compose_answer", {
            "kind": "cars", "filters_used": ["automatic (operator)", "zero excess (operator)"], "sources_read": [], "not_checked": [], "offers": [], "pickup_time": "10:00 on both days",
            "site_results": [{"site": "ratehawk_cars", "result": json.dumps(CARS_RESULT), "url": "https://www.ratehawk.com/cars/?route=965846144,965846144&date=2027-04-12T10:00,2027-04-17T10:00&age=26,69&residency=il"}],
            "wishes": {"automatic": True, "zero_excess": True}, "myt_supplier": {"Dollar": "not checked: test"}})
        d = r.structured_content
        assert not r.is_error and d["ok"] is True, d
        assert "RateHawk Car rental (3 of 3 read)" in d["answer"] and "Ford Focus" in d["answer"] and "Pick-up time used on every source: 10:00 on both days" in d["answer"]
        pick = [l for l in d["answer"].splitlines() if l.startswith("| Recommended")][0]
        assert "Ford Focus" in pick and "Corsa" not in pick


TRANSFERS_RESULT = {"ok": True, "form": {"from": "Leonardo da Vinci Rome Fiumicino Airport (FCO)", "to": "Room Mate Collection Mia, Rome Colosseum", "when": "1 Mar, Mon, 16:30", "passengers": "2 adults, 1 child"},
                    "rows_read": 3, "sort_tab": None, "price_order": "ascending", "rows": [
    {"vehicle": "Toyota Prius, Toyota Corolla or similar", "vehicle_class": "Economy", "passengers": "3", "bags": "3", "waiting": "60 min. waiting time included ", "meeting": "Meeting with a plate ",
     "flight_tracking": True, "cancellation": "Free cancellation 24h before the trip", "price": 81, "currency": "EUR", "child_seat": "Including seats for children € 4"},
    {"vehicle": "Mercedes E-class", "vehicle_class": "Business", "passengers": "3", "bags": "3", "waiting": "60 min. waiting time included ", "meeting": "Meeting with a plate ",
     "flight_tracking": True, "cancellation": "Free cancellation 24h before the trip", "price": 120, "currency": "EUR", "child_seat": None},
    {"vehicle": "VW T5 or similar", "vehicle_class": "Minibus", "passengers": "16", "bags": "16", "waiting": "60 min. waiting time included ", "meeting": "Meeting with a plate ",
     "flight_tracking": True, "cancellation": "No free cancellation", "price": 427, "currency": "EUR", "child_seat": "Including seats for children € 4"}]}


def test_ratehawk_transfers_checks_what_the_page_searched_against_the_request():
    import json

    from myt_mcp.sites.ratehawk_transfers import convert, ratehawk_transfers_recipe

    r = ratehawk_transfers_recipe("Rome FCO", "Room Mate Collection Mia", "2027-03-01", "16:30", 2, [8])
    assert r["expect"]["children"] == 1 and "Transfers tab" in r["steps"][0] and "cards" in r["script"]
    with pytest.raises(ValueError):
        ratehawk_transfers_recipe("a", "b", "2027-03-01", "4pm", 2)
    ok = convert(json.dumps(TRANSFERS_RESULT), {"expect": {"pickup": "Rome FCO Fiumicino", "dropoff": "Room Mate Collection Mia", "day": "2027-03-01", "time": "16:30", "adults": 2, "children": 1}}, "Transfers")
    assert not ok.problems and ok.read == 3 and ok.sorted_by_price is True
    by = {o.name.split(":")[0]: o for o in ok.offers}
    assert by["Economy"].price_total == 81 and by["Economy"].flexible is True and by["Minibus"].flexible is None and by["Economy"].fits is True
    wrong_time = convert(json.dumps(TRANSFERS_RESULT), {"expect": {"pickup": "FCO", "dropoff": "Mia", "day": "2027-03-01", "time": "10:00", "adults": 2, "children": 1}}, "Transfers")
    assert any("not at 10:00" in p for p in wrong_time.problems)
    wrong_place = convert(json.dumps(TRANSFERS_RESULT), {"expect": {"pickup": "Milan Linate", "dropoff": "Mia", "day": "2027-03-01", "time": "16:30", "adults": 2, "children": 1}}, "Transfers")
    assert any("searched from" in p for p in wrong_place.problems)
    wrong_day = convert(json.dumps(TRANSFERS_RESULT), {"expect": {"pickup": "FCO", "dropoff": "Mia", "day": "2027-03-02", "time": "16:30", "adults": 2, "children": 1}}, "Transfers")
    assert any("2027-03-02" in p for p in wrong_day.problems)
    wrong_pax = convert(json.dumps(TRANSFERS_RESULT), {"expect": {"pickup": "FCO", "dropoff": "Mia", "day": "2027-03-01", "time": "16:30", "adults": 3, "children": 0}}, "Transfers")
    assert any("3 adults" in p for p in wrong_pax.problems)



# ---- compact parts: the script's rows reach the server in short, checked parts ----

import json


def seal(text):
    """What emit.js does to every part: the CRC32 of the part's own text, as its last key."""
    import zlib
    return text[:-1] + ',"crc":"' + format(zlib.crc32(text.encode("utf-8")), "08x") + '"}'


def _part(run, part, parts, rows, read=3, **extra):
    head = {"ok": True, "check_in": "2027-05-03", "check_out": "2027-05-05", "adults": 2, "child_ages": [], "residency": "en-il", "sort": "price_asc", "filters": {}, "offset": 0, "results_total": 443,
            "search_finished": True, "run": run, "rows_read": read, "part": part, "parts": parts}
    head.update(extra)
    cols = ["name", "amount", "path"]
    common = {"stars": 4, "meal": ["breakfast"], "free_before": "2027-05-01T00:00:00Z", "penalty": [], "pay": "deposit", "cur": "EUR", "taxes_extra": []}
    return seal(json.dumps({**head, "cols": cols, "common": common, "path_base": "/hotel/portugal/lisbon/", "rows": rows}))


def test_parts_are_joined_decoded_and_checked():
    from myt_mcp.sites import convert_all, expand
    a = _part("r1", 1, 2, [["Hotel A", 100, "mid1/a/"], ["Hotel B", 110, "mid2/b/"]])
    b = _part("r1", 2, 2, [["Hotel C", 120, "mid3/c/"]])
    plain = json.loads(expand(a))
    assert plain["rows"][0]["path"] == "/hotel/portugal/lisbon/mid1/a/" and plain["rows"][0]["meal"] == ["breakfast"] and "cols" not in plain
    offers, sources, problems, by_price, _ = convert_all([{"site": "ratehawk_hotels", "result": a, "url": "u"}, {"site": "ratehawk_hotels", "result": b, "url": "u"}],
                                                          {"breakfast": True, "free_cancellation": True})
    assert not problems and [o.name for o in offers] == ["Hotel A", "Hotel B", "Hotel C"] and offers[0].fits is True and by_price
    assert offers[2].link == "https://www.ratehawk.com/hotel/portugal/lisbon/mid3/c/"
    # a missing part is refused, with the way to get it
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_hotels", "result": a, "url": "u"}], None)
    assert any("part(s) 2 of 2 are missing" in p and "__mytParts" in p for p in problems)
    # rows that do not add up to what the script read are refused
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_hotels", "result": _part("r2", 1, 1, [["Hotel A", 100, "mid1/a/"]], read=3), "url": "u"}], None)
    assert any("hold 1 rows but the script read 3" in p for p in problems)
    # two runs (price sort and rating sort) never count as parts of each other
    other = _part("r9", 1, 1, [["Hotel Z", 500, "mid9/z/"]], read=1)
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_hotels", "result": other, "url": "u"}, {"site": "ratehawk_hotels", "result": a, "url": "u"}, {"site": "ratehawk_hotels", "result": b, "url": "u"}], None)
    assert not problems


def test_with_emit_needs_the_script_shape():
    from myt_mcp.sites import with_emit
    assert "const emit" in with_emit("await (async () => {\n  return 1;\n})()")
    with pytest.raises(ValueError):
        with_emit("1 + 1")


def test_hand_typed_rows_without_a_proof_of_a_wish_do_not_fit():
    from myt_mcp.compose import apply_wishes
    ok = Offer(group="Hotels", source="Arbitrip", name="A", price_total=100, currency="EUR", price_basis="whole stay", details={"meal": "Breakfast", "cancellation": "Free cancellation", "stars": 4})
    cheap = Offer(group="Hotels", source="Arbitrip", name="B", price_total=90, currency="EUR", price_basis="whole stay", details={"meal": "Breakfast", "cancellation": None, "stars": 4})
    apply_wishes([ok, cheap], {"breakfast": True, "free_cancellation": True, "stars_min": 4})
    assert ok.fits is True and cheap.fits is False
    plain = Offer(group="Hotels", source="X", name="C", price_total=1, currency="EUR", price_basis="whole stay")
    apply_wishes([plain], None)
    assert plain.fits is None


@pytest.mark.anyio
async def test_a_minimal_compose_call_works_and_a_hotel_source_left_out_is_named_not_refused():
    import json

    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    item = {"site": "ratehawk_hotels", "result": json.dumps(SAMPLE_RH), "url": "https://www.ratehawk.com/hotel/portugal/lisbon/?dates=03.05.2027-05.05.2027&guests=2&sort=price.asc&page=1"}
    async with Client(create_server(Settings())) as c:
        r = await c.call_tool("compose_answer", {"kind": "hotels", "site_results": [item], "wishes": {"breakfast": True, "free_cancellation": True},
                                                 "myt_supplier": {"Hotel Four": "not checked: test"}})
        d = r.structured_content
        assert d["ok"] is True and "Arbitrip (not read in this answer: not compared)" in d["answer"] and "RateHawk (not read" not in d["answer"], d     # never a refusal: the answer says what was not compared
        r = await c.call_tool("compose_answer", {"kind": "hotels", "site_results": [item], "wishes": {"breakfast": True, "free_cancellation": True},
                                                 "not_checked": [{"name": "Arbitrip", "reason": "login/captcha/block: test"}], "myt_supplier": {"Hotel Four": "not checked: test"}})
        d = r.structured_content
        assert d["ok"] is True and "Breakfast included (operator)" in d["answer"] and "Free cancellation (operator)" in d["answer"], d


def test_ratehawk_card_text_becomes_the_script_row_and_missing_fields_stay_none():
    from myt_mcp.tools.ratehawk_live import parse_card
    full = parse_card({"name": "Hostel Seven Hills", "stars": 2, "href": "/hotel/portugal/lisbon/mid6956517/hostel_seven_hills/?q=2080", "text": "Hostel Seven Hills\nAvenida Almirante Reis, 66\n1.6 km from the Lisbon center\n133 m from Anjos\n6.4\n27 reviews\n1 / 10\nStandard Double room (shared bathroom)\nfull double bed\nBreakfast incl.\nFree cancellation\nPay by wire transfer\nEUR\u00a0118\nfor 2 nights for 2 guests\nShow all rooms"})
    assert (full["name"], full["stars"], full["score"], full["reviews"], full["meal"], full["cancellation"], full["bed"], full["basis"]) == (
        "Hostel Seven Hills", 2, "6.4", "27 reviews", "Breakfast incl.", "Free cancellation", "full double bed", "for 2 nights for 2 guests")
    assert full["price"].replace("\u00a0", " ") == "EUR 118" and full["path"] == "/hotel/portugal/lisbon/mid6956517/hostel_seven_hills/" and full["distance"].startswith("1.6 km")
    thin = parse_card({"name": "Back To Lisbon Hostel", "stars": None, "href": None, "text": "Back To Lisbon Hostel\nRua De Santo Amaro\n1.5 km from the Lisbon center\nmax 1\n1 / 10\nStandard Quadruple room\nBreakfast incl.\nFree cancellation\nEUR 131\nfor 2 nights for 2 guests"})
    assert thin["score"] is None and thin["reviews"] is None and thin["stars"] is None and thin["bed"] is None and thin["room"] == "Standard Quadruple room"


def test_a_hotel_with_breakfast_in_its_name_does_not_get_its_name_as_meal_plan():
    from myt_mcp.tools.ratehawk_live import parse_card
    row = parse_card({"name": "República Bed & Breakfast & Arts", "stars": 3, "href": "/hotel/p/c/mid1/x/", "text": "República Bed & Breakfast & Arts\nRua X\n3.3 km from the Lisbon center\n9.5\n378 reviews\n1 / 5\nStandard Double room (shared bathroom)\nfull double bed\nBreakfast incl.\nFree cancellation\nEUR 211\nfor 2 nights for 2 guests"})
    assert row["meal"] == "Breakfast incl." and row["cancellation"] == "Free cancellation"
    none = parse_card({"name": "Bed & Breakfast Y", "stars": 2, "href": None, "text": "Bed & Breakfast Y\nRua Z\n1 / 3\nSingle room\nNo meals included\nEUR 90"})
    assert none["meal"] == "No meals included"


def test_page_runs_become_one_answer_the_converter_accepts():
    import json as _json

    from myt_mcp.sites import convert_all
    from myt_mcp.tools.ratehawk_live import answer_json
    row = lambda n, price: {"name": f"H{n}", "stars": 3, "distance": "1 km from the Lisbon center", "score": "8.0", "reviews": "100 reviews", "room": "Double", "bed": None, "meal": "Breakfast incl.",
                            "cancellation": "Free cancellation", "payment": "Pay by wire transfer", "price": f"EUR {price}", "basis": "for 2 nights for 2 guests", "path": f"/hotel/p/c/mid{n}/h{n}/", "p": 1}
    runs = [{"info": {"header": "Lisbon: 443 accommodation options available", "sort": "Price (low to high)", "page": "1"}, "rows": [row(1, 100), row(2, 110)]},
            {"info": {"header": None, "sort": "Price (low to high)", "page": "2"}, "rows": [row(3, 120)]}]
    text = answer_json(runs, "Price (low to high)")
    data = _json.loads(text)
    assert data["sort"] == "price_asc" and data["rows_read"] == 3 and data["results_total"] == 443 and data["rows"][0]["amount"] == 100 and data["rows"][0]["meal"] == ["breakfast"] and data["rows"][0]["dist_km"] == 1.0
    assert data["rows"][0]["cancel_text"] == "Free cancellation" and data["rows"][0]["free"] is True and data["rows"][0]["score"] == 8.0 and data["rows"][0]["reviews"] == 100
    offers, sources, problems, by_price, _ = convert_all([{"site": "ratehawk_hotels", "result": text, "url": "u"}], {"breakfast": True, "free_cancellation": True})
    assert not problems and len(offers) == 3 and by_price and sources[0].of == 443 and offers[0].details["cancellation"] == "Free cancellation" and offers[0].flexible is True
    mixed = answer_json([{"info": {"header": None, "sort": "Price (low to high)", "page": "1"}, "rows": [row(1, 100), row(2, 300), row(3, 200)]}], "Price (low to high)")
    for bad in (mixed, answer_json([{"info": {"header": None, "sort": "Price (low to high)", "page": "1"}, "rows": [row(1, 200), row(2, 100)]}], "Price (low to high)")):
        _, _, problems, _, _ = convert_all([{"site": "ratehawk_hotels", "result": bad, "url": "u"}], None)
        assert any("not ascending" in q for q in problems)


def test_table_is_limited_but_the_picks_use_every_row_and_a_thin_recommendation_is_replaced():
    rows = [Offer(group="H", source="RateHawk", name=f"Hotel {i}", price_total=100 + i, currency="EUR", price_basis="whole stay", fits=True, flexible=True,
                  details={"stars": 3, "score": "6.4" if i == 0 else "8.5", "reviews": 20 if i == 0 else 300, "distance_from_centre": "1 km", "meal": "Breakfast", "cancellation": "Free cancellation", "room_bed": "Double"},
                  link=f"https://x.test/{i}") for i in range(30)]
    out = compose("hotels", ["Breakfast (operator)"], [SourceRead(name="RateHawk", read=30, of=100, link="https://x.test/list")], [NotChecked(name="Arbitrip", reason="no browser tool: test")], rows, {}, None, True, "", max_rows=5)
    a = out["answer"]
    assert out["ok"] and a.count("| RateHawk | Hotel ") < 30 and "of the 30 options read" in a
    assert "| Cheapest | RateHawk: Hotel 0 " in a                       # the cheapest is still found among all rows
    assert "| Recommended | RateHawk: Hotel 1 " in a and "is thin" in a  # the thin Best fit (6.4 from 20 reviews) is not the recommendation


def test_budget_and_distance_limits_decide_fits_and_a_missing_number_does_not_pass():
    from myt_mcp.compose import distance_km, meets_limits
    assert distance_km("1.6 km from the Lisbon center") == 1.6 and distance_km("214 m from the Lisbon center") == 0.214 and distance_km("not shown") is None
    w = {"max_total": 300, "max_distance_km": 2}
    assert meets_limits(250, "900 m from the centre", w) and not meets_limits(350, "900 m", w) and not meets_limits(250, "3.3 km from the centre", w)
    assert not meets_limits(250, None, w) and not meets_limits(None, "1 km", w) and meets_limits(999, None, {})


@pytest.mark.anyio
async def test_ratehawk_hotels_asks_the_operator_first_and_searches_nothing(monkeypatch):
    from mcp import Client

    monkeypatch.setenv("RATEHAWK_SERVER_BROWSER", "1")

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    async with Client(create_server(Settings())) as c:
        r = await c.call_tool("ratehawk_hotels", {"country": "portugal", "city": "lisbon", "check_in": "2027-05-03", "check_out": "2027-05-05", "breakfast": True, "free_cancellation": True})
        d = r.structured_content
        assert d["ok"] is False and d["searched"] is False and len(d["ask_operator"]) == 3 and "operator_answered" in d["next"]
        r = await c.call_tool("ratehawk_hotels", {"country": "portugal", "city": "lisbon", "check_in": "2027-05-03", "check_out": "2027-05-05", "stars": 4, "budget_per_night": 200})
        assert len(r.structured_content["ask_operator"]) == 1 and "centre" in r.structured_content["ask_operator"][0]


def test_the_table_lists_only_options_that_meet_the_wishes_and_says_how_many_were_left_out():
    ok = Offer(group="H", source="RateHawk", name="Fits", price_total=200, currency="EUR", price_basis="whole stay", fits=True, details={"stars": 4, "score": "8.5", "reviews": 300, "distance_from_centre": "1 km", "meal": "Breakfast", "cancellation": "Free cancellation", "room_bed": "Double"})
    far = Offer(group="H", source="RateHawk", name="Too far", price_total=100, currency="EUR", price_basis="whole stay", fits=False, details=dict(ok.details, distance_from_centre="5 km"))
    out = compose("hotels", ["x (operator)"], [SourceRead(name="RateHawk", read=2, of=9, link="https://x.test/l")], [NotChecked(name="Arbitrip", reason="no browser tool: test")], [ok, far], {}, None, True, "")
    a = out["answer"]
    assert "| RateHawk | Fits |" in a and "| RateHawk | Too far |" not in a and "1 of the 2 options read do not meet every wish" in a


@pytest.mark.anyio
async def test_a_block_page_stops_the_read_and_the_same_search_is_reused_for_ten_minutes():
    from myt_mcp.browser import BrowserError
    from myt_mcp.tools import ratehawk_live

    class Blocked:
        url = "https://www.ratehawk.com/hotel/x/?page=1"

        async def goto(self, url, **kw):
            pass

        async def wait_for_selector(self, sel, **kw):
            raise TimeoutError("no cards")

        async def evaluate(self, js):
            return "Please verify you are not a robot"

    with pytest.raises(BrowserError, match="block or a captcha"):
        await ratehawk_live._read_one(Blocked(), "https://www.ratehawk.com/hotel/x/?page=1", 1, "Price (low to high)")

    runs = []

    class Browser:
        async def run(self, origin, start, action):
            runs.append(1)
            return [{"info": {"header": None, "sort": "s", "page": "1"}, "rows": []}]

    class Svc:
        def browser(self):
            return Browser()

    jobs = [("https://www.ratehawk.com/hotel/cache-test/?page=1", 1, "s")]
    ratehawk_live._cache.clear()
    await ratehawk_live.read_lists(Svc(), jobs)
    await ratehawk_live.read_lists(Svc(), jobs)
    assert len(runs) == 1 and ratehawk_live.checked_at(jobs)


@pytest.mark.anyio
async def test_the_server_browser_tool_is_off_by_default_and_the_chrome_recipe_asks_first_and_reads_a_window(monkeypatch):
    monkeypatch.setenv("LEGACY_TOOL_POINTERS", "1")      # the pointers are not listed unless asked for (myt_mcp/legacy.py)
    import json as _json

    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    from myt_mcp.sites import convert_all

    monkeypatch.delenv("RATEHAWK_SERVER_BROWSER", raising=False)
    async with Client(create_server(Settings())) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert "ratehawk_hotels" in names and "ratehawk_hotels_recipe" in names      # the old name stays, as a pointer to the recipe
        pointer = (await c.call_tool("ratehawk_hotels", {"country": "portugal", "city": "lisbon", "stars": 4, "operator_answered": True})).structured_content
        assert pointer["ok"] is False and "ratehawk_hotels_recipe" in pointer["next"]
        base = {"country": "portugal", "city": "lisbon", "check_in": "2027-05-03", "check_out": "2027-05-05", "breakfast": True, "free_cancellation": True}
        asked = (await c.call_tool("ratehawk_hotels_recipe", base)).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 3 and "script" not in asked
        r = (await c.call_tool("ratehawk_hotels_recipe", {**base, "stars": 4, "budget_per_night": 250, "operator_answered": True, "offset": 30})).structured_content
        assert "page=2" in r["url"] and "stars=4.5" in r["url"]
        assert "const START_PAGE = 2;" in r["script"] and "const SKIP = 10;" in r["script"] and "const LIMIT = 30;" in r["script"] and "const MAX_PAGES = 2;" in r["script"]
        assert r["wishes"]["max_total"] == 500 and r["wishes"]["stars_min"] == 4 and any("500 for 2 night" in f for f in r["filters_used"]) and "offset=60" in r["more"]
        first = (await c.call_tool("ratehawk_hotels_recipe", {**base, "stars": 3, "operator_answered": True})).structured_content
        assert "page=1" in first["url"] and "const SKIP = 0;" in first["script"] and "const MAX_PAGES = 2;" in first["script"] and "const LIMIT = 30;" in first["script"]
    row = {"name": "H1", "stars": 4, "distance": "1 km", "score": "8.0", "reviews": "100 reviews", "room": "Double", "bed": None, "meal": "Breakfast incl.", "cancellation": "Free cancellation",
           "payment": None, "price": "EUR 300", "basis": "for 2 nights for 2 guests", "path": "/hotel/p/c/mid1/h1/", "p": 2}
    later = _json.dumps({"ok": True, "header": "Lisbon: 100 accommodation options available", "sort": "Price (low to high)", "start_page": 2, "expected_start": 2, "offset": 30,
                         "pages_read": 1, "rows_read": 1, "stopped": None, "price_order": "ascending", "rows": [row]})
    offers, sources, problems, by_price, notes = convert_all([{"site": "ratehawk_hotels", "result": later, "url": "u"}], None)
    assert not problems and any("options 31 to 31" in n and "not the cheapest overall" in n for n in notes)


def test_hotel_options_of_one_stay_in_separate_source_groups_are_refused():
    mk = lambda g, src, price: Offer(group=g, source=src, name=f"{src} hotel", price_total=price, currency="EUR", price_basis="whole stay", fits=True,
                                     details={"stars": 4, "score": "8.5", "reviews": 300, "distance_from_centre": "1 km", "meal": "Breakfast", "cancellation": "Free cancellation", "room_bed": "Double"})
    sources = [SourceRead(name="RateHawk", read=1, of=10, link="https://x.test/a"), SourceRead(name="Arbitrip", read=1, of=5, link="https://x.test/b")]
    split = compose("hotels", ["x (operator)"], sources, [], [mk("Lisbon", "Arbitrip", 279), mk("Hotels", "RateHawk", 234)], {}, None, True, "")
    assert split["ok"] is False and any("ONE `group`" in p for p in split["problems"])
    one = compose("hotels", ["x (operator)"], sources, [], [mk("Lisbon", "Arbitrip", 279), mk("Lisbon", "RateHawk", 234)], {}, None, True, "")
    assert one["ok"] is True and "RateHawk: RateHawk hotel - 234.00 EUR" in one["answer"]
    two_cities = compose("hotels", ["x (operator)"], sources, [], [mk("Lisbon", "RateHawk", 234), mk("Lisbon", "Arbitrip", 279), mk("Porto", "RateHawk", 150), mk("Porto", "Arbitrip", 160)], {}, None, True, "")
    assert two_cities["ok"] is True


# ---- Arbitrip hotels (list rows are comparison only) ----

def _arb(rows, **head):
    base = {"ok": True, "sort": "Price (Low to High)", "contract": "Selected Places", "filters_in_url": [], "breakfast_filter": True, "approx_total": 105, "offset": 0, "price_order": "ascending",
            "cols": ["name", "score", "label", "reviews", "area", "distance", "price", "per_night"], "common": {"stars": 4, "tax_included": True}, "path_base": "", "run": "r1", "part": 1, "parts": 1, "rows_read": len(rows), "rows": rows}
    base.update(head)
    return seal(json.dumps(base))


def test_arbitrip_url_carries_the_operators_filters_as_changes_from_the_agency_defaults(monkeypatch):
    import urllib.parse
    from datetime import date

    from myt_mcp.sites.arbitrip_hotels import arbitrip_hotels_recipe, results_url

    url, keys = results_url("PLACE", "CONTRACT", date(2027, 5, 3), date(2027, 5, 5), 2, None, 4, True, 250, 2.5)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["check_in"] == ["270503"] and q["check_out"] == ["270505"] and q["guests"] == ["2"] and q["contract_id"] == ["CONTRACT"] and q["max_distance"] == ["3"] and q["max_price_per_night"] == ["250"]
    assert json.loads(q["stars"][0]) == {"2": False, "3": False}                  # 4 stars and up = the default 2-5 minus 2 and 3
    assert json.loads(q["categories"][0]) == {"Apartment": True, "Other": True} and json.loads(q["review"][0]) == {"Poor": True}      # no filter the operator did not name
    assert json.loads(q["amenities"][0]) == {"BREAKFAST_INCLUDED": True} and q["sort"] == ["Price (Low to High)"]
    one, _ = results_url("P", "C", date(2027, 5, 3), date(2027, 5, 5), 2, None, 1, False, None, None)
    assert json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(one).query)["stars"][0]) == {"1": True} and "max_price_per_night" not in one and "amenities" not in one
    none, _ = results_url("P", "C", date(2027, 5, 3), date(2027, 5, 5), 2, None, None, False, None, None)
    assert json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(none).query)["stars"][0]) == {"1": True}
    monkeypatch.delenv("ARBITRIP_CONTRACT_ID", raising=False)
    assert arbitrip_hotels_recipe("Lisbon", date(2027, 5, 3), date(2027, 5, 5))["needs_contract_id"] is True
    monkeypatch.setenv("ARBITRIP_CONTRACT_ID", "CONTRACT")
    assert arbitrip_hotels_recipe("Lisbon", date(2027, 5, 3), date(2027, 5, 5), stars=4, limit=30)["filters_in_url"][-1] == "sort"
    assert arbitrip_hotels_recipe("Atlantis", date(2027, 5, 3), date(2027, 5, 5))["needs_place_id"] == "Atlantis"
    assert "children_ages=6" in arbitrip_hotels_recipe("Lisbon", date(2027, 5, 3), date(2027, 5, 5), children_ages=[6])["url"]       # children are supported since 23 Oct 2026
    with pytest.raises(ValueError, match="ages"):
        arbitrip_hotels_recipe("Lisbon", date(2027, 5, 3), date(2027, 5, 5), children_ages=[30])


def test_arbitrip_list_rows_are_comparison_only_and_never_a_pick_when_cancellation_matters():
    from myt_mcp.sites import convert_all

    arb = _arb([["Hotel Principe Real", "8.6", "Very Good", "824", "Near Liberdade", "(0.9 km from center)", 135, 67], ["Luzeiros Suites", "8.8", "Very Good", "2,396", "Near X", "(2.2 km from center)", 252, 126]])
    offers, sources, problems, by_price, notes = convert_all([{"site": "arbitrip_hotels", "result": arb, "url": "https://app.arbitrip.com/results"}], {"breakfast": True, "free_cancellation": True, "max_distance_km": 2})
    assert not problems and by_price and sources[0].name == "Arbitrip" and sources[0].of == 105
    assert all(o.quotable is False and o.group == "Hotels" for o in offers)
    assert offers[0].fits is None and offers[1].fits is False                    # unknown cancellation, and the second is beyond 2 km
    assert "non-refundable" in offers[0].details["cancellation"] and any("comparison only" in n for n in notes)
    plain, _, _, _, _ = convert_all([{"site": "arbitrip_hotels", "result": arb, "url": "u"}], None)
    assert plain[0].fits is True
    bad = _arb([["A", "8", "Good", "10", "x", "(1 km from center)", 200, 100]], price_order="not ascending")
    assert any("not in ascending order" in p for p in convert_all([{"site": "arbitrip_hotels", "result": bad, "url": "u"}], None)[2])
    assert any("script reported" in p for p in convert_all([{"site": "arbitrip_hotels", "result": json.dumps({"ok": False, "error": "x"}), "url": "u"}], None)[2])


def test_the_picks_use_ratehawk_when_arbitrip_cannot_confirm_cancellation():
    rh = Offer(group="Hotels", source="RateHawk", name="RH hotel", price_total=234, currency="EUR", price_basis="whole stay", fits=True,
               details={"stars": 4, "score": "8.5", "reviews": 300, "distance_from_centre": "1 km", "meal": "Breakfast", "cancellation": "Free cancellation", "room_bed": "Double"})
    ab = Offer(group="Hotels", source="Arbitrip", name="AB hotel", price_total=135, currency="EUR", price_basis="whole stay", fits=None, quotable=False,
               details={"stars": 4, "score": "8.6", "reviews": 824, "distance_from_centre": "0.9 km", "meal": "Breakfast included (filter on in the list)", "cancellation": "not in the list", "room_bed": None})
    out = compose("hotels", ["x (operator)"], [SourceRead(name="RateHawk", read=1, of=9, link="https://x.test/a"), SourceRead(name="Arbitrip", read=1, of=100, link="https://x.test/b")], [], [rh, ab], {}, None, True, "")
    a = out["answer"]
    assert out["ok"] and "| Best fit | RateHawk: RH hotel" in a and "| Recommended | RateHawk: RH hotel" in a and "| RateHawk | RH hotel |" in a and "| Arbitrip | AB hotel |" in a
    assert "comparison only" in a


def _rooms(rows, **head):
    base = {"ok": True, "hotel": "Hotel Principe Real", "hotel_path": "/hotel/hotel-principe-real/5ab3", "stars": 4, "score": "8.6", "reviews": "824", "distance": "0.9 km from center", "price_order": "ascending",
            "cols": ["room", "cancellation", "price", "per_night"], "common": {"meal": "Breakfast Included"}, "path_base": "", "run": "r", "part": 1, "parts": 1, "rows_read": len(rows), "rows": rows}
    base.update(head)
    return seal(json.dumps(base))


def test_arbitrip_rooms_confirm_free_cancellation_and_say_what_the_cheapest_room_is():
    from myt_mcp.sites import convert_all

    rooms = _rooms([["Run Of The House", "Non refundable", 135, 67], ["Run Of The House", "Free cancellation before Apr 24, 2027 11:59 PM (GMT)", 279, 139],
                    ["Deluxe Room", "Free cancellation before Apr 24, 2027 11:59 PM (GMT)", 294, 147]])
    wishes = {"breakfast": True, "free_cancellation": True, "stars_min": 4, "max_distance_km": 3, "arbitrip_link_query": "place_id=P&check_in=270503&check_out=270505&guests=2&rooms=1&contract_id=C"}
    offers, sources, problems, _, notes = convert_all([{"site": "arbitrip_rooms", "result": rooms, "url": "u"}], wishes)
    assert not problems and len(offers) == 1
    o = offers[0]
    assert o.price_total == 279 and o.fits is True and o.flexible is True and o.quotable is True and o.name == "Hotel Principe Real - Run Of The House"
    assert o.details["cancellation"].startswith("Free cancellation before Apr 24, 2027") and o.link == "https://app.arbitrip.com/hotel/hotel-principe-real/5ab3?" + wishes["arbitrip_link_query"]
    assert any("cheapest room overall is 135" in n and "Non refundable" in n for n in notes)
    assert o.source == "Arbitrip hotel page" and sources[0].name == "Arbitrip hotel page" and (sources[0].read, sources[0].of) == (3, 3)
    none, _, _, _, notes2 = convert_all([{"site": "arbitrip_rooms", "result": _rooms([["Std", "Non refundable", 135, 67]]), "url": "u"}], {"free_cancellation": True})
    assert none == [] and any("none of its 1 rooms meets every wish" in n for n in notes2)
    assert any("script reported" in p for p in convert_all([{"site": "arbitrip_rooms", "result": json.dumps({"ok": False, "error": "dates"}), "url": "u"}], None)[2])


@pytest.mark.anyio
async def test_arbitrip_tools_exist_and_the_rooms_script_checks_the_dates(monkeypatch):
    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    monkeypatch.setenv("ARBITRIP_CONTRACT_ID", "CONTRACT")
    async with Client(create_server(Settings())) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"arbitrip_hotels_recipe", "arbitrip_rooms_recipe"} <= names
        asked = (await c.call_tool("arbitrip_hotels_recipe", {"city": "lisbon", "check_in": "2027-05-03", "check_out": "2027-05-05"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 3
        r = (await c.call_tool("arbitrip_hotels_recipe", {"city": "Lisbon", "check_in": "2027-05-03", "check_out": "2027-05-05", "stars": 4, "breakfast": True, "operator_answered": True, "offset": 30})).structured_content
        assert "contract_id=CONTRACT" in r["url"] and "const SKIP = 30;" in r["script"] and "const LIMIT = 30;" in r["script"] and "offset=60" in r["more"]
        rooms = (await c.call_tool("arbitrip_rooms_recipe", {"city": "lisbon", "check_in": "2027-05-03", "check_out": "2027-05-05"})).structured_content
        assert '"check_in": "270503"' in rooms["script"] and rooms["link_query"].endswith("contract_id=CONTRACT") and "place_id=ChIJ" in rooms["link_query"]


def test_ratehawk_hotels_refuses_a_list_of_another_search_or_one_still_running():
    from myt_mcp.sites import convert_all
    row = _rh_row("H1", 4, 1.0, 8.0, 100, "Double room", ["breakfast"], "2027-05-01T00:00:00Z", 300, "/hotel/p/c/mid1/h1/")
    filters = {"stars": [40, 50], "free_cancellation": True, "meals": ["breakfast"]}
    expect = {"check_in": "2027-05-03", "check_out": "2027-05-05", "adults": 2, "children_ages": [], "residency": "en-il", "sort": "price_asc", "nights": 2, "filters": filters}
    def result(**extra):
        d = dict(SAMPLE_RH, filters=filters, results_total=57, page_header_count=57, rows=[row], rows_read=1)
        d.update(extra)
        return json.dumps(d)
    wishes = {"breakfast": True, "free_cancellation": True, "expect": expect}
    run = lambda text, w=wishes: convert_all([{"site": "ratehawk_hotels", "result": text, "url": "u"}], w)[2]
    assert run(result()) == []
    assert any("filters" in p and "not" in p for p in run(result(filters={"stars": [40, 50]})))            # the search was sent with other filters than the recipe asked for
    assert any("check_in 2027-06-01, not 2027-05-03" in p for p in run(result(check_in="2027-06-01")))
    assert any("adults 3, not 2" in p for p in run(result(adults=3)))
    assert any("children_ages [6], not []" in p for p in run(result(child_ages=[6])))
    assert any("had not finished" in p for p in run(result(search_finished=False)))
    assert any("header says 99 options and the search service 57" in p for p in run(result(page_header_count=99)))
    assert any("1 RateHawk hotel(s) came without a rate" in p for p in run(result(unparsed=1)))
    assert any("sort price_desc, not price_asc" in p for p in run(result(sort="price_desc")))


def _cars(rows, **head):
    base = {"ok": True, "search": {"route": "965846144,965846144", "date": "2027-04-12T10:00,2027-04-17T10:00", "age": "26,69", "residency": "il"}, "filters": {}, "offset": 0, "search_total": 90, "reached_cap": False, "rows": rows}
    base.update(head)
    return json.dumps(base)


def _car(name, price, seats="5", gearbox="Manual", company="greenmotion"):
    return _car_row(name, "MDMR", "mini", gearbox.lower(), int(seats), 1, 2, company, price, cdw=1100, deposit=1200)


def test_ratehawk_cars_ask_first_wishes_and_the_search_is_checked():
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ratehawk_cars import cars_ask_gate, ratehawk_cars_recipe
    asked = cars_ask_gate(None, None, None, None, False)
    assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 4
    assert len(cars_ask_gate("automatic", None, None, None, False)["ask_operator"]) == 3 and cars_ask_gate(None, None, None, None, True) is None
    r = ratehawk_cars_recipe("Faro Airport", None, "2027-04-12", "10:00", "2027-04-17", "10:00", None, None, "26,69", "il", True, False, False, 40, False, 30, 30)
    assert "const SKIP = 30;" in r["script"] and "const MAX_CARS = 60;" in r["script"] and r["filters_to_tick"] == ["Automatic"] and 'const FILTERS = ["Automatic"];' in r["script"]
    assert r["expect"] == {"route": "965846144,965846144", "date": "2027-04-12T10:00,2027-04-17T10:00", "age": "26,69", "residency": "il", "filters": {"vehicle_transmission_type": ["automatic"]},
                           "pickup_at": "2027-04-12T10:00:00Z", "dropoff_at": "2027-04-17T10:00:00Z"} and "getFilteredOffers" in r["script"] and "zenpagination" not in r["script"]
    rows = [_car("Fiat Panda", 60, "4", "Manual"), _car("Opel Corsa", 62, "5", "Automatic"), _car("Jeep", 90, "5", "Automatic")]
    wishes = {"automatic": True, "min_seats": 5, "max_total": 80}
    offers, _, problems, _, notes = convert_all([{"site": "ratehawk_cars", "result": _cars(rows), "url": "u"}], wishes)
    assert not problems and [o.fits for o in offers] == [False, True, False]            # manual, too few seats, over budget
    manual, _, _, _, _ = convert_all([{"site": "ratehawk_cars", "result": _cars(rows), "url": "u"}], {"manual": True})
    assert [o.fits for o in manual] == [True, False, False]
    exp = dict(r["expect"], filters={})
    run = lambda text, e=exp: convert_all([{"site": "ratehawk_cars", "result": text, "url": "u"}], {"expect": e})[2]
    assert run(_cars(rows)) == []
    assert any("filters" in p and "vehicle_transmission_type" in p for p in run(_cars(rows, filters={"vehicle_transmission_type": ["automatic"]})))      # sent with a filter nobody asked for
    assert any("residency 'us', not 'il'" in p for p in run(_cars(rows, search={"route": exp["route"], "date": exp["date"], "age": "26,69", "residency": "us"})))
    assert any("route '1,2', not '965846144,965846144'" in p for p in run(_cars(rows, search={"route": "1,2", "date": exp["date"], "age": "26,69", "residency": "il"})))
    late = [dict(rows[0], pickup=dict(rows[0]["pickup"], at="2027-04-12T12:00:00Z"))]
    assert any("for pick-up 2027-04-12T12:00:00Z, not 2027-04-12T10:00:00Z" in p for p in run(_cars(late)))
    mixed = [_car("A", 90), _car("B", 60), _car("C", 80)]
    assert any("not in one order" in p for p in run(_cars(mixed)))
    later = _cars(rows, offset=30)
    assert any("cars 31 to 33" in n and "not the cheapest overall" in n for n in convert_all([{"site": "ratehawk_cars", "result": later, "url": "u"}], None)[4])
    capped = convert_all([{"site": "ratehawk_cars", "result": _cars(rows, reached_cap=True, filters={"vehicle_transmission_type": ["automatic"]}), "url": "u"}], None)
    assert any("more exist" in n and "RateHawk lists" not in n for n in capped[4])         # with a filter RateHawk's count (the whole search) is not quoted


def _transfers(rows, **head):
    base = {"ok": True, "form": {"from": "Leonardo da Vinci Rome Fiumicino Airport (FCO)", "to": "Room Mate Collection Mia, Rome Colosseum", "when": "1 Mar, Mon, 16:30", "passengers": "2 adults, 1 child"},
            "page_ticked": [], "bags_range": {"from": 2, "to": 16}, "seats_range": {"from": 3, "to": 16}, "rows_read": len(rows), "sort_tab": "Cheapest", "price_order": "ascending", "rows": rows}
    base.update(head)
    return json.dumps(base)


def _tr(vehicle, price, passengers="3", bags="2", tracking=True):
    return {"vehicle": vehicle, "vehicle_class": "Standard", "passengers": passengers, "bags": bags, "waiting": "60 min waiting time", "meeting": "Meeting inside", "flight_tracking": tracking,
            "cancellation": "Free cancellation", "price": price, "currency": "EUR", "child_seat": None}


def test_ratehawk_transfers_ask_first_wishes_tab_and_hidden_filters():
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ratehawk_transfers import ratehawk_transfers_recipe, transfers_ask_gate
    asked = transfers_ask_gate(None, None, None, None, False)
    assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 4 and transfers_ask_gate(None, None, None, None, True) is None
    assert len(transfers_ask_gate(2, True, "cheapest", None, False)["ask_operator"]) == 1
    exp = ratehawk_transfers_recipe("Fiumicino", "Room Mate", "2027-03-01", "16:30", 2, [6], "Comfortable")["expect"]
    assert exp["sort_tab"] == "Comfortable" and exp["children"] == 1
    rows = [_tr("Sedan", 40, "3", "2", True), _tr("Minivan", 60, "6", "4", True), _tr("Sedan B", 38, "3", "1", False)]
    wishes = {"expect": {k: v for k, v in exp.items() if k != "sort_tab"}, "min_bags": 2, "flight_tracking": True, "max_total": 50}
    wishes["expect"].update({"pickup": "Leonardo da Vinci Rome Fiumicino Airport", "dropoff": "Room Mate Collection Mia", "adults": 2, "children": 1})
    offers, _, problems, _, _ = convert_all([{"site": "ratehawk_transfers", "result": _transfers(rows), "url": "u"}], wishes)
    assert not problems and [o.fits for o in offers] == [True, False, False]            # fits; over budget; too few bags and no flight tracking
    tab = convert_all([{"site": "ratehawk_transfers", "result": _transfers(rows), "url": "u"}], {"expect": {"sort_tab": "Comfortable"}})[2]
    assert any("'Cheapest' tab, not 'Comfortable'" in p for p in tab)
    sticky = convert_all([{"site": "ratehawk_transfers", "result": _transfers(rows, page_ticked=["With flight tracking"]), "url": "u"}], {"expect": {}})[2]
    assert any("did not ask for (With flight tracking)" in p for p in sticky)
    wanted = convert_all([{"site": "ratehawk_transfers", "result": _transfers(rows, page_ticked=["With flight tracking"]), "url": "u"}], {"expect": {}, "flight_tracking": True})[2]
    assert wanted == []


def _air(rows, **head):
    base = {"ok": True, "page_ticked": ["One way", "Economy", "All flights"], "settled": True, "cards_read": len(rows), "lowest_fare_order": "ascending", "rows": rows}
    base.update(head)
    return seal(json.dumps(base))


def _card(carrier="Air France", fares=None, stops="1 stop", date_text="Mar 6, Sat", route="Firenze-Peretola Airport FLR \u2192 Humberto Delgado Airport LIS"):
    return {"carrier": carrier, "issuing": "15 hours for issuing", "date": date_text, "route": route,
            "itineraries": [{"d": "06:50", "a": "11:25", "n": None, "t": "5 h 35 min", "s": stops, "l": "55 min, Paris" if stops != "Direct flight" else None, "f": ["AF-1267", "AF-1024"]},
                            {"d": "09:55", "a": "15:10", "n": "+1", "t": "9 h", "s": stops, "l": "4 h, Paris", "f": ["AF-1067", "AF-1624"]}],
            "fares": fares or [{"name": "Basic", "price": 399.88, "currency": "EUR", "bags": []}, {"name": "Standard", "price": 525.88, "currency": "EUR", "bags": [23, 12]}]}


def test_ratehawk_air_asks_first_has_filters_in_the_address_and_checks_the_page():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ratehawk_air import air_url, ratehawk_air_recipe
    url = air_url("FLR", "LIS", date(2027, 3, 6), 2, 1, 0, "economy", "direct", True, True)
    assert url == "https://www.ratehawk.com/air/?route=FLRa06032027LISa&adt=2&tns=0&chd=1&inf=0&class=economy&stops=direct&baggageIncluded=on&withoutAirportChange=on"
    assert "stops=" not in air_url("FLR", "LIS", date(2027, 3, 6), 2, 0, 0, "business", "any", False, False)
    with pytest.raises(ValueError, match="IATA"):
        ratehawk_air_recipe("Florence", "LIS", date(2027, 3, 6))
    exp = ratehawk_air_recipe("flr", "lis", date(2027, 3, 6), 2, 1, 0, "economy", "any", False, False)["expect"]
    run = lambda text, e=exp: convert_all([{"site": "ratehawk_air", "result": text, "url": "u"}], {"expect": e})
    offers, sources, problems, _, _ = run(_air([_card()]))
    assert not problems and len(offers) == 2 and offers[0].group == "FLR to LIS, 06 Mar 2027" and (sources[0].read, sources[0].of) == (1, 1)
    assert offers[0].details["per_person"].startswith("133.29") and "(+1 other times)" in offers[0].name and offers[0].details["checked_bag"].startswith("not shown")
    assert offers[1].details["checked_bag"] == "23 kg checked bag included" and offers[0].details["stops"].startswith("1 stop")
    assert any("not LIS" in p or "not FLR to LIS" in p for p in run(_air([_card(route="Rome Airport FCO \u2192 Lisbon LIS")]))[2])
    assert any("not 2027-03-06" in p for p in run(_air([_card(date_text="Mar 7, Sun")]))[2])
    assert any("filters are not as asked" in p and "Direct flight" in p for p in run(_air([_card()], page_ticked=["One way", "Economy", "Direct flight"]))[2])
    assert any("still adding flights" in p for p in run(_air([_card()], settled=False))[2])
    bag = ratehawk_air_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1, 0, "economy", "any", True, False)["expect"]
    got = convert_all([{"site": "ratehawk_air", "result": _air([_card()], page_ticked=["One way", "Economy", "All flights", "Checked baggage"]), "url": "u"}], {"expect": bag})[0]
    assert [o.fits for o in got] == [None, True]            # a tier whose bag is not shown is unknown, never a pick


@pytest.mark.anyio
async def test_ratehawk_air_tool_asks_first():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("ratehawk_air_recipe", {"origin": "FLR", "destination": "LIS", "day": "2027-03-06"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 3
        r = (await c.call_tool("ratehawk_air_recipe", {"origin": "FLR", "destination": "LIS", "day": "2027-03-06", "stops": "direct", "checked_bag": True, "cabin": "economy"})).structured_content
        assert "stops=direct" in r["url"] and "baggageIncluded=on" in r["url"] and r["wishes"]["expect"]["stops"] == "direct" and any("Direct flight" in f for f in r["filters_used"])


def test_air_cards_are_counted_once_across_parts():
    from myt_mcp.sites import convert_all
    a, b = _air([_card()], cards_read=2, run="r", part=1, parts=2, rows_read=2), _air([_card(carrier="KLM")], cards_read=2, run="r", part=2, parts=2, rows_read=2)
    _, sources, problems, _, _ = convert_all([{"site": "ratehawk_air", "result": a, "url": "u"}, {"site": "ratehawk_air", "result": b, "url": "u"}], {})
    assert not problems and (sources[0].read, sources[0].of) == (2, 2)


def _trains(rows, **head):
    base = {"ok": True, "search": {"from": "8306421", "to": "8308409", "date": "2026-11-23", "time": "08:00", "adt": "2"}, "filters": {"changes": None, "class": None}, "offset": 0, "loaded": len(rows), "matching": len(rows),
            "all_loaded": True, "rows": rows}
    base.update(head)
    return json.dumps(base)


def _train(no="9511", dep="08:14", arr="09:49", changes=0, classes=None, frm="Firenze S.M. Novella", to="Roma Termini", day="2026-11-23", brand="TRENITALIA_FRECCIAROSSA", minutes=95):
    mid = "Bologna Centrale"
    legs = ([{"from": frm, "to": to, "dep": f"{day}T{dep}:00", "arr": f"{day}T{arr}:00", "train": no, "brand": brand, "operator": "Trenitalia"}] if changes == 0 else
            [{"from": frm, "to": mid, "dep": f"{day}T{dep}:00", "arr": f"{day}T10:00:00", "train": no, "brand": brand, "operator": "Trenitalia"}, {"from": mid, "to": to, "dep": f"{day}T10:20:00", "arr": f"{day}T{arr}:00", "train": "8001", "brand": brand, "operator": "Trenitalia"}])
    return {"rank": 1, "id": f"id-{no}", "supplier": "rail_europe", "legs": legs, "dep": legs[0]["dep"], "arr": legs[-1]["arr"], "minutes": minutes, "changes": changes, "cur": "EUR", "services": ["wifi", "air_conditioning"], "seat_reservation": False,
            "classes": classes or [{"id": "standard", "from": 61.38, "to": 110}, {"id": "comfort", "from": 52.58, "to": 132}, {"id": "premier", "from": 61.38, "to": 319}]}


def test_ratehawk_trains_ask_first_station_ids_filters_and_checks():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ratehawk_trains import ratehawk_trains_recipe
    r = ratehawk_trains_recipe("Firenze Santa Maria Novella", "Roma Termini", date(2026, 11, 23), "08:00", 2, "direct", "comfort", limit=30, offset=30)
    assert r["url"] == "https://www.ratehawk.com/railway/?from=8306421&to=8308409&date=2026-11-23&time=08%3A00&adt=2"
    assert 'const CHANGES = "Direct route"' in r["script"] and 'const CLASS = "Comfort"' in r["script"] and "const SKIP = 30;" in r["script"] and "const LIMIT = 30;" in r["script"]
    assert ratehawk_trains_recipe("Atlantis", "Roma Termini", date(2026, 11, 23), "08:00")["needs_station_id"] == "Atlantis"
    gone = ratehawk_trains_recipe("Lisboa Oriente", "Porto Campanhã", date(2026, 11, 12), "08:00")
    assert gone["not_served"] == "Lisboa Oriente" and "route not served" in gone["next"] and "url" not in gone
    assert "not_served" not in ratehawk_trains_recipe("Porto Campanhã", "Roma Termini", date(2026, 11, 12), "08:00")
    with pytest.raises(ValueError, match="HH:MM"):
        ratehawk_trains_recipe("Roma Termini", "Napoli", date(2026, 11, 23), "8am")
    exp = ratehawk_trains_recipe("Firenze Santa Maria Novella", "Roma Termini", date(2026, 11, 23), "08:00", 2)["expect"]
    assert exp["from_id"] == "8306421" and exp["to_id"] == "8308409" and exp["time"] == "08:00" and '"one_way"' in r["script"] and "zenpagination" not in r["script"] and "Select fare" not in r["script"]
    run = lambda text, w=None: convert_all([{"site": "ratehawk_trains", "result": text, "url": "u"}], w if w is not None else {"expect": exp})
    offers, sources, problems, _, notes = run(_trains([_train(), _train("8505", "08:33", "10:15", minutes=102)]))
    assert not problems and len(offers) == 6 and offers[0].group == "Firenze Santa Maria Novella to Roma Termini, 23 Nov 2026" and (sources[0].read, sources[0].of) == (2, 2)
    assert offers[0].price_total == 61.38 and offers[0].details["class_fare"] == "Standard from 61.38 EUR (up to 110 EUR for the dearest fare of the class)" and "whole group" in offers[0].price_basis and any("loaded 2 trains" in n for n in notes)
    assert offers[0].name == "Trenitalia Frecciarossa 9511 08:14-09:49 (1 h 35 min) Standard" and offers[0].details["changes"] == "Direct" and offers[0].details["services"] == "wifi, air conditioning"
    assert any("not Firenze Santa Maria Novella to Roma Termini" in p for p in run(_trains([_train(frm="Milano Centrale", to="Venezia S. Lucia")]))[2])
    assert any("leaves on 2026-11-24, not 2026-11-23" in p for p in run(_trains([_train(day="2026-11-24")]))[2])
    assert any("filters were" in p and "Direct route" in p for p in run(_trains([_train()], filters={"changes": "Direct route", "class": None}))[2])
    assert any("date '2026-11-24', not '2026-11-23'" in p for p in run(_trains([_train()], search={"from": "8306421", "to": "8308409", "date": "2026-11-24", "time": "08:00", "adt": "2"}))[2])
    assert any("adt '3', not '2'" in p for p in run(_trains([_train()], search={"from": "8306421", "to": "8308409", "date": "2026-11-23", "time": "08:00", "adt": "3"}))[2])
    comfort = dict(exp, **{"class": "comfort", "changes": "direct"})
    got = run(_trains([_train(), _train("8999", changes=1)], filters={"changes": "Direct route", "class": "Comfort"}), {"expect": comfort, "max_total": 60})
    assert not got[2] and [o.fits for o in got[0]] == [True, False] and all(o.details["class_fare"].startswith("Comfort") for o in got[0])
    assert got[0][1].details["changes"] == "1 change of train, via Bologna Centrale" and "8999 + 8001" in got[0][1].name
    more = run(_trains([_train()], loaded=15, matching=15, all_loaded=False))
    assert more[4] and any("more exist on the page than were loaded" in n for n in more[4])


@pytest.mark.anyio
async def test_ratehawk_trains_tool_asks_first():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        base = {"origin": "Firenze Santa Maria Novella", "destination": "Roma Termini", "day": "2026-11-23", "time": "08:00"}
        asked = (await c.call_tool("ratehawk_trains_recipe", base)).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 3
        r = (await c.call_tool("ratehawk_trains_recipe", {**base, "changes": "direct", "train_class": "comfort", "max_total": 120})).structured_content
        assert "railway/?from=8306421" in r["url"] and r["wishes"]["max_total"] == 120 and any("Direct route" in f for f in r["filters_used"]) and "offset=30" in r["more"]


def _sky(rows, **head):
    base = {"ok": True, "route": ["FLR", "LIS"], "date": "2027-03-06", "adults": 2, "children_ages": [6], "cabin": "economy", "currency": "EUR", "direct_only": False, "results_total": 97, "matching_total": 97, "offset": 0,
            "sorts": [{"sort": "Best", "read": 2}, {"sort": "Cheapest", "read": 2}], "status": "complete", "polls": 2, "unparsed": 0, "rows": rows}
    base.update(head)
    return json.dumps(base)


def _sk(sort, rank, mk, dep, arr, total, direct=False, plus=0, via=None, mins=485, op=None, **extra):
    row = {"sort": sort, "rank": rank, "id": f"{mk}-{dep}-{arr}", "total": total, "stops": 0 if direct else 1, "mins": mins, "dep": f"2027-03-06T{dep}:00", "arr": f"2027-03-06T{arr}:00", "plus": plus, "mk": [mk], "op": op or [mk],
           "flights": ["VY 6075"], "via": [] if direct else (via or [{"code": "BCN", "name": "Barcelona"}]), "layover": 0 if direct else 55, "self_transfer": False, "protected": False, "tags": [], "em_kg": 188.9, "em_level": "typical",
           "sellers": [{"n": mk, "a": True, "p": total}, {"n": "Booking.com", "a": False, "p": round(total + 6.4, 2)}], "seller_count": 2, "airline_price": total}
    row.update(extra)
    return row


def test_skyscanner_asks_first_has_the_url_and_its_rows_are_comparison_only():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.skyscanner import skyscanner_recipe
    r = skyscanner_recipe("FLR", "LIS", date(2027, 3, 6), 2, [6, 8], "economy", True, 20)
    assert r["url"] == "https://www.skyscanner.net/transport/flights/flr/lis/270306/?adultsv2=2&childrenv2=6%7C8&cabinclass=economy&rtn=0&preferdirects=true&currency=EUR"
    assert 'const SORTS = ["Best", "Cheapest"];' in r["script"] and "const LIMIT = 20;" in r["script"] and "const DIRECT = true;" in r["script"] and r["expect"]["leg"] == "FLR to LIS, 06 Mar 2027"
    assert "const DIRECT = false;" in skyscanner_recipe("FLR", "LIS", date(2027, 3, 6))["script"] and r["expect"]["children_ages"] == [6, 8]
    with pytest.raises(ValueError, match="IATA"):
        skyscanner_recipe("Florence", "LIS", date(2027, 3, 6))
    exp = skyscanner_recipe("FLR", "LIS", date(2027, 3, 6), 2, [6])["expect"]
    run = lambda text, e=exp: convert_all([{"site": "skyscanner", "result": text, "url": "u"}], {"expect": e})
    rows = [_sk("Best", 1, "TAP Air Portugal", "12:20", "14:30", 325.34, direct=True, mins=190, op=["Portugalia Airlines"]), _sk("Best", 2, "Vueling Airlines", "13:10", "16:55", 215.68),
            _sk("Cheapest", 1, "Vueling Airlines", "21:00", "08:30", 146.0, plus=1, mins=690, self_transfer=True), _sk("Cheapest", 2, "Vueling Airlines", "13:10", "16:55", 215.68)]
    offers, sources, problems, _, notes = run(_sky(rows))
    assert not problems and len(offers) == 3 and all(o.quotable is False and o.group == "FLR to LIS, 06 Mar 2027" for o in offers)         # the same ticket in both lists is one offer
    assert offers[0].name == "TAP Air Portugal (operated by Portugalia Airlines) 12:20-14:30 (3 h 10 min)" and offers[0].price_total == 325.34 and offers[0].details["stops"] == "Direct flight"
    assert offers[0].details["per_person"].startswith("108.45 EUR") and offers[0].details["flights"] == "VY 6075" and "(airline) 325.34 EUR" in offers[0].details["sold_by"] and "325.34 EUR for the whole group" in offers[0].details["airline_price"]
    assert "(+1 day)" in offers[2].name and offers[2].details["self_transfer"].startswith("yes: separate tickets, NOT protected")
    assert offers[1].details["stops"] == "1 stop via Barcelona (BCN), 55 min in total on the ground" and offers[1].details["self_transfer"] == "no" and offers[1].details["emissions"] == "189 kg CO2e (typical)" and offers[0].details["fare"].startswith("not shown")
    assert any("only compares" in n for n in notes) and any(n.startswith("FLR to LIS, 06 Mar 2027: Skyscanner lists 97 tickets for this search") for n in notes)     # counts name their leg
    assert any("not FLR to LIS" in p for p in run(_sky(rows, route=["FCO", "LIS"]))[2])
    assert any("not 2027-03-06" in p for p in run(_sky(rows, date="2027-03-07"))[2])
    assert any("1 adult(s), not 2" in p for p in run(_sky(rows, adults=1))[2])
    assert any("children aged [6, 9], not [6]" in p for p in run(_sky(rows, children_ages=[6, 9]))[2])
    assert any("cabin 'Business'" in p for p in run(_sky(rows, cabin="business"))[2])
    assert any("stop filter" in p for p in run(_sky(rows, direct_only=True))[2])
    assert any("1 Skyscanner ticket(s) came without a price" in p for p in run(_sky(rows, unparsed=1))[2])
    assert any("not EUR" in p for p in run(_sky(rows, currency="GBP"))[2])
    assert any("both the Best and the Cheapest" in p for p in run(_sky(rows, sorts=[{"sort": "Best", "read": 2}]))[2])
    assert any("human check" in p for p in run(json.dumps({"ok": False, "error": "Skyscanner shows a human check (captcha). Stop"}))[2])


@pytest.mark.anyio
async def test_skyscanner_tool_asks_first():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("skyscanner_recipe", {"origin": "FLR", "destination": "LIS", "day": "2027-03-06"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 2
        r = (await c.call_tool("skyscanner_recipe", {"origin": "FLR", "destination": "LIS", "day": "2027-03-06", "direct_only": False, "cabin": "economy", "children_ages": [6]})).structured_content
        assert "childrenv2=6" in r["url"] and r["wishes"]["expect"]["children"] == 1 and any("Best and Cheapest" in f for f in r["filters_used"])


def _elal(rows, **head):
    base = {"ok": True, "route": ["TLV", "LIS"], "trip": "One way", "day": "2027-03-01", "pax": 3, "settled": True, "english": True, "rows": rows}
    base.update(head)
    return json.dumps(base)


def _el(dep="13:40", arr="17:50", stops="Non-stop", eco=432, biz=1146, left=2, prem=None, flights=("LY375",)):
    f = lambda p, left=None, lowest=False: {"price": p, "currency": "USD", "lowest": lowest, "left": left} if p else None
    return {"dep": dep, "arr": arr, "from": "TLV", "to": "LIS", "stops": stops, "duration": "06h 10m", "flights": list(flights), "operated": True, "eco": f(eco, None, True), "prem": f(prem), "biz": f(biz, left)}


def test_elal_asks_first_gives_the_steps_and_checks_what_the_page_searched():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.elal import elal_recipe
    r = elal_recipe("tlv", "lis", date(2027, 3, 1), 2, 1, 0, 0, "any", False)
    assert r["url"].endswith("lang=en") and r["expect"]["pax"] == 3 and r["expect"]["leg"] == "TLV to LIS, 01 Mar 2027" and any("Modify" in s for s in r["steps"]) and any("Done" in s for s in r["steps"]) and any("No matching city/airport" in s for s in r["steps"]) and "const" in r["script"]
    with pytest.raises(ValueError, match="IATA"):
        elal_recipe("Tel Aviv", "LIS", date(2027, 3, 1))
    with pytest.raises(ValueError, match="infants"):
        elal_recipe("TLV", "LIS", date(2027, 3, 1), 1, 0, 0, 2)
    exp = r["expect"]
    run = lambda text, e=exp: convert_all([{"site": "elal", "result": text, "url": "u"}], {"expect": e})
    offers, sources, problems, _, notes = run(_elal([_el()]))
    assert not problems and len(offers) == 2 and (sources[0].read, sources[0].of) == (1, 1) and all(o.quotable for o in offers)
    assert offers[0].price_total == 1296 and offers[0].currency == "USD" and "432 USD per passenger x 3" in offers[0].price_basis and offers[0].details["per_person"].startswith("432 USD")
    assert offers[0].details["fare"].startswith("ECONOMY (lowest") and offers[1].details["seats_left"] == "2 left at this price" and offers[0].group == "TLV to LIS, 01 Mar 2027"
    assert any("not TLV to LIS" in p for p in run(_elal([_el()], route=["TLV", "FCO"]))[2])
    assert any("not 2027-03-01" in p for p in run(_elal([_el()], day="2027-03-02"))[2])
    assert any("1 passengers, not 3" in p for p in run(_elal([_el()], pax=1))[2])
    assert any("not 'One way'" in p for p in run(_elal([_el()], trip="Round trip"))[2])
    assert any("not in English" in p for p in run(_elal([_el()], english=False))[2])
    assert any("still adding" in p for p in run(_elal([_el()], settled=False))[2])
    biz = dict(exp, cabin="business")
    only = convert_all([{"site": "elal", "result": _elal([_el(prem=900)]), "url": "u"}], {"expect": biz})[0]
    assert [o.details["fare"] for o in only] == ["BUSINESS"]
    stop = dict(exp, direct_only=True)
    got = convert_all([{"site": "elal", "result": _elal([_el(), _el(dep="06:00", stops="1 stop")]), "url": "u"}], {"expect": stop})[0]
    assert [o.fits for o in got] == [True, True, False, False]


@pytest.mark.anyio
async def test_elal_tool_asks_first():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("elal_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-03-01"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 2
        r = (await c.call_tool("elal_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-03-01", "direct_only": True, "cabin": "economy", "adults": 2, "children": 1})).structured_content
        assert r["wishes"]["expect"]["pax"] == 3 and r["wishes"]["expect"]["direct_only"] is True and any("Direct flights only" in f for f in r["filters_used"]) and r["steps"]


def _ofr(rows, **head):
    base = {"ok": True, "form": {"pickup_place": "Faro Airport (FAO)", "pickup_when": "23.11.26 | 10:00", "dropoff_place": "Faro Airport (FAO)", "dropoff_when": "28.11.26 | 10:00", "age": None},
            "other_places": [], "logged_in": True, "cars_total": 66, "offset": 0, "ms": 3700, "settled": True, "rows": rows}
    base.update(head)
    return json.dumps(base)


def _of(car="Fiat 500", price="88.07", before="111.44", adults="2", kids="1", acriss="MBMR", package="תכנית ביטול השתתפות עצמית", cdw="0.00", station="Airport", supplier="Tangerine Portugal", **more):
    row = {"supplier": supplier, "supplier_score": "8.80", "size": "Small", "acriss": acriss, "car": car, "seats": adults, "kids": kids, "doors": "2/4", "suitcases": "1", "handbags": "0", "station_type": station, "price": price, "price_before": before,
           "currency": "EUR", "package": package, "live_rate": True, "cdw_excess": cdw, "theft_excess": cdw, "deposit": "700.00", "excess_currency": "EUR", "one_way_fee": None, "extras": [{"name": "Ofran Plus II", "price": "28.00", "currency": "EUR"}]}
    row.update(more)
    return row


def test_ofran_asks_first_gives_the_steps_and_checks_what_the_script_searched():
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ofran import ofran_recipe
    r = ofran_recipe("Faro Airport", "2026-11-23", "10:00", "2026-11-28", "10:00", 30, 30)
    assert '"skip": 30' in r["script"] and '"limit": 30' in r["script"] and '"pickup": "Faro Airport"' in r["script"] and "__REQUEST__" not in r["script"] and r["url"] == "https://ofran.co.il/"
    assert any("no form to fill" in s.lower() or "There is no form to fill" in s for s in r["steps"]) and not any("calendar" in s for s in r["steps"])
    with pytest.raises(ValueError, match="HH:MM"):
        ofran_recipe("Faro Airport", "2026-11-23", "ten", "2026-11-28", "10:00")
    for age in (20, 86):
        with pytest.raises(ValueError, match="21-85"):
            ofran_recipe("Faro Airport", "2026-11-23", "10:00", "2026-11-28", "10:00", driver_years=age)
    exp = ofran_recipe("Faro Airport", "2026-11-23", "10:00", "2026-11-28", "10:00")["expect"]
    run = lambda text, w=None: convert_all([{"site": "ofran", "result": text, "url": "u"}], w if w is not None else {"expect": exp})
    offers, sources, problems, _, notes = run(_ofr([_of(), _of("Opel Corsa", "89.26", "112.78", "3", "1", "EDAR", "תכנית בסיס", "700.00")]))
    assert not problems and len(offers) == 2 and (sources[0].read, sources[0].of) == (2, 66) and offers[0].group == "Cars"
    assert offers[0].price_total == 88.07 and "after the agent discount (list price 111.44)" in offers[0].price_basis and "5 days" in offers[0].price_basis and offers[0].supplier == "Tangerine Portugal"
    assert offers[0].details["gearbox"] == "Manual" and offers[0].details["excess"].startswith("excess cancelled") and offers[1].details["excess"] == "damage excess 700.00 EUR, theft excess 700.00 EUR"
    assert offers[1].details["gearbox"] == "Automatic" and offers[0].details["seats_bags"] == "3 seats (Ofran's recommended: 2 adults + 1 kids) / 1 suitcases + 0 handbags / 2/4 doors" and offers[0].details["deposit"] == "700.00 EUR"
    assert offers[0].details["optional_extras"] == "Ofran Plus II +28.00 EUR (not in the price)" and offers[1].details["plan"] == "תכנית בסיס" and offers[0].details["pickup_place"] == "Pick-up station inside the airport"
    form = lambda **k: {"pickup_place": "Faro Airport (FAO)", "pickup_when": "23.11.26 | 10:00", "dropoff_place": "Faro Airport (FAO)", "dropoff_when": "28.11.26 | 10:00", "age": None, **k}
    assert any("searched '23.11.26 | 11:00', not '23.11.26 | 10:00'" in p for p in run(_ofr([_of()], form=form(pickup_when="23.11.26 | 11:00")))[2])
    assert any("not 'Faro Airport'" in p for p in run(_ofr([_of()], form=form(pickup_place="Malaga Airport (AGP)")))[2])
    young = {"expect": dict(exp, driver_years=25)}
    assert any("driver age '30', not '25'" in p for p in run(_ofr([_of()], form=form(age="30")), young)[2]) and not run(_ofr([_of()], form=form(age="25")), young)[2]
    out_ = run(_ofr([_of()], logged_in=False, diag={"page": "https://ofran.co.il/", "title": "Ofran", "text_start": "התחברות הרשמה", "login_link": True}))
    assert out_[2] == [] and "PUBLIC price" in out_[0][0].price_basis and out_[0][0].quotable is False and run(_ofr([_of()]))[0][0].quotable is True        # read anyway: public prices, never quotable
    assert any("WITHOUT the agent login" in n and "PUBLIC prices" in n and "a login link is on it" in n and "https://ofran.co.il/" in n for n in out_[4])
    assert any("script reported: Ofran could not run this search" in p for p in run(json.dumps({"ok": False, "error": "Ofran could not run this search (its own message, the answer still said 200): [\"age\"]"}))[2])
    assert any("other Ofran places that also match: Faro City Center (FAOC)" in n for n in run(_ofr([_of()], other_places=[{"name": "Faro City Center", "code": "FAOC"}]))[4])
    rows = [_of("Fiat 500", "88.07", adults="2", kids="1", acriss="MBMR"), _of("Jeep", "150", "190", "4", "1", "CDAR"), _of("Kia", "95", "120", "4", "1", "CDAR", "תכנית בסיס", "700.00"), _of("Seat", "99", "120", "4", "1", "CDAR", station="City")]
    wish = {"expect": exp, "automatic": True, "min_seats": 5, "max_total": 120, "zero_excess": True, "inside_airport": True}
    got = convert_all([{"site": "ofran", "result": _ofr(rows), "url": "u"}], wish)[0]
    assert [o.fits for o in got] == [False, False, False, False]             # manual / too dear / base plan with 700 excess / not at the airport
    ok = convert_all([{"site": "ofran", "result": _ofr([_of("Jeep", "110", "150", "4", "1", "CDAR")]), "url": "u"}], wish)[0]
    assert [o.fits for o in ok] == [True] and ok[0].details["gearbox"] == "Automatic"
    outside = convert_all([{"site": "ofran", "result": _ofr([_of(station="City")]), "url": "u"}], {"expect": exp})[0][0]
    assert "outside the airport" in outside.details["pickup_place"] and "City" in outside.details["pickup_place"]
    plan_only = _of(package="תכנית ביטול השתתפות עצמית", cdw="300.00")      # the plan's name alone is not zero excess: the number must be 0 too
    assert convert_all([{"site": "ofran", "result": _ofr([plan_only]), "url": "u"}], {"expect": exp, "zero_excess": True})[0][0].fits is False


@pytest.mark.anyio
async def test_ofran_tool_asks_first():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        base = {"pickup": "Faro Airport", "pickup_date": "2026-11-23", "pickup_time": "10:00", "dropoff_date": "2026-11-28", "dropoff_time": "10:00"}
        asked = (await c.call_tool("ofran_recipe", base)).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 4
        r = (await c.call_tool("ofran_recipe", {**base, "gearbox": "automatic", "min_seats": 5, "zero_excess": True, "max_total": 300})).structured_content
        assert r["wishes"]["automatic"] is True and r["wishes"]["max_total"] == 300 and r["pickup_time"] == "10:00" and "offset=100" in r["more"] and '"limit": 100' in r["script"] and '"skip": 0' in r["script"] and any("Excess" in f for f in r["filters_used"])


def test_place_matching_uses_the_distinctive_words_and_trains_keep_their_direction():
    from myt_mcp.sites import convert_all, place_matches
    assert place_matches("Faro Airport", "Portugal, Faro Airport") and not place_matches("Faro Airport", "Spain, Malaga Airport")
    assert place_matches("Leonardo da Vinci Rome Fiumicino Airport", "Rome Fiumicino Airport (FCO)") and not place_matches("Fiumicino Airport", "Ciampino Airport")
    assert place_matches("Airport", "anything") and place_matches("Roma Termini", "Roma Termini railway station") and not place_matches("Roma Termini", "Napoli Centrale")
    exp = {"origin": "Firenze Santa Maria Novella", "destination": "Roma Termini", "day": "2026-11-23", "adults": 2, "changes": "any", "class": None}
    back = convert_all([{"site": "ratehawk_trains", "result": _trains([_train(frm="Roma Termini", to="Firenze S.M. Novella")]), "url": "u"}], {"expect": exp})[2]
    assert any("not Firenze Santa Maria Novella to Roma Termini" in p for p in back)


def test_skyscanner_offset_window_and_the_direct_filter_is_checked():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.skyscanner import skyscanner_recipe
    r = skyscanner_recipe("FLR", "LIS", date(2027, 3, 6), 2, [6], "economy", False, 20, 20)
    assert "const SKIP = 20;" in r["script"] and "const LIMIT = 20;" in r["script"]
    exp = skyscanner_recipe("FLR", "LIS", date(2027, 3, 6), 2, [6])["expect"]
    rows = [_sk("Best", 21, "Vueling Airlines", "13:10", "16:55", 340.0), _sk("Cheapest", 21, "Vueling Airlines", "21:00", "08:30", 218.0, plus=1)]
    offers, _, problems, _, notes = convert_all([{"site": "skyscanner", "result": _sky(rows, offset=20), "url": "u"}], {"expect": exp})
    assert not problems and any("tickets 21 to 22" in n for n in notes)


def test_elal_selling_fast_label_is_kept_and_the_real_row_shapes_convert():
    from myt_mcp.sites import convert_all
    row = _el(dep="15:15", arr="19:25")
    row["selling_fast"] = True
    exp = {"origin": "TLV", "destination": "LIS", "day": "2027-03-01", "pax": 3, "cabin": "any", "direct_only": False, "leg": "TLV to LIS, 01 Mar 2027"}
    offers = convert_all([{"site": "elal", "result": _elal([row]), "url": "u"}], {"expect": exp})[0]
    assert "'Selling fast'" in offers[0].details["seats_left"]
    nostop = dict(_el(), stops=None, duration=None)
    odd = convert_all([{"site": "elal", "result": _elal([nostop]), "url": "u"}], {"expect": dict(exp, direct_only=True)})[0]
    assert odd[0].details["stops"] == "stops not shown" and odd[0].connecting is True and odd[0].fits is False          # an unreadable layout is never treated as non-stop


# ---------- TAP (recipe: the page's own availability answer, read from its session storage) ----------

def _tap(rows, **head):
    base = {"ok": True, "currency": "EUR", "pax": {"ADT": 2, "CHD": 1}, "not_available": False, "flights_total": 2, "offset": 0, "flights_in_part": 2, "page_direct": 1, "page_connecting": 1, "rows": rows}
    base.update(head)
    return json.dumps(base)


def _tp(fare="DISCNEW", total=434.38, adt=154.3, chd=125.78, bag=0, ref=0, fi=0, flights="TP875", dep="2027-03-06 12:20", arr="2027-03-06 14:30", stops=0, mins=190, via="", frm="FLR", cabin="Economy", seats=9):
    # the first five rows are the real fares of TP875 FLR-LIS 6 Mar 2027 for 2 adults + 1 child (22 Oct 2026)
    return {"fi": fi, "flights": flights, "op": "Portugália Airlines", "from": frm, "to": "LIS", "dep": dep, "arr": arr, "stops": stops, "mins": mins, "via": via, "fare": fare, "cabin": cabin,
            "total": total, "adt": adt, "chd": chd, "inf": None, "bag": bag, "ref": ref, "seats": seats}


TAP_REAL = [_tp(), _tp("CLANEW", 530.38, 189.3, 151.78, 1, 0, 1), _tp("PLUSNEW", 654.38, 234.3, 185.78, 1, 1, 2), _tp("EXENEW", 1407.38, 501.3, 404.78, 1, 0, 3, cabin="Executive", seats=7),
            _tp("TOPNEW", 1544.38, 551.3, 441.78, 1, 1, 4, cabin="Executive", seats=7)]
TAP_CONN = _tp("DISCNEW", 888.63, 318.12, 252.39, 0, 0, 0, "TP1234+TP827", "2027-03-06 06:25", "2027-03-06 14:30", 1, 545, "LIS")


def test_tap_recipe_builds_the_deeplink_the_script_and_what_to_expect():
    from datetime import date
    from myt_mcp.sites.tap import tap_recipe
    r = tap_recipe("flr", "lis", date(2027, 3, 6), 2, 1, 0, True, False, False, 12, 12)
    assert r["url"].startswith("https://booking.flytap.com/booking/flights/deeplink?") and "origin=FLR" in r["url"] and "destination=LIS" in r["url"] and "adt=2" in r["url"] and "chd=1" in r["url"] and "depDate=06.03.2027" in r["url"]
    assert "const LIMIT = 12; const SKIP = 12;" in r["script"] and "__LIMIT__" not in r["script"] and "airportTranslationData" in r["script"] and "window.__mytParts" in r["script"]
    assert "const window" not in r["script"] and r["expect"]["leg"] == "FLR to LIS, 06 Mar 2027" and r["expect"]["direct_only"] is True
    with pytest.raises(ValueError, match="IATA"):
        tap_recipe("Florence", "LIS", date(2027, 3, 6))
    with pytest.raises(ValueError, match="infants"):
        tap_recipe("FLR", "LIS", date(2027, 3, 6), 1, 0, 2)


def test_tap_converts_the_real_rows_counts_flights_once_and_keeps_bag_and_refund_per_fare():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.tap import tap_recipe
    exp = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1)["expect"]
    offers, sources, problems, _, notes = convert_all([{"site": "tap", "result": _tap(TAP_REAL + [TAP_CONN, dict(TAP_CONN, fare="CLANEW", fi=1, total=950.0, adt=340.0, chd=270.0, bag=1)]), "url": "u"}], {"expect": exp})
    assert not problems and len(offers) == 7 and (sources[0].read, sources[0].of) == (2, 2) and all(o.quotable and o.currency == "EUR" for o in offers)
    first = offers[0]
    assert first.price_total == 434.38 and first.group == "FLR to LIS, 06 Mar 2027" and first.source == "TAP Air Portugal" and not first.connecting and "3 seated travellers" in first.price_basis
    assert first.details["checked_bag"] == "no" and first.details["refund_change"].startswith("not refundable") and first.details["fare"] == "DISCNEW (Economy)" and "ADT 154.3 EUR" in first.details["per_person"]
    plus = offers[2]
    assert plus.details["checked_bag"] == "yes" and plus.details["refund_change"] == "refundable" and plus.flexible is True and plus.details["seats_left"] == 9
    assert offers[5].connecting is True and "1 stop via LIS" in offers[5].name and offers[0].name.startswith("TP875 12:20-14:30 operated by Portugália Airlines")


def test_tap_flights_of_two_legs_add_up_and_the_read_never_passes_the_total():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.tap import tap_recipe
    out = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1)["expect"]
    back = dict(out, leg="LIS to FLR, 13 Mar 2027")
    item = lambda e: {"site": "tap", "result": _tap(TAP_REAL + [TAP_CONN]), "url": "u", "wishes": {"expect": e}}
    one_leg = convert_all([item(out)], {})[1][0]
    two_legs = convert_all([item(out), item(back)], {})[1][0]
    assert (two_legs.read, two_legs.of) == (2 * one_leg.read, 2 * one_leg.of) and one_leg.read <= one_leg.of


def test_tap_wishes_decide_fits_and_every_refusal_is_reported():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.tap import tap_recipe
    exp = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1, 0, True, True, True)["expect"]
    got = convert_all([{"site": "tap", "result": _tap(TAP_REAL + [TAP_CONN]), "url": "u"}], {"expect": exp})[0]
    assert [o.fits for o in got] == [False, False, True, False, True, False]        # direct + checked bag + refundable: only PLUSNEW and TOPNEW of the direct flight
    exp = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1)["expect"]
    run = lambda text: convert_all([{"site": "tap", "result": text, "url": "u"}], {"expect": exp})[2]
    assert any("passengers {'ADT': 2}" in p for p in run(_tap(TAP_REAL, pax={"ADT": 2})))
    assert any("not on 2027-03-06" in p for p in run(_tap([_tp(dep="2027-03-07 12:20")])))
    assert any("ends at" in p for p in run(_tap([dict(_tp(), to="OPO")])))
    assert any("does not add up" in p for p in run(_tap([_tp(total=400.0)])))
    assert any("not EUR" in p for p in run(_tap(TAP_REAL, currency="USD")))
    assert any("direct and" in p and "run the script once more" in p for p in run(_tap(TAP_REAL + [TAP_CONN], page_direct=1, page_connecting=7)))
    assert any("TAP script reported" in p for p in run(json.dumps({"ok": False, "error": "no flights"})))
    assert any("not the script's JSON" in p for p in run("hello"))
    elsewhere = convert_all([{"site": "tap", "result": _tap(TAP_REAL + [_tp(frm="ZMS", flights="TP9XYZ")], flights_total=2, page_direct=None, page_connecting=None), "url": "u"}], {"expect": exp})
    assert len(elsewhere[0]) == 5 and any("another place than FLR" in n for n in elsewhere[4]) and not elsewhere[2]


def test_tap_cabin_wish_drops_the_fares_of_another_cabin_and_marks_a_fare_that_names_none():
    """28 Oct 2026: Economy was asked and TAP's Executive fare (TOPINT) was in the table as quotable, 'meets every wish'."""
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.tap import tap_recipe
    plain = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1)["expect"]
    assert plain["cabin"] is None
    eco = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1, cabin="Economy")["expect"]
    biz = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1, cabin="business")["expect"]
    assert eco["cabin"] == "economy" and biz["cabin"] == "executive"
    run = lambda exp, rows: convert_all([{"site": "tap", "result": _tap(rows), "url": "u"}], {"expect": exp})[0]
    assert [o.fits for o in run(plain, TAP_REAL)] == [True] * 5                                   # no cabin asked: nothing changes
    assert [o.fits for o in run(eco, TAP_REAL)] == [True, True, True, False, False]              # Economy: the two Executive fares are a clear miss
    assert [o.fits for o in run(biz, TAP_REAL)] == [False, False, False, True, True]
    unnamed = run(eco, [_tp(cabin=None)])[0]
    assert unnamed.fits is None and unnamed.unconfirmed == ["cabin"]                              # a fare that does not name its cabin is marked, never a pick
    with pytest.raises(ValueError):
        tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1, cabin="luxury")


def test_tap_parts_are_counted_once_per_flight_and_a_later_window_says_so():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.tap import tap_recipe
    exp = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1)["expect"]
    part_a = _tap(TAP_REAL[:3], flights_total=2, page_direct=None, page_connecting=None)          # TP875's fares continue in the next part
    part_b = _tap(TAP_REAL[3:] + [TAP_CONN], flights_total=2, page_direct=None, page_connecting=None)
    offers, sources, problems, _, _ = convert_all([{"site": "tap", "result": part_a, "url": "u"}, {"site": "tap", "result": part_b, "url": "u"}], {"expect": exp})
    assert not problems and len(offers) == 6 and (sources[0].read, sources[0].of) == (2, 2)
    later = convert_all([{"site": "tap", "result": _tap([TAP_CONN], offset=12, flights_in_part=1, flights_total=13), "url": "u"}], {"expect": exp})
    assert any("flights 13 to 13 of 13" in n for n in later[4])


@pytest.mark.anyio
async def test_tap_tool_asks_first_then_returns_the_url_script_wishes_and_filters_used():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("tap_recipe", {"origin": "FLR", "destination": "LIS", "day": "2027-03-06"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 3 and "url" not in asked
        part = (await c.call_tool("tap_recipe", {"origin": "FLR", "destination": "LIS", "day": "2027-03-06", "direct_only": False, "checked_bag": True, "refundable": False, "adults": 2, "children": 1})).structured_content
        assert part["wishes"]["expect"]["checked_bag"] is True and part["url"].startswith("https://booking.flytap.com/") and "offset=24" in part["more"]
        assert any("checked bag only (operator)" in f for f in part["filters_used"]) and any("Connections allowed (operator)" in f for f in part["filters_used"])
        none = (await c.call_tool("tap_recipe", {"origin": "FLR", "destination": "LIS", "day": "2027-03-06", "operator_answered": True})).structured_content
        assert any("default: no preference" in f for f in none["filters_used"])
        eco = (await c.call_tool("tap_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-01-12", "direct_only": True, "checked_bag": True, "refundable": True, "cabin": "economy"})).structured_content
        assert eco["wishes"]["expect"]["cabin"] == "economy" and "Economy cabin only (operator)" in eco["filters_used"]
        assert not any("cabin" in f.lower() for f in none["filters_used"]) and none["wishes"]["expect"]["cabin"] is None
        bad = await c.call_tool("tap_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-01-12", "direct_only": True, "checked_bag": True, "refundable": True, "cabin": "luxury"})
        assert bad.is_error                                                  # a cabin TAP does not have is refused (the tool's generic error answer)


# ---------- SATA / Azores Airlines (recipe: the page's own state store) ----------

def _sata(rows, **head):
    base = {"ok": True, "currency": "EUR", "searched": {"from": "LIS", "to": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "infants": 0, "directions": 1},
            "no_flight_found": False, "flights_total": 10, "offset": 0, "flights_in_part": 2, "rows": rows}
    base.update(head)
    return json.dumps(base)


def _sa(fi, fare, total, adt, chd, bag, change, refund, flights="S4121", dep="2027-03-08 06:00", arr="2027-03-08 07:30", frm="LIS", stops=0, mins=150, nadt=2, nchd=1):
    # the rows of S4121 and S4125 LIS-PDL 8 Mar 2027 for 2 adults + 1 child are the real ones (22 Oct 2026)
    return {"fi": fi, "flights": flights, "from": frm, "to": "PDL", "dep": dep, "arr": arr, "mins": mins, "stops": stops, "via": "", "fare": fare, "cabin": "ECONOMY", "total": total, "adt": adt, "chd": chd, "inf": None,
            "nadt": nadt, "nchd": nchd, "ninf": 0, "carry": "1pc up to 8kg (included)", "bag": bag, "change": change, "refund": refund}


SATA_REAL = [_sa(0, "SPL_DOMESTIC_BF", 217.04, 147.36, 69.68, "BAG (chargeable)", "Penalty €100 (chargeable)", "Non Refundable (not included)"),
             _sa(1, "BSC_DOMESTIC_BF", 250.04, 171.36, 78.68, "1 x 23 kg (included)", "Penalty €40 (chargeable)", "Non Refundable (not included)"),
             _sa(2, "FLX_DOMESTIC_BF", 283.04, 195.36, 87.68, "1 x 23 kg (included)", "Penalty €25 (chargeable)", "Penalty €65 (chargeable)"),
             _sa(3, "TOP_DOMESTIC_BF", 408.04, 291.36, 116.68, "2 x 23 kg (included)", "Without penalty* (included)", "Without penalties (included)")]


def test_sata_recipe_builds_the_deeplink_and_the_script_without_hiding_window():
    from datetime import date
    from myt_mcp.sites.sata import sata_recipe
    r = sata_recipe("lis", "pdl", date(2027, 3, 8), 2, 1, 0, False, True, False, 8, 8)
    assert r["url"].startswith("https://book.azoresairlines.pt/booking/dl?") and "search=LIS.PDL.2027-03-08" in r["url"] and "adults=2" in r["url"] and "children=1" in r["url"] and "pointOfSale=PT" in r["url"]
    assert "const LIMIT = 8; const SKIP = 8;" in r["script"] and "__LIMIT__" not in r["script"] and "Availability" in r["script"] and "const window" not in r["script"] and "window.__mytParts" in r["script"]
    assert r["expect"]["leg"] == "LIS to PDL, 08 Mar 2027" and r["expect"]["checked_bag"] is True
    with pytest.raises(ValueError, match="IATA"):
        sata_recipe("Lisbon", "PDL", date(2027, 3, 8))


def test_sata_converts_the_real_rows_with_group_totals_and_fare_terms():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.sata import sata_recipe
    exp = sata_recipe("LIS", "PDL", date(2027, 3, 8), 2, 1)["expect"]
    rows = SATA_REAL + [dict(r, flights="S4125", dep="2027-03-08 14:05", arr="2027-03-08 15:35") for r in SATA_REAL]
    offers, sources, problems, _, notes = convert_all([{"site": "sata", "result": _sata(rows), "url": "u"}], {"expect": exp})
    assert not problems and len(offers) == 8 and (sources[0].read, sources[0].of) == (2, 10) and all(o.quotable and o.currency == "EUR" for o in offers)
    first = offers[0]
    assert first.price_total == 217.04 and first.group == "LIS to PDL, 08 Mar 2027" and first.source == "SATA / Azores Airlines" and not first.connecting and "3 seated travellers" in first.price_basis
    assert first.details["checked_bag"] == "BAG (chargeable)" and "Non Refundable" in first.details["refund_change"] and "adults 147.36 EUR for all 2 adults" in first.details["per_person"] and first.flexible is False
    assert offers[3].flexible is True and offers[2].flexible is None and offers[1].name.startswith("S4121 06:00-07:30 (direct, 2h 30) fare BSC_DOMESTIC_BF")


def test_sata_wishes_decide_fits_and_every_refusal_is_reported():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.sata import sata_recipe
    exp = sata_recipe("LIS", "PDL", date(2027, 3, 8), 2, 1, 0, True, True, True)["expect"]
    got = convert_all([{"site": "sata", "result": _sata(SATA_REAL + [_sa(0, "BSC_DOMESTIC_BF", 300.0, 200.0, 100.0, "1 x 23 kg (included)", "x", "Penalty €50 (chargeable)", flights="S4+SP", stops=1)]), "url": "u"}], {"expect": exp})[0]
    assert [o.fits for o in got] == [False, False, True, True, False]       # direct + checked bag + refundable (a penalty is allowed): FLX and TOP; the one-stop flight fails 'direct'
    exp = sata_recipe("LIS", "PDL", date(2027, 3, 8), 2, 1)["expect"]
    run = lambda text: convert_all([{"site": "sata", "result": text, "url": "u"}], {"expect": exp})[2]
    assert any("searched" in p and "not LIS to PDL on 2027-03-08 for 2" in p for p in run(_sata(SATA_REAL, searched={"from": "LIS", "to": "OPO", "day": "2027-03-08", "adults": 2, "children": 1, "infants": 0, "directions": 1})))
    assert any("searched" in p for p in run(_sata(SATA_REAL, searched={"from": "LIS", "to": "PDL", "day": "2027-03-08", "adults": 3, "children": 0, "infants": 0, "directions": 1})))
    assert any("2 directions" in p for p in run(_sata(SATA_REAL, searched={"from": "LIS", "to": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "infants": 0, "directions": 2})))
    assert any("not on 2027-03-08" in p for p in run(_sata([_sa(0, "SPL_DOMESTIC_BF", 217.04, 147.36, 69.68, "BAG (chargeable)", "x", "y", dep="2027-03-09 06:00")])))
    assert any("does not add up" in p for p in run(_sata([_sa(0, "SPL_DOMESTIC_BF", 200.0, 147.36, 69.68, "BAG (chargeable)", "x", "y")])))
    assert any("priced for 3 adults" in p for p in run(_sata([_sa(0, "SPL_DOMESTIC_BF", 217.04, 147.36, 69.68, "BAG (chargeable)", "x", "y", nadt=3)])))
    assert any("not EUR" in p for p in run(_sata(SATA_REAL, currency="USD")))
    assert any("runs LIS to PDL" not in p and "runs OPO to PDL" in p for p in run(_sata([_sa(0, "SPL_DOMESTIC_BF", 217.04, 147.36, 69.68, "BAG (chargeable)", "x", "y", frm="OPO")])))
    assert any("SATA script reported" in p for p in run(json.dumps({"ok": False, "error": "no flights"})))
    none = convert_all([{"site": "sata", "result": _sata([], no_flight_found=True, flights_total=0, flights_in_part=0), "url": "u"}], {"expect": exp})
    assert not none[0] and any("lists no flight for this route and day" in p and "route not served" in p for p in none[2])      # never "checked, 0 of 0 read"


@pytest.mark.anyio
async def test_sata_tool_asks_first_then_returns_the_url_script_wishes_and_filters_used():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("sata_recipe", {"origin": "LIS", "destination": "PDL", "day": "2027-03-08"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 3 and "url" not in asked
        part = (await c.call_tool("sata_recipe", {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "direct_only": True, "checked_bag": False, "refundable": False, "adults": 2, "children": 1})).structured_content
        assert part["wishes"]["expect"]["direct_only"] is True and part["url"].startswith("https://book.azoresairlines.pt/") and "offset=16" in part["more"]
        assert any("Direct flights only (operator)" in f for f in part["filters_used"]) and any("Any bag option (operator)" in f for f in part["filters_used"])


@pytest.mark.anyio
async def test_tap_and_sata_server_tools_are_pointers_to_the_recipes_unless_switched_on(monkeypatch):
    monkeypatch.setenv("LEGACY_TOOL_POINTERS", "1")      # the pointers are not listed unless asked for (myt_mcp/legacy.py)
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    monkeypatch.delenv("TAP_SERVER_BROWSER", raising=False)
    monkeypatch.delenv("SATA_SERVER_BROWSER", raising=False)
    async with Client(create_server(Settings())) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"tap_flight_prices", "sata_flight_prices", "tap_recipe", "sata_recipe", "tap_fare_calendar"} <= names
        tap = (await c.call_tool("tap_flight_prices", {"from_airport": "FLR", "to_airport": "LIS", "departure_date": "2027-03-06"})).structured_content
        sata = (await c.call_tool("sata_flight_prices", {"from_airport": "LIS", "to_airport": "PDL", "departure_date": "2027-03-08"})).structured_content
        assert tap["ok"] is False and tap["searched"] is False and "tap_recipe" in tap["next"]
        assert sata["ok"] is False and sata["searched"] is False and "sata_recipe" in sata["next"]
    monkeypatch.setenv("TAP_SERVER_BROWSER", "1")
    async with Client(create_server(Settings())) as c:
        tool = next(t for t in (await c.list_tools()).tools if t.name == "tap_flight_prices")
        assert "NOT USED" not in (tool.description or "")


# ---------- Viator (recipes: the list of a search page, and the exact price of one activity) ----------

@pytest.mark.anyio
async def test_viator_find_tool_asks_first():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("viator_find_recipe", {"query": "Florence golf cart tour"})).structured_content
        assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 3 and "url" not in asked
        r = (await c.call_tool("viator_find_recipe", {"query": "Florence golf cart tour", "free_cancellation": False, "max_price": 100, "max_hours": 2, "page": 2})).structured_content
        assert r["url"].startswith("https://www.viator.com/searchResults/all/2?") and "page=3" in r["more"] and any("At most 100 EUR per person (operator)" in f for f in r["filters_used"])
        none = (await c.call_tool("viator_find_recipe", {"query": "Florence golf cart tour", "operator_answered": True})).structured_content
        assert any("default: no preference" in f for f in none["filters_used"])


@pytest.mark.anyio
async def test_viator_activity_tool_returns_steps_script_and_wishes():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    url = "https://www.viator.com/tours/Florence/Private-Golf-Cart-Tour-of-Florence-Discover-Iconic-Landmarks/d519-5546346P3"
    async with Client(create_server(Settings())) as c:
        r = (await c.call_tool("viator_activity_recipe", {"url": url, "day": "2027-03-05", "adults": 2, "children_ages": [8]})).structured_content
        assert r["wishes"]["expect"]["total"] == 3 and r["steps"] and "script" in r and "Free cancellation only" not in " ".join(r["filters_used"])


@pytest.mark.anyio
async def test_viator_and_gyg_server_tools_are_pointers_to_the_recipes_unless_switched_on(monkeypatch):
    monkeypatch.setenv("LEGACY_TOOL_POINTERS", "1")      # the pointers are not listed unless asked for (myt_mcp/legacy.py)
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    monkeypatch.delenv("VIATOR_SERVER_BROWSER", raising=False)
    monkeypatch.delenv("GYG_SERVER_BROWSER", raising=False)
    async with Client(create_server(Settings())) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"viator_search_activities", "viator_activity_details", "getyourguide_find_activities", "getyourguide_activity_details", "viator_find_recipe", "viator_activity_recipe",
                "getyourguide_find_recipe", "getyourguide_activity_recipe"} <= names
        v = (await c.call_tool("viator_search_activities", {"query": "Florence golf cart tour"})).structured_content
        g = (await c.call_tool("getyourguide_find_activities", {"query": "Florence golf cart tour"})).structured_content
        vd = (await c.call_tool("viator_activity_details", {"url": "https://www.viator.com/tours/a/b/d1-X"})).structured_content
        gd = (await c.call_tool("getyourguide_activity_details", {"url": "https://www.getyourguide.com/a/b-t1/", "activity_date": "2027-03-05"})).structured_content
        assert all(x["ok"] is False and x["searched"] is False for x in (v, g, vd, gd))
        assert "viator_find_recipe" in v["next"] and "getyourguide_find_recipe" in g["next"] and "viator_activity_recipe" in vd["next"] and "getyourguide_activity_recipe" in gd["next"]


def test_sata_counts_a_technical_stop_like_the_page_and_says_so():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.sata import sata_recipe
    exp = sata_recipe("LIS", "FLW", date(2027, 3, 9), 2, 0, 1, True)["expect"]
    # real row (22 Oct 2026): S4121 LIS-PDL + SP542 PDL-FLW (two legs: a technical stop), the page says "2 Stops"; 2 adults + 1 infant (the infant pays 6)
    row = {"fi": 0, "flights": "S4121+SP542", "from": "LIS", "to": "FLW", "dep": "2027-03-09 06:00", "arr": "2027-03-09 13:25", "mins": 505, "stops": 2, "tech": 1, "via": "PDL,TER", "fare": "SPL_DOMESTIC_BF",
           "cabin": "ECONOMY", "total": 225.36, "adt": 219.36, "chd": None, "inf": 6, "nadt": 2, "nchd": 0, "ninf": 1, "carry": "1pc up to 8kg (included)", "bag": "BAG (chargeable)", "change": "Penalty €100 (chargeable)", "refund": "Non Refundable (not included)"}
    s = {"from": "LIS", "to": "FLW", "day": "2027-03-09", "adults": 2, "children": 0, "infants": 1, "directions": 1}
    offers, sources, problems, _, _ = convert_all([{"site": "sata", "result": _sata([row], searched=s, flights_total=7, flights_in_part=1), "url": "u"}], {"expect": exp})
    assert not problems and offers[0].connecting is True and offers[0].fits is False and "2 stop(s) via PDL,TER" in offers[0].details["stops"] and "1 technical stop" in offers[0].details["stops"]
    assert "2 seated travellers" in offers[0].price_basis and "infants 6 EUR for all 1 infants" in offers[0].details["per_person"]


def test_skyscanner_direct_only_is_applied_on_the_stop_count_and_flagged_when_not_asked():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.skyscanner import skyscanner_recipe
    exp = skyscanner_recipe("FLR", "LIS", date(2027, 3, 6), 2, [6], "economy", True)["expect"]
    rows = [_sk("Best", 1, "Azores Airlines", "06:00", "07:30", 192.0, direct=True, mins=90)]
    got = convert_all([{"site": "skyscanner", "result": _sky(rows, direct_only=True, matching_total=1), "url": "u"}], {"expect": exp})
    assert not got[2] and got[0][0].fits is True and any("(1 of them direct)" in n for n in got[4])
    asked_any = skyscanner_recipe("FLR", "LIS", date(2027, 3, 6), 2, [6], "economy", False)["expect"]
    assert convert_all([{"site": "skyscanner", "result": _sky(rows, direct_only=True), "url": "u"}], {"expect": asked_any})[2]       # not asked: still flagged
    assert convert_all([{"site": "skyscanner", "result": _sky([_sk("Best", 1, "Vueling Airlines", "13:10", "16:55", 215.68)]), "url": "u"}], {"expect": exp})[2]      # a connection when direct only was asked


def test_the_drivers_age_is_stated_and_a_driver_outside_the_ratehawk_band_gets_a_warning():
    from myt_mcp.sites.ratehawk_cars import driver_filter
    assert driver_filter("26,69", None) == "driver age 26,69 (default: the agency's)"
    assert driver_filter("26,69", 40) == "driver age 40 (operator)"
    assert "young- or senior-driver fee may be missing" in driver_filter("26,69", 25) and "26-69 band" in driver_filter("26,69", 72)


def test_ratehawk_cars_are_not_a_pick_for_a_driver_outside_its_age_band():
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ratehawk_cars import outside_band
    assert outside_band("26,69", 25) and outside_band("26,69", 72) and not outside_band("26,69", 26) and not outside_band("26,69", None)
    rows = [_car("Opel Corsa", 62, "5", "Automatic")]
    inside, _, _, _, _ = convert_all([{"site": "ratehawk_cars", "result": _cars(rows), "url": "u"}], {"automatic": True})
    young, _, problems, _, notes = convert_all([{"site": "ratehawk_cars", "result": _cars(rows), "url": "u"}], {"automatic": True, "driver_outside_band": "25 years old"})
    assert [o.fits for o in inside] == [True] and [o.fits for o in young] == [False] and not problems
    assert any("25 years old" in n and "none is a pick for this driver" in n for n in notes)


def test_ofran_takes_the_drivers_age_as_given_within_its_band():
    from myt_mcp.sites.ofran import ofran_recipe
    young = ofran_recipe("Lisbon Airport", "2026-12-10", "18:30", "2026-12-17", "17:00", driver_years=25)
    assert young["expect"]["driver_years"] == 25 and '"age": 25' in young["script"]
    assert '"age": null' in ofran_recipe("Lisbon Airport", "2026-12-10", "18:30", "2026-12-17", "17:00")["script"]


def test_ofran_says_the_large_bag_wish_cannot_be_checked_on_its_list():
    import inspect
    from myt_mcp.sites import ofran
    src = inspect.getsource(ofran)
    assert "min_large_bags" in src and "NOT checkable on Ofran" in src and "no Ofran car was checked for it" in src


def test_ofran_reads_every_car_at_once_by_default_and_keeps_its_login_check_optional():
    """5 Nov 2026 chat test: only the 30 cheapest of 62 were read (none met automatic + 5 seats) and the chat skipped Ofran on its own login check (now optional)."""
    from myt_mcp.sites.ofran import BATCH, ofran_recipe
    assert BATCH == 100 and '"limit": 100' in ofran_recipe("Lisbon Airport", "2027-03-08", "10:00", "2027-03-11", "10:00")["script"]
    import asyncio
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    async def call():
        async with Client(create_server(Settings())) as c:
            return (await c.call_tool("ofran_recipe", {"pickup": "Lisbon Airport", "pickup_date": "2027-03-08", "pickup_time": "10:00", "dropoff_date": "2027-03-11", "dropoff_time": "10:00", "operator_answered": True})).structured_content
    out = asyncio.run(call())
    assert "login_check" in out and "OPTIONAL" in out["login_check"]["run_first"] and "next 100 cars" in out["more"]


def test_ofran_one_way_fee_is_added_on_a_one_way_search_and_only_named_on_a_same_station_one():
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ofran import ofran_recipe
    exp1 = ofran_recipe("Lisbon Airport", "2027-03-08", "10:00", "2027-03-11", "10:00", dropoff="Porto Airport")["expect"]
    form = {"pickup_place": "Lisbon Airport (LIS)", "dropoff_place": "Porto Airport (OPO)", "pickup_when": "08.03.27 | 10:00", "dropoff_when": "11.03.27 | 10:00", "age": None}
    rows = [_of(price="100.00", one_way_fee="110.70"), _of(price="90.00")]
    one, _, problems, _, notes = convert_all([{"site": "ofran", "result": _ofr(rows, form=form), "url": "u"}], {"expect": exp1, "max_total": 205})
    assert not problems and [o.price_total for o in one] == [210.7, 90.0] and [o.fits for o in one] == [False, True]       # 100 + 110.70 is over a 205 budget
    assert "one-way fee of 110.7 added" in one[0].price_basis and one[0].details["one_way_fee"].startswith("110.7 EUR, added") and any("one-way fee is added" in n for n in notes)
    exp2 = ofran_recipe("Lisbon Airport", "2027-03-08", "10:00", "2027-03-11", "10:00")["expect"]
    same, _, _, _, notes2 = convert_all([{"site": "ofran", "result": _ofr([_of(price="100.00", one_way_fee="153.75")]), "url": "u"}], {"expect": exp2})
    assert same[0].price_total == 100.0 and "NOT added" in same[0].details["one_way_fee"] and any("without saying when it applies" in n for n in notes2)


def test_ofran_reads_both_spellings_of_the_excess_plan_and_off_airport_stations():
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ofran import ofran_recipe
    exp = ofran_recipe("Lisbon Airport", "2027-03-08", "10:00", "2027-03-11", "10:00")["expect"]
    rows = [_of("Fiat 500", "50.00", package="תוכנית ביטול השתתפות עצמית", station="Off Airport"), _of("Opel Corsa", "60.00", package="תכנית ביטול השתתפות עצמית"), _of("VW Polo", "70.00", package="תכנית בסיס", cdw="700.00")]
    got = convert_all([{"site": "ofran", "result": _ofr(rows), "url": "u"}], {"expect": exp, "zero_excess": True})[0]
    assert [o.fits for o in got] == [True, True, False] and "outside the airport" in got[0].details["pickup_place"] and "Off Airport" in got[0].details["pickup_place"]


def test_a_source_with_no_search_address_may_give_its_home_page_as_its_link_and_others_may_not():
    from myt_mcp.compose import NotChecked, SourceRead, validate
    ok = validate("cars", ["Automatic gearbox (operator)"], [SourceRead(name="Ofran", link="https://ofran.co.il/", read=62, of=62)], [], [], {}, "10:00")
    assert not any("home page" in p for p in ok)
    bad = validate("cars", ["Automatic gearbox (operator)"], [SourceRead(name="Europcar", link="https://www.europcar.com/", read=17, of=32)], [], [], {}, "10:00")
    assert any("Europcar" in p and "home page" in p for p in bad)


def test_ofran_seats_are_recommended_passengers_so_one_short_is_unconfirmed_and_two_short_does_not_fit():
    """5 Nov 2026: a Citroen C4 is 2 adults + 2 kids = 4 on Ofran and 5 seats on Europcar (same class CDAR), so '5 seats' dropped real 5-seaters."""
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ofran import ofran_recipe
    exp = ofran_recipe("Lisbon Airport", "2027-03-08", "10:00", "2027-03-11", "10:00")["expect"]
    rows = [_of("Citroen C4", "80.00", adults="2", kids="2", acriss="CDAR"), _of("Fiat 500", "70.00", adults="2", kids="1", acriss="MBMR"), _of("Jeep", "90.00", adults="3", kids="2", acriss="CFAR"), _of("Seat", "95.00", adults="2", kids="2", acriss="CDAR", cdw="500.00")]
    got, _, _, _, notes = convert_all([{"site": "ofran", "result": _ofr(rows), "url": "u"}], {"expect": exp, "min_seats": 5})
    by = {o.name.split(" (")[0]: o for o in got}
    assert by["Jeep"].fits is True and by["Citroen C4"].fits is None and by["Citroen C4"].unconfirmed == ["seats"] and by["Fiat 500"].fits is False and by["Fiat 500"].unconfirmed == []
    assert any("one seat fewer than the 5 asked" in n and "RECOMMENDED passengers" in n and "never a pick" in n for n in notes)
    other = convert_all([{"site": "ofran", "result": _ofr(rows), "url": "u"}], {"expect": exp, "min_seats": 5, "max_total": 85})[0]
    assert {o.name.split(" (")[0]: o.fits for o in other}["Seat"] is False and {o.name.split(" (")[0]: o.unconfirmed for o in other}["Seat"] == []          # a row that misses another wish is not "unconfirmed"


def test_ofran_judges_zero_excess_by_the_numbers_so_the_english_page_works_like_the_hebrew_one():
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ofran import ofran_recipe
    exp = ofran_recipe("Lisbon Airport", "2027-03-08", "10:00", "2027-03-11", "10:00")["expect"]
    rows = [_of("Fiat 500", "50.00", package="Zero Excess"), _of("Opel Corsa", "60.00", package="Inclusive", cdw="700.00"), _of("VW Polo", "70.00", package="Zero Excess", cdw="300.00"), _of("Kia Rio", "80.00", package="Zero Excess", theft_excess="500.00")]
    got = convert_all([{"site": "ofran", "result": _ofr(rows), "url": "u"}], {"expect": exp, "zero_excess": True})[0]
    assert [o.fits for o in got] == [True, False, False, False] and got[0].details["plan"] == "Zero Excess" and got[1].details["plan"] == "Inclusive"      # a plan's name alone is never zero excess: both excesses must be 0


def test_ofran_station_type_is_given_in_words_and_any_other_type_is_called_outside_the_airport():
    from myt_mcp.sites.ofran import station_text
    assert station_text("Airport") == "Pick-up station inside the airport"
    assert "outside the airport" in station_text("City") and "City" in station_text("City") and station_text(None) == "not shown"


def test_a_big_price_gap_between_sources_is_named_for_transfers_and_cars_only():
    from myt_mcp.compose import Offer, price_gap_notes
    mk = lambda src, price: Offer(group="g", source=src, name="x", price_total=price, currency="EUR", price_basis="b", fits=True, details={})
    rows = [mk("RateHawk Transfers", 13.0), mk("Kiwitaxi", 40.0), mk("Kiwitaxi", 46.0)]
    note = price_gap_notes("transfers", rows)
    assert len(note) == 1 and "13.00 EUR" in note[0] and "40.00 EUR" in note[0] and "compare them row by row" in note[0]
    assert not price_gap_notes("transfers", [mk("RateHawk Transfers", 13.0), mk("Kiwitaxi", 20.0)]) and not price_gap_notes("flights", rows)


def test_a_source_the_operator_excluded_and_a_filter_the_server_wrote_are_accepted():
    rows = [Offer(group="Terra Nostra", source="Bensaude", name="Cosy Art Deco FLEX", price_total=322, currency="EUR")]
    r = compose(kind="hotels", filters_used=["breakfast (operator)", "prices converted to EUR by the server at the Bank of Israel representative rates of 2026-10-26"],
                sources_read=[SourceRead(name="Bensaude", read=1, of=1, link="https://bensaude.e-gds.com/webfrontendcorporate/shoppingcart/availability.aspx?hotelid=29")],
                not_checked=[NotChecked(name="RateHawk", reason="operator excluded this source"), NotChecked(name="Arbitrip", reason="operator excluded this source")],
                offers=rows, myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert r["ok"] is True and "RateHawk (operator excluded this source)" in r["answer"], r
    lazy = compose(kind="hotels", filters_used=["breakfast (operator)"], sources_read=[SourceRead(name="Bensaude", read=1, of=1, link="https://bensaude.e-gds.com/webfrontendcorporate/shoppingcart/availability.aspx?hotelid=29")],
                   not_checked=[NotChecked(name="RateHawk", reason="for time")], offers=rows, myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert lazy["ok"] is False        # the laziness reasons stay refused


def test_the_reasons_a_chat_gives_for_leaving_out_sources_the_operator_did_not_name_are_accepted_and_laziness_is_not():
    rows = [Offer(group="Terra Nostra", source="Bensaude", name="Cosy Art Deco FLEX", price_total=322, currency="EUR")]
    src = [SourceRead(name="Bensaude", read=1, of=1, link="https://bensaude.e-gds.com/webfrontendcorporate/shoppingcart/availability.aspx?hotelid=29")]
    for reason in ("operator asked for Bensaude only", "the operator named Booking.com only", "operator excluded this source"):
        ok = compose(kind="hotels", filters_used=["breakfast (operator)"], sources_read=src, not_checked=[NotChecked(name="RateHawk", reason=reason)], offers=rows, myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
        assert ok["ok"] is True, (reason, ok)
    for reason in ("for time", "out of scope", "you did not ask"):
        bad = compose(kind="hotels", filters_used=["breakfast (operator)"], sources_read=src, not_checked=[NotChecked(name="RateHawk", reason=reason)], offers=rows, myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
        assert bad["ok"] is False, reason


def test_a_filter_line_the_server_wrote_with_agency_rule_is_not_refused():
    rows = [Offer(group="Terra Nostra", source="Bensaude", name="Cosy Art Deco FLEX", price_total=322, currency="EUR")]
    src = [SourceRead(name="Bensaude", read=1, of=1, link="https://bensaude.e-gds.com/webfrontendcorporate/shoppingcart/availability.aspx?hotelid=29")]
    ok = compose(kind="hotels", filters_used=["Best and Cheapest sorts read together (agency rule)"], sources_read=src, not_checked=[], offers=rows, myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert ok["ok"] is True, ok


def test_a_tab_column_only_some_sources_have_is_not_reported_as_not_shown():
    """27 Oct 2026: 'from tab (in 16 row(s))' was listed as hidden by the sources; only Booking.com rows carry it, Skyscanner rows cannot."""
    rows = offers() + [Offer(group="FLR -> LIS", source="Booking.com flights", name="X", price_total=300, currency="EUR", details={"from_tab": "Best and Cheapest", "stops": 1})]
    booking = SourceRead(name="Booking.com flights", read=1, of=1, link="https://flights.booking.com/flights/TLV.AIRPORT-LIS.AIRPORT/?depart=2027-03-06")
    text = run(offers=rows, sources_read=SRC + [booking])["answer"]
    assert "| from tab |" in text and "from tab" not in text.split("Not shown by the sources:")[1].split("\n")[0]


def test_detail_keys_typed_with_spaces_or_capitals_are_one_column():
    """27 Oct 2026, Kiwitaxi rows: 'meeting point' and 'waiting time' (spaces) came next to the required meeting_point and waiting_time: two columns each."""
    o = Offer(source="Kiwitaxi", name="Comfort", price_total=40, currency="EUR", details={"meeting point": "arrivals hall", "Waiting-Time": "60 min", "waiting_time": None, "flight tracking": "yes"})
    assert o.details == {"meeting_point": "arrivals hall", "waiting_time": "60 min", "flight_tracking": "yes"}
    r = run(kind="transfers", pickup_time="10:00", offers=[Offer(group="A to B", source="TAP", name="Comfort", price_total=40, currency="EUR", details={"meeting point": "hall", "waiting time": "60 min", "capacity": "4", "cancellation": "free", "provider": "x"})])
    header = next(line for line in r["answer"].splitlines() if line.startswith("| Source |"))
    assert header.lower().count("meeting point") == 1 and header.lower().count("waiting time") == 1


def test_a_filter_the_assistant_chose_and_says_so_is_accepted_and_a_bare_judgement_is_not():
    """28 Oct 2026: '(assistant: no hotel picked yet)' and '(my judgement)' were refused, each costing the chat a retry."""
    ok = run(filters_used=["direct (trip default)", "Drop-off at Rossio Square until a hotel is chosen (assistant: no hotel picked yet)"])
    assert ok["ok"] is True, ok
    bad = run(filters_used=["direct (trip default)", "The 3 chosen: highest rating with most reviews (my judgement)"])
    assert bad["ok"] is False and any("where it comes from" in p for p in bad["problems"])


def test_the_title_filter_line_of_the_viator_and_getyourguide_lists_names_its_source():
    """28 Oct 2026: the recipes wrote 'Titles holding any of: lisbon (the wish's own words)', which compose_answer itself refused."""
    import re
    from pathlib import Path
    from myt_mcp.compose import SOURCE_WORDS
    for name in ("viator_find.py", "getyourguide_find.py"):
        src = (Path(__file__).parent.parent / "myt_mcp" / "sites" / name).read_text()
        bracket = re.search(r"Titles holding any of: \{[^\"]*\} \(([^)]*)\)\"", src).group(1)
        assert any(w in bracket.lower() for w in SOURCE_WORDS), (name, bracket)


def test_when_every_source_is_excused_the_server_writes_the_nothing_found_answer_itself():
    """28 Oct 2026, trains: CP had none on sale and RateHawk has no Lisbon station; compose refused ('sources_read is empty') and the chat wrote the section by hand, '0 of 0 trains shown'."""
    r = compose(kind="trains", filters_used=["2nd class (operator)", "Changes allowed (operator)"], sources_read=[],
                not_checked=[NotChecked(name="CP", reason="not available: CP has no trains on sale for this date"), NotChecked(name="RateHawk Train tickets", reason="route not served: no Lisboa station")],
                offers=[], myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert r["ok"] is True, r
    text = r["answer"]
    assert text.startswith("Sources checked: none returned an option | Not checked: CP (not available: CP has no trains on sale for this date); RateHawk Train tickets (route not served: no Lisboa station)")
    assert "Filters used: 2nd class (operator); Changes allowed (operator)" in text and "0 of 0" not in text
    assert text.count("not determined: no source returned an option for this search") == 4 and "In MYT supplier?" not in text and "Sources: none read" in text      # trains never had that line
    assert "| Cheapest | not determined |" in text
    t = compose(kind="transfers", filters_used=["2 passengers (operator)"], sources_read=[], not_checked=[NotChecked(name="iWay", reason="no browser tool in this chat")], offers=[], myt_supplier={}, pickup_time="10:00", sorted_by_price=False, notes="")
    assert t["ok"] is True and "In MYT supplier? not checked: there was no option to check." in t["answer"] and "Pick-up time used on every source: 10:00" in t["answer"]


def test_nothing_found_still_needs_allowed_reasons_filters_with_a_source_and_no_sources_at_all_is_still_refused():
    bad = compose(kind="trains", filters_used=["2nd class (operator)"], sources_read=[], not_checked=[NotChecked(name="CP", reason="skipped for time")], offers=[], myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert bad["ok"] is False and any("not an allowed reason" in p for p in bad["problems"])
    nofilter = compose(kind="trains", filters_used=["2nd class"], sources_read=[], not_checked=[NotChecked(name="CP", reason="not available: no trains on sale")], offers=[], myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert nofilter["ok"] is False and any("where it comes from" in p for p in nofilter["problems"])
    nothing = compose(kind="trains", filters_used=["2nd class (operator)"], sources_read=[], not_checked=[], offers=[], myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert nothing["ok"] is False and any("sources_read is empty" in p for p in nothing["problems"])


def test_one_leg_written_with_different_spellings_is_one_table_with_one_set_of_picks():
    """28 Oct 2026: Kiwitaxi (typed by the chat) and iWay (from the recipe) named the same leg differently and came as two tables; Best fit was Kiwitaxi in one and 'not determined' in the other."""
    from myt_mcp.compose import group_key
    assert group_key("Lisbon Airport -> Praça do Comércio 6 Mar 2027 10:00") == group_key("Lisbon Airport to Praça do Comércio, 06 Mar 2027 10:00")
    assert group_key("Lisbon Airport to Praça do Comércio") != group_key("Praça do Comércio to Lisbon Airport")      # direction matters
    assert group_key("TLV -> LIS 6 Mar 2027") != group_key("LIS -> TLV 6 Mar 2027") and group_key("TLV -> LIS 6 Mar 2027") != group_key("TLV -> LIS 16 Mar 2027")
    mk = lambda g, src, name, p, q: Offer(group=g, source=src, name=name, price_total=p, currency="EUR", quotable=q, fits=True,
                                          details={"capacity": "x", "waiting_time": "x", "cancellation": "free", "provider": "x", "meeting_point": "x"})
    rows = [mk("Lisbon Airport -> Praça do Comércio 6 Mar 2027 10:00", "Kiwitaxi", "Comfort", 40, True), mk("Lisbon Airport to Praça do Comércio, 06 Mar 2027 10:00", "iWay", "Standard", 25.37, False)]
    src = [SourceRead(name="Kiwitaxi", read=9, of=9, link="https://kiwitaxi.com/en/portugal/x?ref=sf"), SourceRead(name="iWay", read=4, of=4, link="https://iway.io/booking?from=a&to=b")]
    text = compose("transfers", ["2 passengers (operator)"], src, [], rows, {}, "10:00", False, "")["answer"]
    assert text.count("| Pick | Option | Reason |") == 1 and "iWay" in text and "Kiwitaxi" in text


def test_a_long_activities_list_shows_30_rows_and_says_how_many_were_read():
    """28 Oct 2026: 54 Booking.com rows were shown in full and the chat shortened them by hand into 'for example ...' (check_answer cannot see a shortened table); the server now does the cutting and says so."""
    from myt_mcp.compose import MAX_ROWS_BY_KIND
    assert MAX_ROWS_BY_KIND["activities"] == 30
    rows = [Offer(group="Lisbon, 7 Mar 2027", source="Booking.com attractions", name=f"Tour {i}", price_total=10 + i, currency="EUR", quotable=False,
                  details={"duration": "2h", "start_times": "x", "language": "x", "meeting_point": "x", "cancellation": "free", "private_or_group": "x"}) for i in range(54)]
    src = [SourceRead(name="Booking.com attractions", read=54, of=54, link="https://www.booking.com/attractions/searchresults/pt/lisbon.html?date_from=2027-03-07")]
    text = compose("activities", ["Free cancellation (operator)"], src, [], rows, {}, None, False, "", max_rows=MAX_ROWS_BY_KIND["activities"])["answer"]
    assert len([l for l in text.splitlines() if l.startswith("| Booking.com")]) == 30 and "Showing 30 of the 54 options read" in text


def test_a_source_listed_as_read_with_no_options_still_gets_the_nothing_found_answer():
    """28 Oct 2026, trains: the chat listed CP in sources_read (searched, 0 trains) and RateHawk in not_checked; compose answered 'offers is empty' and the chat had to retry."""
    cp = SourceRead(name="CP Comboios de Portugal", read=0, of=0, link="https://www.cp.pt/en/resultado-pesquisa?passageiros=2&startDate=2027-03-07")
    r = compose(kind="trains", filters_used=["2nd class (operator)"], sources_read=[cp], not_checked=[NotChecked(name="RateHawk Train tickets", reason="route not served: no Lisboa station")],
                offers=[], myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert r["ok"] is True, r
    text = r["answer"]
    assert text.startswith("Sources checked: none returned an option (searched, no options: CP Comboios de Portugal) | Not checked: RateHawk Train tickets (route not served: no Lisboa station)")
    assert "0 of 0" not in text and "Sources: CP Comboios de Portugal: https://www.cp.pt/en/resultado-pesquisa" in text
    odd = compose(kind="trains", filters_used=["2nd class (operator)"], sources_read=[SourceRead(name="CP", read=5, of=5, link="https://www.cp.pt/en/resultado-pesquisa?x=1")], not_checked=[], offers=[],
                  myt_supplier={}, pickup_time=None, sorted_by_price=False, notes="")
    assert odd["ok"] is False and any("offers is empty" in p for p in odd["problems"])          # rows read but none passed on is still a mistake


def test_a_long_detail_cell_is_cut_at_a_word_and_ends_with_an_ellipsis_but_the_name_and_the_basis_are_never_cut():
    """28 Oct 2026: 'Please look for the Blue Umbrellas at t' and 'contact us directly befor': cut in the middle of a word."""
    from myt_mcp.compose import DETAIL_CAP, _cell
    long = "Please look for the Blue Umbrellas at the meeting point near the statue and wait for your guide. " * 5
    cut = _cell(long, DETAIL_CAP)
    assert len(cut) <= DETAIL_CAP + 1 and cut.endswith("…") and not cut[:-1].endswith(" ") and long.startswith(cut[:-1])
    assert _cell("short text", DETAIL_CAP) == "short text" and _cell(long) == long.replace("\n", " ")
    basis = "per vehicle, one way, iWay's list price for the route (its date and time step was not opened: a night or holiday surcharge or a wait may change it), converted from USD 28.40 at 1 USD = 0.8932 EUR " * 2
    o = Offer(group="g", source="iWay", name="Standard " + "x " * 120, price_total=25.37, currency="EUR", price_basis=basis, details={"capacity": long, "waiting_time": "x", "cancellation": "x", "provider": "x", "meeting_point": "x"})
    text = compose("transfers", ["2 passengers (operator)"], [SourceRead(name="iWay", read=1, of=1, link="https://iway.io/booking?from=a&to=b")], [], [o], {}, "10:00", False, "")["answer"]
    assert basis.strip()[:60] in text and "x x x x" in text and "…" in text


def test_a_place_the_sources_box_does_not_offer_is_an_allowed_reason_so_it_need_not_be_called_route_not_served():
    """28 Oct 2026: RateHawk Transfers had no 'Praça do Comércio' place; 'place not offered' was refused and the chat relabelled it 'route not served', which is not true (RateHawk serves Lisbon)."""
    r = run(not_checked=[NotChecked(name="RateHawk Transfers", reason="place not found in RateHawk's drop-off box: no 'Praça do Comércio, Lisbon' suggestion")])
    assert r["ok"] is True, r
    assert "RateHawk Transfers (place not found" in r["answer"]


def test_the_words_a_chat_types_for_the_columns_become_the_columns_the_other_sources_use():
    """28 Oct 2026: Kiwitaxi rows (typed) said 'free cancellation', 'max bags', 'max passengers': false 'not shown' gaps next to RateHawk's cancellation and capacity."""
    o = Offer(source="Kiwitaxi", name="Comfort", price_total=40, currency="EUR", details={"free cancellation": "16 hours before", "max bags": 3, "max passengers": 4, "meeting point": None})
    assert o.details == {"cancellation": "16 hours before", "meeting_point": None, "capacity": "up to 4 people / 3 bags"}
    keep = Offer(source="RateHawk Transfers", name="Micro", price_total=14, currency="EUR", details={"capacity": "up to 3 people / 2 bags", "cancellation": "free 24h"})
    assert keep.details == {"capacity": "up to 3 people / 2 bags", "cancellation": "free 24h"}


def test_most_flexible_says_when_only_comparison_rows_show_free_cancellation_and_a_pick_outside_the_terminal_gets_a_caution():
    """28 Oct 2026, cars: 'no free-cancellation option was read' beside Rentalcars rows that carry the flag; the Best fit was an Ofran station outside the airport."""
    from myt_mcp.compose import picks
    cmp_row = Offer(group="g", source="Rentalcars.com", name="Golf", price_total=19, currency="EUR", quotable=False, flexible=True, fits=True)
    best = Offer(group="g", source="Ofran", name="Qashqai", price_total=165.72, currency="EUR", quotable=True, fits=True, details={"pickup_place": "Pick-up station outside the airport (not at the terminal)"})
    rows, notes = picks("cars", [cmp_row, best], False)
    d = {a: c for a, _, c in rows}
    assert d["Most flexible"].startswith("not determined: no quotable option shows free cancellation (only 1 comparison-only row(s) do, from Rentalcars.com)")
    assert any("Caution on the Best fit (Ofran: Qashqai)" in n and "not at the airport terminal" in n for n in notes) and sum("Caution on the" in n for n in notes) == 1      # Best fit and Recommended are the same row: said once
    none = Offer(group="g", source="Ofran", name="x", price_total=9, currency="EUR", quotable=True, fits=True)
    assert {a: c for a, _, c in picks("cars", [none], False)[0]}["Most flexible"] == "not determined: no refundable or free-cancellation option was read"


def test_a_column_only_some_kinds_of_row_have_is_not_counted_as_not_shown_for_the_others():
    """28 Oct 2026, activities: 'includes (in 13 rows), pay, ticket, option state' counted the list rows for columns only the exact-price rows have."""
    lst = Offer(group="g", source="Viator", name="Walk", price_total=3, currency="EUR", quotable=False, details={"duration": "2h", "start_times": "check", "language": "x", "meeting_point": "x", "cancellation": "free", "private_or_group": "x"})
    exact = Offer(group="g", source="Viator", name="Walk - English", price_total=6, currency="EUR", quotable=True, details={"duration": "2h", "start_times": "10:00", "language": "x", "meeting_point": "x", "cancellation": "free",
                                                                                                                              "private_or_group": "x", "includes": None, "pay": None})
    text = compose("activities", ["Free cancellation (operator)"], [SourceRead(name="Viator", read=2, of=2, link="https://www.viator.com/searchResults/all?text=Lisbon+tours")], [], [lst, exact], {}, None, False, "")["answer"]
    gap_line = next(l for l in text.splitlines() if l.startswith("Not shown by the sources:"))
    assert "includes (in 1 row(s))" in gap_line and "pay (in 1 row(s))" in gap_line


def test_ratehawk_cars_knows_the_lisbon_airport_id():
    """Lisbon (Humberto Delgado) was read from the cars page on 19 and 29 Oct 2026: route=965847007,965847007; the recipe must not ask for the id again."""
    from myt_mcp.sites.ratehawk_cars import known_locations
    ids = known_locations()
    assert ids["humberto delgado airport"] == ids["lisbon airport"] == 965847007


def test_gyg_and_viator_scripts_recognise_the_cloudflare_check_page():
    from pathlib import Path
    sites = Path(__file__).resolve().parent.parent / "myt_mcp" / "sites"
    for name in ("getyourguide_find", "getyourguide_activity", "viator_find", "viator_activity"):
        assert "performing security verification" in (sites / f"{name}.js").read_text(encoding="utf-8"), name


def test_ratehawk_transfers_accepts_the_15_minute_step_at_or_before_the_asked_time():
    """2 Nov 2026: the flight lands 17:50, RateHawk's list has 17:45: the answer was refused twice. The step at or just before the asked time is accepted and named; a later or farther time is still refused."""
    import json

    from myt_mcp.sites.ratehawk_transfers import convert

    page_time = TRANSFERS_RESULT["form"]["when"]          # '<day> <Mon>, <weekday>, 16:30'
    base = {"pickup": "Rome FCO Fiumicino", "dropoff": "Room Mate Collection Mia", "day": "2027-03-01", "adults": 2, "children": 1}
    early = convert(json.dumps(TRANSFERS_RESULT), {"expect": {**base, "time": "16:40"}}, "Transfers")
    assert not early.problems and any("15-minute steps" in n and "16:30" in n and "16:40" in n for n in early.extra_notes), (page_time, early.problems)
    exact = convert(json.dumps(TRANSFERS_RESULT), {"expect": {**base, "time": "16:30"}}, "Transfers")
    assert not exact.problems and not any("15-minute" in n for n in exact.extra_notes)
    for asked in ("16:45", "16:20", "10:00"):          # after the next step, or before the page's time: not the closest step at or before
        wrong = convert(json.dumps(TRANSFERS_RESULT), {"expect": {**base, "time": asked}}, "Transfers")
        assert any(f"not at {asked}" in p for p in wrong.problems), asked


def test_error_messages_name_the_fields_the_chat_must_use():
    """2 Nov 2026: the chat guessed the field names ('ratehawk', 'link' in the items) because 'unknown site' and 'give the exact page as link' named no field."""
    from myt_mcp.compose import SourceRead, validate
    from myt_mcp.sites import unknown_site
    msg = unknown_site("", {"viator_find": 1, "getyourguide_find": 2})
    assert '"site"' in msg and '"result"' in msg and '"url"' in msg and "unknown site ''" in msg
    problems = validate("activities", [], [SourceRead(name="Viator", read=5, of=50, link="")], [], [], {}, None)
    assert any("`sources_read` entry" in p and "no link" in p and "not a home page" in p for p in problems)


def test_a_row_marked_not_confirmed_by_its_site_is_never_a_pick_and_apply_wishes_keeps_it_so():
    """2 Nov 2026: Ofran's VW Polo (large bags unconfirmed) went through apply_wishes, got fits=True and became the Best fit and Recommended."""
    from myt_mcp.compose import Offer, apply_wishes, mark_unconfirmed, picks
    det = {"seats_bags": "4 seats / 1/1 bags"}
    unsure = Offer(group="g", source="Ofran", name="VW Polo", price_total=112.74, currency="EUR", quotable=True, details=dict(det))
    sure = Offer(group="g", source="Other", name="Opel Corsa", price_total=130.0, currency="EUR", quotable=True, details={"seats_bags": "5 seats / 2 large bags"}, fits=True)
    mark_unconfirmed(unsure, "large bags")
    apply_wishes([unsure, sure], {"min_large_bags": 2, "automatic": True})
    assert unsure.fits is None and unsure.unconfirmed == ["large bags"]
    rows, _ = picks("cars", [unsure, sure], True)
    by = {a: b for a, b, _ in rows}
    assert "Opel Corsa" in by["Best fit"] and "Opel Corsa" in by["Recommended"] and "VW Polo" in by["Cheapest"]


def test_the_cheapest_activity_is_an_exact_price_for_the_date_not_a_list_from_price():
    """2 Nov 2026: the Cheapest pick was Devour Lisbon's list 'from' price EUR 63; the price for the date was EUR 79 (EUR 158 for two)."""
    from myt_mcp.compose import Offer, picks
    list_row = Offer(group="g", source="Viator", name="Devour Lisbon", price_total=63.0, currency="EUR", quotable=False, price_basis="'from' price per person")
    exact = Offer(group="g", source="Viator", name="Devour Lisbon - Small Group (2 travellers)", price_total=158.0, currency="EUR", quotable=True, price_basis="whole group, 2 adults")
    rows, _ = picks("activities", [list_row, exact], False)
    cheapest = next(r for r in rows if r[0] == "Cheapest")
    assert "158.00 EUR" in cheapest[1] and "exact price for the date" in cheapest[2] and "lower 'from' price per person" in cheapest[2] and "63.00 EUR" in cheapest[2]
    only_list, _ = picks("activities", [list_row], False)
    assert "63.00 EUR" in only_list[0][1] and "comparison row, not quotable" in only_list[0][2]          # with no exact price the list's own Cheapest stays, and says what it is


def test_room_for_large_bags_is_written_once_in_the_filters():
    from myt_mcp.tools.compose_answer import one_large_bags_line
    f = ["Automatic gearbox (operator)", "room for 2 large bags (operator): NOT checkable on Ofran, its list shows only 'x/y' bags", "room for at least 2 large bags (operator)", "driver age 25 (operator)"]
    assert one_large_bags_line(f) == [f[0], f[1], f[3]] and one_large_bags_line(f[:1] + f[2:]) == f[:1] + f[2:]


def _cover_car(source, name, price, excess, quotable=True, basis="whole rental, 3 days", fits=True):
    from myt_mcp.compose import Offer
    return Offer(group="g", source=source, name=name, price_total=price, currency="EUR", price_basis=basis, quotable=quotable, fits=fits, details={"excess": excess})


def test_the_car_picks_name_the_cover_the_fees_not_in_the_price_and_a_cheapest_with_zero_excess():
    """5 Nov 2026: the same Europcar Citroen C4 was EUR 108 with a 3,000 excess and EUR 193 with none, and 'Cheapest' compared only the price."""
    from myt_mcp.compose import cover_text, is_zero_excess, picks
    rows = [_cover_car("Rentalcars.com", "Seat Leon", 17.79, "damage excess 2,400.00 EUR, theft excess 2,400.00 EUR", False, "whole rental, 3 days; plus fees listed as not in the total: 26.69 EUR (transponder, valet: which of them apply is not shown)"),
            _cover_car("Europcar", "Citroen C4", 108.34, "BASIC with an excess of EUR 3,000.00; no zero-excess option is offered in the list", False),
            _cover_car("Ofran", "Citroen C4", 192.82, "excess cancelled (the plan includes it, excess 0)"),
            _cover_car("Ofran", "Opel Corsa", 120.09, "zero excess (damage excess 0)", True)]
    out, notes = picks("cars", rows, False)
    by = {p: (o, r) for p, o, r in out}
    assert by["Cheapest"][0].endswith("Seat Leon - 17.79 EUR") or "Seat Leon" in by["Cheapest"][0]
    assert "(cover: excess 2,400.00 EUR; plus 26.69 EUR of fees listed as not in the total)" in by["Cheapest"][1]
    assert "Cheapest with zero excess" in by and "Opel Corsa" in by["Cheapest with zero excess"][0]
    assert "lowest of 2 zero-excess option(s) in EUR, 102.30 EUR above the Cheapest, which has excess 2,400.00 EUR" in by["Cheapest with zero excess"][1]
    assert any("do not come with the same cover" in n for n in notes) and len(out) == 5
    assert (cover_text(rows[1]), is_zero_excess(rows[2]), is_zero_excess(rows[0])) == ("excess 3,000.00 EUR", True, False) and cover_text(_cover_car("x", "y", 1.0, "not shown")) == "excess not shown"


def test_no_zero_excess_pick_when_the_cheapest_already_has_zero_excess_or_nothing_does_and_other_kinds_are_unchanged():
    from myt_mcp.compose import Offer, picks
    zero_cheapest = [_cover_car("Ofran", "A", 90.0, "excess cancelled (included)"), _cover_car("Europcar", "B", 108.0, "BASIC with an excess of EUR 3,000.00")]
    assert [p for p, _, _ in picks("cars", zero_cheapest, False)[0]] == ["Cheapest", "Best fit", "Most flexible", "Recommended"]
    none_zero = [_cover_car("Europcar", "B", 108.0, "BASIC with an excess of EUR 3,000.00"), _cover_car("Rentalcars.com", "C", 20.0, "damage excess 2,400.00 EUR", False)]
    out, notes = picks("cars", none_zero, False)
    assert [p for p, _, _ in out] == ["Cheapest", "Best fit", "Most flexible", "Recommended"] and not any("same cover" in n for n in notes)
    flights = [Offer(group="g", source="TAP", name="TP1", price_total=100.0, currency="EUR", price_basis="b", details={"excess": "zero excess"})]
    assert [p for p, _, _ in picks("flights", flights, False)[0]] == ["Cheapest", "Best fit", "Most flexible", "Recommended"] and "cover:" not in picks("flights", flights, False)[0][0][2]
