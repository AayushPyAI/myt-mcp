"""The operator's own words against the '(operator)' labels (30 Oct 2026): a value the assistant added is no longer called the operator's, and a made-up limit hides no row."""

import pytest
from mcp import Client

from myt_mcp import request_check as rc
from myt_mcp.app import create_server
from myt_mcp.config import Settings

REQUEST = "Hotel in Lisbon 6-13 March for 2 adults, breakfast included, free cancellation, at least 4 stars, budget 150 per night. Transfer from the airport on arrival."
FILTERS = ["Breakfast included (operator)", "Free cancellation (operator)", "4+ stars (operator)", "budget up to 150 per night, 1050 for 7 night(s) (operator)", "Guests: 2 adults (operator)",
           "within 1.5 km of the centre (operator)", "Manual gearbox (operator)", "Zero excess (operator)", "Flight tracking (operator)", "Walking tour in the morning (operator)",
           "Day 2027-03-07 and 2 adults (operator)", "Date and group as the operator said (operator)", "Prices in EUR (server default)", "Driver age 30 (default: ask)"]


def test_a_filter_the_request_does_not_support_is_relabelled_and_the_others_are_kept():
    out, changed = rc.relabel(FILTERS, REQUEST)
    assert changed == ["within 1.5 km of the centre", "Manual gearbox", "Zero excess", "Flight tracking", "Walking tour in the morning"]
    assert [f for f, o in zip(FILTERS, out) if f == o] == [FILTERS[0], FILTERS[1], FILTERS[2], FILTERS[3], FILTERS[4], FILTERS[10], FILTERS[11], FILTERS[12], FILTERS[13]]
    assert out[5] == f"within 1.5 km of the centre ({rc.ASSUMED})" and "(operator" not in out[5]
    assert rc.relabel(["Zero excess (operator; the page has no box)"], "a car please")[0] == [f"Zero excess ({rc.ASSUMED}; the page has no box)"]


def test_no_request_changes_nothing_and_a_line_it_cannot_judge_is_left_alone():
    assert rc.relabel(FILTERS, None) == (FILTERS, []) and rc.relabel(FILTERS, "  ") == (FILTERS, [])
    assert rc.relabel(["Something new and odd (operator)"], "anything")[1] == []


@pytest.mark.parametrize("request_text,line,expected", [
    ("a walk of about 1,5 km from the centre", "within 1.5 km of the centre (operator)", True),
    ("close to the centre", "within 1.5 km of the centre (operator)", False),            # 'close' is not a number the operator gave
    ("two adults and a child of 7", "Guests: 2 adults and child 7 (operator)", True),
    ("a couple", "Guests: 2 adults (operator)", True),
    ("automatic please", "Automatic gearbox (operator)", True),
    ("an automatic car", "Manual gearbox (operator)", True),                                 # same topic (gearbox): the topic is judged, not the value
    ("a sedan, no more than 80 euro", "budget up to 80 EUR for the whole rental (operator)", True),
    ("a sedan", "budget up to 80 EUR for the whole rental (operator)", False),
    ("food tour, about two hours", "Title has one of: food, tour (operator)", True),
    ("a day trip to Sintra", "Title has one of: food, tour (operator)", False),
])
def test_topic_and_number_must_both_be_in_the_request(request_text, line, expected):
    assert rc.line_supported(line, request_text) is expected


def test_wishes_the_request_does_not_support_are_not_applied_and_are_named():
    wishes = {"breakfast": True, "free_cancellation": True, "stars_min": 4, "max_distance_km": 1.5, "max_total": 1050, "flight_tracking": True, "vehicle": "comfortable"}
    kept, left = rc.drop_unsupported(wishes, REQUEST)
    assert kept == {"breakfast": True, "free_cancellation": True, "stars_min": 4, "max_total": 1050}
    assert left == ["within 1.5 km of the centre", "flight tracking", "a comfortable vehicle"] or set(left) == {"within 1.5 km of the centre", "flight tracking", "a comfortable vehicle"}
    assert rc.drop_unsupported(wishes, "") == (wishes, [])
    assert rc.not_applied_line([]) is None and "Not applied" in rc.not_applied_line(left)
    shared, left2 = rc.drop_unsupported({"max_price_pp": 50.0, "max_hours": 4.0, "min_rating_10": 9.0}, "a tour under 50 euro for up to 4 hours")
    assert shared == {"max_price_pp": 50.0, "max_hours": 4.0} and left2 == ["a minimum rating"]


def test_the_operators_answers_to_the_assistants_questions_count_as_their_words():
    first = "Car hire from Lisbon airport (Humberto Delgado), pick up 7 March 2027 at 10:00, return 12 March 2027 at 10:00, driver age 35."
    answers = "Automatic. 4 seats, 2 large bags. No preference on excess. Up to €300."
    lines = ["Automatic gearbox (operator)", "budget up to 300 EUR for the whole rental (operator)", "at least 4 seats (operator)", "room for 2 large bags (operator)"]
    assert rc.relabel(lines, f"{first}\n{answers}") == (lines, [])
    assert rc.relabel(lines, first)[1] == ["Automatic gearbox", "budget up to 300 EUR for the whole rental", "at least 4 seats", "room for 2 large bags"]   # the first message alone proves none of them
    kept, left = rc.drop_unsupported({"max_price": 300.0}, f"{first}\n{answers}")
    assert kept == {"max_price": 300.0} and left == []
    assert rc.drop_unsupported({"max_price": 300.0}, first)[1] == ["at most 300 EUR per person"]


def _transfer(name, tracking, price):
    return {"group": "Lisbon Airport (LIS) to Hotel, 7 Mar 2027", "source": "Kiwitaxi", "name": name, "price_total": price, "currency": "EUR", "price_basis": "per vehicle", "quotable": True,
            "details": {"flight_tracking": tracking}, "link": "https://kiwitaxi.test/x"}


async def _compose(**extra):
    args = {"kind": "transfers", "offers": [_transfer("Comfort sedan", "not shown", 40.0), _transfer("Standard sedan", "yes", 45.0)], "filters_used": ["Flight tracking (operator)", "Day 2027-03-07 and 2 adults (operator)"],
            "sources_read": [{"name": "Kiwitaxi", "read": 2, "of": 2, "link": "https://kiwitaxi.test/x"}], "pickup_time": "10:00", **extra}
    async with Client(create_server(Settings())) as c:
        return (await c.call_tool("compose_answer", args)).structured_content


@pytest.mark.anyio
async def test_compose_answer_does_not_hide_rows_for_flight_tracking_the_operator_never_asked_for():
    asked = await _compose(request="Transfer from the airport to the hotel on 7 March, 2 adults, please track my flight")
    assert "Flight tracking (operator)" in asked["answer"] and "not confirmed" in asked["answer"]            # asked: a row that does not say yes stays unconfirmed (as before)
    not_asked = await _compose(request="Transfer from the airport to the hotel on 7 March, 2 adults")
    assert f"Flight tracking ({rc.ASSUMED})" in not_asked["answer"] and "Flight tracking (operator)" not in not_asked["answer"]
    assert "not confirmed" not in not_asked["answer"] and "Day 2027-03-07 and 2 adults (operator)" in not_asked["answer"]
    without = await _compose()
    assert "were not checked against it" in without["answer"] and "Flight tracking (operator)" in without["answer"]


# ---------- a source of the earlier answer is not lost when the same kind is composed again (B1) ----------

def _tour(source, name, price):
    return {"group": "Food tour", "source": source, "name": name, "price_total": price, "currency": "EUR", "price_basis": "per person", "quotable": True, "link": "https://x.test/" + name.replace(" ", "")}


async def _activities(offers, sources, **extra):
    args = {"kind": "activities", "offers": offers, "sources_read": sources, "filters_used": ["Date and group as the operator said (operator)"], **extra}
    async with Client(create_server(Settings())) as c:
        return (await c.call_tool("compose_answer", args)).structured_content


GYG = ([_tour("Ofran activities", "Fado night", 60.0), _tour("Ofran activities", "Pastel class", 45.0)], [{"name": "Ofran activities", "read": 2, "of": 2, "link": "https://x.test/a"}])
SECOND = ([_tour("TAP tours", "Sintra day", 90.0)], [{"name": "TAP tours", "read": 1, "of": 1, "link": "https://x.test/b"}])


@pytest.mark.anyio
async def test_a_second_compose_of_the_same_kind_and_request_keeps_the_first_source():
    first = await _activities(*GYG, request="food tours in Lisbon on 7 March")
    assert first["ok"] and "Fado night" in first["answer"]
    second = await _activities(*SECOND, request="Food tours in Lisbon on 7 March!")        # the same words, other spelling of the stops
    assert second["ok"] and "Sintra day" in second["answer"] and "Fado night" in second["answer"] and "Pastel class" in second["answer"]
    assert "Carried from the earlier answer of this kind" in second["answer"] and "Ofran activities (2 rows)" in second["answer"]
    third = await _activities(*SECOND, request="food tours in Lisbon on 7 March")          # the carried rows are kept for the next call too
    assert "Fado night" in third["answer"] and "Ofran activities" in third["answer"]


@pytest.mark.anyio
async def test_nothing_is_carried_for_another_request_another_kind_or_a_source_put_in_not_checked():
    await _activities(*GYG, request="food tours in Lisbon on 7 March")
    other = await _activities(*SECOND, request="a day trip to Porto on 9 March")
    assert "Fado night" not in other["answer"] and "Carried from" not in other["answer"]
    await _activities(*GYG, request="food tours in Lisbon on 7 March")
    skipped = await _activities(*SECOND, request="food tours in Lisbon on 7 March", not_checked=[{"name": "Ofran activities", "reason": "block"}])
    assert "Fado night" not in skipped["answer"]


# ---------- D: cabin from the request, the tracking note, iWay's time, the server's own check ----------

def _tap(name, cabin, fits=True):
    from myt_mcp.compose import Offer
    return Offer(group="TLV to LIS, 7 Mar 2027", source="TAP", name=name, price_total=500.0, currency="EUR", fits=fits, details={"fare": f"DISCOUNT ({cabin})" if cabin else "DISCOUNT"})


def test_the_cabin_the_operator_names_is_taken_from_the_request():
    from myt_mcp.wishes import cabin_in, judge_cabin
    assert [cabin_in(t) for t in ("economy please", "in Business class", "Premium Economy seats", "first class", "economy or business", "a business trip", None)] == ["economy", "executive", "premium", "first", None, None, None]
    eco, exe, unnamed = _tap("TP1", "Economy"), _tap("TP2", "Executive"), _tap("TP3", None)
    other = _tap("TP4", "Executive"); other.source = "SATA"
    note = judge_cabin([eco, exe, unnamed, other], "economy")
    assert eco.fits is True and exe.fits is False and unnamed.unconfirmed == ["cabin"] and other.fits is True and "taken from the operator's message" in note
    assert judge_cabin([_tap("TP5", "Economy")], "economy") is None


def test_the_tracking_note_names_a_leg_written_two_ways_once():
    from myt_mcp.compose import Offer, tracking_unconfirmed
    mk = lambda group: Offer(group=group, source="Kiwitaxi", name="Comfort", price_total=40.0, currency="EUR", quotable=True, fits=True, details={"flight_tracking": "not shown"})
    note = tracking_unconfirmed([mk("Praça do Comércio -> Lisbon Airport (LIS), 19 Jan 2027"), mk("Praça do Comércio to Lisbon Airport (LIS), 19 Jan 2027")])
    assert note.count("19 Jan 2027") == 1


def test_a_page_time_that_does_not_fit_the_distance_is_not_written_as_a_fact():
    from myt_mcp.sites.iway_transfers import route_text
    assert route_text(["9", "2h 0m"]) == "9 km (the page's time, 2h 0m, does not fit that distance: not used)"
    assert route_text(["30", "45m"]) == "30 km, about 45m" and route_text(["9", ""]) == "9 km" and route_text(None) == "not shown"


@pytest.mark.anyio
async def test_compose_answer_holds_its_own_text_to_the_check_answer_list_and_a_normal_answer_passes():
    out = await _compose(request="Transfer from the airport on 7 March, please track my flight")
    assert out["ok"] and "answer_check_missing" not in out
