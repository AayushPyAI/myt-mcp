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
            "kind": "hotels", "filters_used": ["breakfast (operator)", "free cancellation (operator)"], "sources_read": [], "not_checked": [], "offers": [],
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
