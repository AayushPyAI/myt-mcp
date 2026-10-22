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
                        "&stars=4.5&sort=price.asc&page=1")
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
    return json.dumps(base)


def test_arbitrip_url_carries_the_operators_filters_as_changes_from_the_agency_defaults(monkeypatch):
    import urllib.parse
    from datetime import date

    from myt_mcp.sites.arbitrip_hotels import arbitrip_hotels_recipe, results_url

    url, keys = results_url("PLACE", "CONTRACT", date(2027, 5, 3), date(2027, 5, 5), 2, 4, True, 250, 2.5)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["check_in"] == ["270503"] and q["check_out"] == ["270505"] and q["guests"] == ["2"] and q["contract_id"] == ["CONTRACT"] and q["max_distance"] == ["3"] and q["max_price_per_night"] == ["250"]
    assert json.loads(q["stars"][0]) == {"2": False, "3": False}                  # 4 stars and up = the default 2-5 minus 2 and 3
    assert json.loads(q["categories"][0]) == {"Apartment": True, "Other": True} and json.loads(q["review"][0]) == {"Poor": True}      # no filter the operator did not name
    assert json.loads(q["amenities"][0]) == {"BREAKFAST_INCLUDED": True} and q["sort"] == ["Price (Low to High)"]
    one, _ = results_url("P", "C", date(2027, 5, 3), date(2027, 5, 5), 2, 1, False, None, None)
    assert json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(one).query)["stars"][0]) == {"1": True} and "max_price_per_night" not in one and "amenities" not in one
    none, _ = results_url("P", "C", date(2027, 5, 3), date(2027, 5, 5), 2, None, False, None, None)
    assert json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(none).query)["stars"][0]) == {"1": True}
    monkeypatch.delenv("ARBITRIP_CONTRACT_ID", raising=False)
    assert arbitrip_hotels_recipe("Lisbon", date(2027, 5, 3), date(2027, 5, 5))["needs_contract_id"] is True
    monkeypatch.setenv("ARBITRIP_CONTRACT_ID", "CONTRACT")
    assert arbitrip_hotels_recipe("Lisbon", date(2027, 5, 3), date(2027, 5, 5), stars=4, limit=30)["filters_in_url"][-1] == "sort"
    assert arbitrip_hotels_recipe("Atlantis", date(2027, 5, 3), date(2027, 5, 5))["needs_place_id"] == "Atlantis"
    with pytest.raises(ValueError, match="children"):
        arbitrip_hotels_recipe("Lisbon", date(2027, 5, 3), date(2027, 5, 5), children_ages=[6])


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
    return json.dumps(base)


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


def test_ratehawk_hotels_refuses_a_list_with_a_filter_nobody_asked_for_or_a_search_still_running():
    from myt_mcp.sites import convert_all
    row = {"name": "H1", "stars": 4, "distance": "1 km", "score": "8.0", "reviews": "100 reviews", "room": "Double", "bed": None, "meal": "Breakfast incl.", "cancellation": "Free cancellation",
           "payment": None, "price": "EUR 300", "basis": "for 2 nights for 2 guests", "path": "/hotel/p/c/mid1/h1/", "p": 1}
    def result(**extra):
        d = {"ok": True, "header": "Lisbon: 57 accommodation options available", "sort": "Price (low to high)", "start_page": 1, "expected_start": 1, "offset": 0, "pages_read": 1, "rows_read": 1,
             "stopped": None, "price_order": "ascending", "header_settled": True, "filters_ticked": ["Breakfast included", "Free cancellation available"], "unlabelled_ticked": 0, "rows": [row]}
        d.update(extra)
        return json.dumps(d)
    wishes = {"breakfast": True, "free_cancellation": True}
    run = lambda text, w=wishes: convert_all([{"site": "ratehawk_hotels", "result": text, "url": "u"}], w)[2]
    assert run(result()) == []
    assert any("filters the operator did not ask for" in p and "Pool" in p for p in run(result(filters_ticked=["Breakfast included", "Free cancellation available", "Pool"])))
    assert any("did not ask for" in p for p in run(result(unlabelled_ticked=1)))
    assert run(result(unlabelled_ticked=1), {**wishes, "stars_min": 4}) == []                # star boxes are expected when the operator named stars
    assert any("still adding results" in p for p in run(result(header_settled=False)))
    assert any("did not ask for" in p for p in run(result(filters_ticked=["Breakfast included"]), {"free_cancellation": False, "breakfast": False}))


def _cars(rows, **head):
    base = {"ok": True, "form": {"pickup": "Faro Airport", "dropoff": "Faro Airport", "times": ["10:00", "10:00"], "dates": ["12 Apr, Mon", "17 Apr, Sat"], "age_residency": ["26 - 69", "Israel"]},
            "filters_ticked": [], "page_ticked": ["26 - 69 years"], "offset": 0, "rows_read": len(rows), "reached_cap": False, "price_order": "ascending", "rows": rows}
    base.update(head)
    return json.dumps(base)


def _car(name, price, seats="5", gearbox="Manual", company="greenmotion"):
    return {"score": "8.0", "company": company, "company_from": "text", "seats": seats, "large_bags": "1", "small_bags": "2", "gearbox": gearbox, "car": name, "code_class": "MDMR • Mini", "pickup_place": "Faro Airport",
            "deposit": 1200, "excess": 1100, "insurance": "Basic with excess", "mileage_fuel": "Unlimited mileage • Full to full", "extras": [], "price": price, "currency": "EUR", "cancellation": "Free cancellation"}


def test_ratehawk_cars_ask_first_wishes_and_hidden_filters():
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ratehawk_cars import cars_ask_gate, ratehawk_cars_recipe
    asked = cars_ask_gate(None, None, None, None, False)
    assert asked["ok"] is False and asked["searched"] is False and len(asked["ask_operator"]) == 4
    assert len(cars_ask_gate("automatic", None, None, None, False)["ask_operator"]) == 3 and cars_ask_gate(None, None, None, None, True) is None
    r = ratehawk_cars_recipe("Faro Airport", None, "2027-04-12", "10:00", "2027-04-17", "10:00", None, None, "26,69", "il", True, False, False, 40, False, 30, 30)
    assert "const SKIP = 30;" in r["script"] and "const MAX_CARS = 60;" in r["script"] and r["filters_to_tick"] == ["Automatic"]
    rows = [_car("Fiat Panda", 60, "4", "Manual"), _car("Opel Corsa", 62, "5", "Automatic"), _car("Jeep", 90, "5", "Automatic")]
    wishes = {"automatic": True, "min_seats": 5, "max_total": 80}
    offers, _, problems, _, notes = convert_all([{"site": "ratehawk_cars", "result": _cars(rows), "url": "u"}], wishes)
    assert not problems and [o.fits for o in offers] == [False, True, False]            # manual, too few seats, over budget
    manual, _, _, _, _ = convert_all([{"site": "ratehawk_cars", "result": _cars(rows), "url": "u"}], {"manual": True})
    assert [o.fits for o in manual] == [True, False, False]
    sticky = _cars(rows, page_ticked=["26 - 69 years", "Zero excess"])
    assert any("did not ask for (Zero excess)" in p for p in convert_all([{"site": "ratehawk_cars", "result": sticky, "url": "u"}], wishes)[2])
    asked_for = _cars(rows, filters_ticked=["Zero excess"], page_ticked=["26 - 69 years", "Zero excess"])
    assert convert_all([{"site": "ratehawk_cars", "result": asked_for, "url": "u"}], {"zero_excess": True})[2] == []
    later = _cars(rows, offset=30)
    assert any("cars 31 to 33" in n and "not the cheapest overall" in n for n in convert_all([{"site": "ratehawk_cars", "result": later, "url": "u"}], None)[4])


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
    return json.dumps(base)


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
    base = {"ok": True, "page_ticked": ["One way", "All routes"], "settled": True, "all_loaded": True, "cards_total": len(rows), "offset": 0, "rows": rows}
    base.update(head)
    return json.dumps(base)


def _train(no="9511", dep="08:14", arr="09:49", changes="Direct", classes=None, route="Firenze S.M. Novella \u2192 Roma Termini", date_text="23 November, Mon", tag=None):
    return {"train": no, "route": route, "tag": tag, "dep": dep, "travel": "1 hr 35 min", "arr": arr, "date": date_text, "changes": changes,
            "classes": classes or [{"name": "Standard", "price": 61.38, "currency": "EUR"}, {"name": "Comfort", "price": 52.58, "currency": "EUR"}, {"name": "Premier", "price": 61.38, "currency": "EUR"}]}


def test_ratehawk_trains_ask_first_station_ids_filters_and_checks():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.ratehawk_trains import ratehawk_trains_recipe
    r = ratehawk_trains_recipe("Firenze Santa Maria Novella", "Roma Termini", date(2026, 11, 23), "08:00", 2, "direct", "comfort", limit=30, offset=30)
    assert r["url"] == "https://www.ratehawk.com/railway/?from=8306421&to=8308409&date=2026-11-23&time=08%3A00&adt=2"
    assert 'const CHANGES = "Direct route"' in r["script"] and 'const CLASS = "Comfort"' in r["script"] and "const SKIP = 30;" in r["script"] and "const LIMIT = 30;" in r["script"]
    assert ratehawk_trains_recipe("Atlantis", "Roma Termini", date(2026, 11, 23), "08:00")["needs_station_id"] == "Atlantis"
    with pytest.raises(ValueError, match="HH:MM"):
        ratehawk_trains_recipe("Roma Termini", "Napoli", date(2026, 11, 23), "8am")
    exp = ratehawk_trains_recipe("Firenze Santa Maria Novella", "Roma Termini", date(2026, 11, 23), "08:00", 2)["expect"]
    run = lambda text, w=None: convert_all([{"site": "ratehawk_trains", "result": text, "url": "u"}], w if w is not None else {"expect": exp})
    offers, sources, problems, _, notes = run(_trains([_train(), _train("8505", "08:33", "10:15", tag="The cheapest option")]))
    assert not problems and len(offers) == 6 and offers[0].group == "Firenze Santa Maria Novella to Roma Termini, 23 Nov 2026" and (sources[0].read, sources[0].of) == (2, 2)
    assert offers[0].price_total == 61.38 and offers[0].details["class_fare"] == "Standard from 61.38 EUR" and "whole group" in offers[0].price_basis and any("2 trains" in n or "lists 2" in n for n in notes)
    assert any("not Firenze Santa Maria Novella to Roma Termini" in p for p in run(_trains([_train(route="Milano Centrale \u2192 Venezia S. Lucia")]))[2])
    assert any("not 2026-11-23" in p for p in run(_trains([_train(date_text="24 November, Tue")]))[2])
    assert any("filters are not as asked" in p and "Direct route" in p for p in run(_trains([_train()], page_ticked=["One way", "Direct route"]))[2])
    assert any("still adding trains" in p for p in run(_trains([_train()], settled=False))[2])
    comfort = dict(exp, **{"class": "comfort", "changes": "direct"})
    got = run(_trains([_train(), _train("8999", changes="1 change")], page_ticked=["One way", "Direct route", "Comfort"]), {"expect": comfort, "max_total": 60})
    assert not got[2] and [o.fits for o in got[0]] == [True, False] and all(o.details["class_fare"].startswith("Comfort") for o in got[0])


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
    base = {"ok": True, "route": ["FLR", "LIS"], "date": "Sat, 6 Mar", "travellers": 3, "cabin": "Economy", "results_total": 97, "direct_only": False, "tabs": {}, "ads_skipped": 2, "unparsed": [],
            "sorts": [{"sort": "Best", "shown_as": "Best", "read": 2}, {"sort": "Cheapest", "shown_as": "Cheapest", "read": 2}], "rows": rows}
    base.update(head)
    return json.dumps(base)


def _sk(sort, airlines, dep, arr, total, per, direct=False, later=None, via="one stop in Barcelona", duration="8 hours 5 minutes"):
    return {"sort": sort, "per": per, "total": total, "airlines": airlines, "from": "Florence", "dep": dep, "to": "Lisbon", "arr": arr, "later": later, "direct": direct, "duration": duration, "via": None if direct else via}


def test_skyscanner_asks_first_has_the_url_and_its_rows_are_comparison_only():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.skyscanner import skyscanner_recipe
    r = skyscanner_recipe("FLR", "LIS", date(2027, 3, 6), 2, [6, 8], "economy", True, 20)
    assert r["url"] == "https://www.skyscanner.net/transport/flights/flr/lis/270306/?adultsv2=2&childrenv2=6%7C8&cabinclass=economy&rtn=0&preferdirects=true&currency=EUR"
    assert 'const SORTS = ["Best", "Cheapest"];' in r["script"] and "const LIMIT = 20;" in r["script"] and r["expect"]["leg"] == "FLR to LIS, 06 Mar 2027"
    with pytest.raises(ValueError, match="IATA"):
        skyscanner_recipe("Florence", "LIS", date(2027, 3, 6))
    exp = skyscanner_recipe("FLR", "LIS", date(2027, 3, 6), 2, [6])["expect"]
    run = lambda text, e=exp: convert_all([{"site": "skyscanner", "result": text, "url": "u"}], {"expect": e})
    rows = [_sk("Best", "Portugalia Airlines", "12:20", "14:30", 414, 138, direct=True, duration="3 hours 10 minutes"), _sk("Best", "Vueling Airlines", "13:10", "16:55", 340, 113),
            _sk("Cheapest", "Vueling Airlines", "21:00", "08:30", 218, 73, later="one day"), _sk("Cheapest", "Vueling Airlines", "13:10", "16:55", 340, 113)]
    offers, sources, problems, _, notes = run(_sky(rows))
    assert not problems and len(offers) == 3 and all(o.quotable is False and o.group == "FLR to LIS, 06 Mar 2027" for o in offers)         # the same ticket in both tabs is one offer
    assert offers[0].details["per_person"].startswith("138 EUR") and offers[0].details["stops"] == "Direct flight" and "one day later" in offers[2].name
    assert any("sponsored" in n for n in notes) and any("only compares" in n for n in notes)
    assert any("not FLR to LIS" in p for p in run(_sky(rows, route=["FCO", "LIS"]))[2])
    assert any("not Sat, 6 Mar" in p for p in run(_sky(rows, date="Sun, 7 Mar"))[2])
    assert any("counts 2 travellers, not 3" in p for p in run(_sky(rows, travellers=2))[2])
    assert any("cabin 'Business'" in p for p in run(_sky(rows, cabin="Business"))[2])
    assert any("stop filters" in p for p in run(_sky(rows, direct_only=True))[2])
    assert any("does not know" in p for p in run(_sky(rows, unparsed=["Flight option 3: something new"]))[2])
    assert any("both the Best and the Cheapest" in p for p in run(_sky(rows, sorts=[{"sort": "Best", "shown_as": "Best", "read": 2}]))[2])
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
