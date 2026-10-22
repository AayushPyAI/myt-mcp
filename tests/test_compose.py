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


SAMPLE_RH = {"ok": True, "header": "Lisbon: 1160 accommodation options available", "sort": "Price (low to high)", "start_page": 1, "pages_read": 1, "rows_read": 3,
             "stopped": None, "price_order": "ascending", "rows": [
    {"p": 1, "name": "White House Lisbon Hostel", "stars": 1, "distance": "3 km from the Lisbon center", "score": "9.0", "reviews": None, "room": "Bed in Dorm", "bed": None,
     "meal": "No meals", "cancellation": "No free cancellation", "payment": "Pay by wire transfer", "price": "EUR 61", "basis": "for 2 nights for 2 guests", "path": "/hotel/portugal/lisbon/mid1/white/"},
    {"p": 1, "name": "Hotel Alegria", "stars": 3, "distance": "700 m from the Lisbon center", "score": "9.4", "reviews": "1765 reviews", "room": "Double", "bed": "full double bed",
     "meal": "Breakfast incl.", "cancellation": "Free cancellation", "payment": "Pay by wire transfer", "price": "EUR 513", "basis": "for 2 nights for 2 guests", "path": "/hotel/portugal/lisbon/mid2/alegria/"},
    {"p": 1, "name": "Hotel Four", "stars": 4, "distance": "1.2 km from the Lisbon center", "score": "8.8", "reviews": "900 reviews", "room": "Twin", "bed": "twin beds",
     "meal": "Breakfast incl.", "cancellation": "Free cancellation", "payment": "Pay by wire transfer", "price": "EUR 450", "basis": "for 2 nights for 2 guests", "path": "/hotel/portugal/lisbon/mid3/four/"}]}


def test_ratehawk_recipe_url_and_script_are_built_from_the_search():
    from datetime import date

    from myt_mcp.recipes import ratehawk_hotels_recipe

    r = ratehawk_hotels_recipe("Portugal", "Lisbon", date(2027, 5, 3), date(2027, 5, 5), 2, "price_asc", True, True, 4, 2)
    assert r["url"] == ("https://www.ratehawk.com/hotel/portugal/lisbon/?dates=03.05.2027-05.05.2027&guests=2&meal_types=breakfast&payment=freecancellation"
                        "&stars=4&sort=price.asc&page=1")
    assert r["expect_sort"] == "Price (low to high)" and "__MAX_PAGES__" not in r["script"] and "const MAX_PAGES = 2;" in r["script"]
    assert "zenpagination-button-next" in r["script"] and "page counter says" in r["script"]
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
    bad = dict(SAMPLE_RH, start_page=3)
    assert any("page 1" in p for p in offers_from_ratehawk([json.dumps(bad)], [], None, "Hotels")[2])
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


CARS_RESULT = {"ok": True, "form": {"pickup": "Faro Airport", "dropoff": "Faro Airport", "times": ["10:00", "10:00"], "dates": ["12 Apr, Mon", "17 Apr, Sat"], "age_residency": ["26 - 69 years", "Israel"]},
               "filters_ticked": ["Automatic"], "rows_read": 3, "reached_cap": False, "price_order": "ascending", "rows": [
    {"score": None, "company": "tangerine", "company_from": "logo file name", "seats": "5", "large_bags": "2", "small_bags": "1", "gearbox": "Automatic", "car": "Opel Corsa", "code_class": "EDAR • Economy",
     "pickup_place": "Meeting with an agent", "deposit": 2100, "excess": 1900, "insurance": "Basic with excess", "mileage_fuel": "Unlimited mileage • Fuel policy: Full to full", "extras": [],
     "price": 61.83, "currency": "EUR", "cancellation": "Free cancellation up to 48 hours before pick-up"},
    {"score": "5.8", "company": "Dollar", "company_from": "text", "seats": "4", "large_bags": "1", "small_bags": "1", "gearbox": "Automatic", "car": "Ford Focus", "code_class": "CDAR • Compact",
     "pickup_place": "Transfer to the rental place", "deposit": 200, "excess": None, "insurance": "Zero excess", "mileage_fuel": "Unlimited mileage • Fuel policy: Full to full", "extras": [],
     "price": 150.0, "currency": "EUR", "cancellation": "Free cancellation up to 48 hours before pick-up"},
    {"score": "7.0", "company": "Sixt", "company_from": "text", "seats": "5", "large_bags": "2", "small_bags": "2", "gearbox": "Manual", "car": "VW Golf", "code_class": "CDMR • Compact",
     "pickup_place": "Meeting with an agent", "deposit": 800, "excess": 1500, "insurance": "Basic with excess", "mileage_fuel": "Unlimited mileage • Fuel policy: Full to full", "extras": [],
     "price": 170.0, "currency": "EUR", "cancellation": "No free cancellation"}]}


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
    assert not rows.problems and rows.read == 3 and rows.total == 3
    by = {o.name: o for o in rows.offers}
    assert by["Opel Corsa (EDAR • Economy)"].fits is False and by["Ford Focus (CDAR • Compact)"].fits is True and by["VW Golf (CDMR • Compact)"].fits is False
    assert "logo's file name" in by["Opel Corsa (EDAR • Economy)"].details["company"] and by["Ford Focus (CDAR • Compact)"].details["company"] == "Dollar"
    assert by["Ford Focus (CDAR • Compact)"].details["deposit"] == "200" and by["Ford Focus (CDAR • Compact)"].flexible is True
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


def _part(run, part, parts, rows, read=3, **extra):
    head = {"ok": True, "header": "Lisbon: 443 accommodation options available", "sort": "Price (low to high)", "start_page": 1, "pages_read": 1,
            "price_order": "ascending", "stopped": None, "run": run, "rows_read": read, "part": part, "parts": parts}
    head.update(extra)
    cols = ["name", "price", "path"]
    common = {"stars": 4, "meal": "Breakfast incl.", "cancellation": "Free cancellation", "basis": "for 2 nights for 2 guests"}
    return json.dumps({**head, "cols": cols, "common": common, "path_base": "/hotel/portugal/lisbon/", "rows": rows})


def test_parts_are_joined_decoded_and_checked():
    from myt_mcp.sites import convert_all, expand
    a = _part("r1", 1, 2, [["Hotel A", "EUR 100", "mid1/a/"], ["Hotel B", "EUR 110", "mid2/b/"]])
    b = _part("r1", 2, 2, [["Hotel C", "EUR 120", "mid3/c/"]])
    plain = json.loads(expand(a))
    assert plain["rows"][0]["path"] == "/hotel/portugal/lisbon/mid1/a/" and plain["rows"][0]["meal"] == "Breakfast incl." and "cols" not in plain
    offers, sources, problems, by_price, _ = convert_all([{"site": "ratehawk_hotels", "result": a, "url": "u"}, {"site": "ratehawk_hotels", "result": b, "url": "u"}],
                                                          {"breakfast": True, "free_cancellation": True})
    assert not problems and [o.name for o in offers] == ["Hotel A", "Hotel B", "Hotel C"] and offers[0].fits is True and by_price
    assert offers[2].link == "https://www.ratehawk.com/hotel/portugal/lisbon/mid3/c/"
    # a missing part is refused, with the way to get it
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_hotels", "result": a, "url": "u"}], None)
    assert any("part(s) 2 of 2 are missing" in p and "__mytParts" in p for p in problems)
    # rows that do not add up to what the script read are refused
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_hotels", "result": _part("r2", 1, 1, [["Hotel A", "EUR 100", "mid1/a/"]], read=3), "url": "u"}], None)
    assert any("hold 1 rows but the script read 3" in p for p in problems)
    # two runs (price sort and rating sort) never count as parts of each other
    other = _part("r9", 1, 1, [["Hotel Z", "EUR 500", "mid9/z/"]], read=1)
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
async def test_a_minimal_compose_call_works_and_a_missing_hotel_source_is_refused():
    import json

    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    item = {"site": "ratehawk_hotels", "result": json.dumps(SAMPLE_RH), "url": "https://www.ratehawk.com/hotel/portugal/lisbon/?dates=03.05.2027-05.05.2027&guests=2&sort=price.asc&page=1"}
    async with Client(create_server(Settings())) as c:
        r = await c.call_tool("compose_answer", {"kind": "hotels", "site_results": [item], "wishes": {"breakfast": True, "free_cancellation": True},
                                                 "myt_supplier": {"Hotel Four": "not checked: test"}})
        d = r.structured_content
        assert d["ok"] is False and any("Arbitrip is neither in sources_read nor in not_checked" in x for x in d["problems"]) and not any("Ratehawk" in x for x in d["problems"])
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
    row = lambda n, price: {"name": f"H{n}", "stars": 3, "distance": "1 km", "score": "8.0", "reviews": "100 reviews", "room": "Double", "bed": None, "meal": "Breakfast incl.",
                            "cancellation": "Free cancellation", "payment": None, "price": f"EUR {price}", "basis": "for 2 nights for 2 guests", "path": f"/hotel/p/c/mid{n}/h{n}/", "p": 1}
    runs = [{"info": {"header": "Lisbon: 443 accommodation options available", "sort": "Price (low to high)", "page": "1"}, "rows": [row(1, 100), row(2, 110)]},
            {"info": {"header": None, "sort": "Price (low to high)", "page": "2"}, "rows": [row(3, 120)]}]
    text = answer_json(runs, "Price (low to high)")
    assert _json.loads(text)["price_order"] == "ascending" and _json.loads(text)["rows_read"] == 3
    offers, sources, problems, by_price, _ = convert_all([{"site": "ratehawk_hotels", "result": text, "url": "u"}], {"breakfast": True, "free_cancellation": True})
    assert not problems and len(offers) == 3 and by_price and sources[0].of == 443
    mixed = answer_json([{"info": {"header": None, "sort": "Price (low to high)", "page": "1"}, "rows": [row(1, 100), row(2, 300), row(3, 200)]}], "Price (low to high)")
    assert _json.loads(mixed)["price_order"] == "mixed"
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
