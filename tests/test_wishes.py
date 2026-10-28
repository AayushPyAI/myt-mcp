"""The operator's wishes are judged on every row of an answer, whichever source it came from (28 Oct 2026)."""

from myt_mcp.compose import Offer
from myt_mcp.wishes import hours_range, judge_activities, shared_wishes


def test_the_wishes_of_all_the_runs_are_put_together_with_the_strictest_value_and_ratings_on_ten_points():
    carried = {("viator_find", "a"): {"wishes": {"expect": {"max_price": 50, "max_hours": 4, "min_rating": 4.5, "free_cancellation": True}, "free_cancellation": True}},
               ("booking_attractions", "b"): {"wishes": {"expect": {"min_rating_wish": 9, "min_rating": ["4.5"]}}}, ("x", "c"): {"wishes": {"expect": {"max_price": 40}}}}
    assert shared_wishes(carried, None) == {"max_price_pp": 40, "max_hours": 4, "min_rating_10": 9.0, "free_cancellation": True}
    assert shared_wishes({}, {"max_price": 30, "expect": {}}) == {"max_price_pp": 30}
    assert shared_wishes({}, None) == {}


def test_hours_are_read_from_every_way_the_sources_write_a_duration():
    assert hours_range("2 hours 30 minutes") == (2.5, 2.5)
    assert hours_range("1 hour - 5 hours") == (1.0, 5.0)
    assert hours_range("1 to 4 hours") == (1.0, 4.0)
    assert hours_range("4 hours (approx.)") == (4.0, 4.0)
    assert hours_range("1 hour 30 minutes to 3 hours 30 minutes") == (1.5, 3.5)
    assert round(hours_range("50 minutes")[0], 2) == 0.83
    assert hours_range("not shown on the card") is None and hours_range(None) is None


def _row(source, name, price, basis, link, details, flexible=True, quotable=True, fits=None):
    return Offer(group="g", source=source, name=name, price_total=price, currency="EUR", price_basis=basis, link=link, quotable=quotable, flexible=flexible, fits=fits, details=details)


def test_a_maximum_per_person_hours_and_a_rating_are_judged_on_the_exact_price_rows_and_on_other_sources_lists():
    """28 Oct 2026: 80-130 EUR per person tuk tuk tours, 8-hour day trips and a pick with no rating all 'met every wish'."""
    page = "https://www.viator.com/tours/Lisbon/Walk/d538-1"
    rows = [
        _row("Viator", "Walk list", 3, "'from' price per person", page, {"duration": "2 hours 30 minutes", "rating": "4.9 (757 reviews)"}, quotable=False),
        _row("Viator", "Walk - English", 6.0, "whole group (2 travellers; 2 Adults x €3.00)", page, {"duration": "2 hours 30 minutes (approx.)"}),                         # price, hours and rating (from the list row) are fine
        _row("Viator", "Tuk tuk", 260.0, "whole group (2 travellers; 2 Travelers x €130.00)", "https://www.viator.com/tours/Lisbon/Tuk/d538-2", {"duration": "4 hours (approx.)"}),   # 130 per person
        _row("Viator", "No rating", 40.0, "whole group (2 travellers; 2 Adults x €20.00)", "https://www.viator.com/tours/Lisbon/Other/d538-3", {"duration": "3 hours"}),           # rating cannot be found
        _row("Booking.com attractions", "Day trip", 30.0, "'from' price = the lowest", "https://www.booking.com/attractions/pt/trip.html", {"duration": "9 hours", "rating": "9.2 (790 reviews)"}, quotable=False),
        _row("Booking.com attractions", "Bike", 16.0, "'from' price = the lowest", "https://www.booking.com/attractions/pt/bike.html", {"duration": "4 hours - 5 hours", "rating": "9.6 (377 reviews)"}, quotable=False),
    ]
    judge_activities(rows, {"max_price_pp": 50, "max_hours": 4, "min_rating_10": 9.0})
    walk_list, walk, tuk, norating, trip, bike = rows
    assert walk.fits is True and walk_list.fits is True
    assert tuk.fits is False                                                   # 130 per person
    assert norating.fits is None and norating.unconfirmed == ["rating"]
    assert trip.fits is False                                                  # 9 hours
    assert bike.fits is None and bike.unconfirmed == ["duration (a range that goes over the limit)"]      # 4-5 hours: the operator may choose the short one


def test_a_free_cancellation_wish_leaves_a_row_with_unknown_terms_unconfirmed_and_no_wishes_change_nothing():
    row = _row("Booking.com attractions", "Walk", 38.0, "whole group (2 travellers; 2 x Adult at 19.00)", "https://www.booking.com/attractions/pt/walk.html", {"duration": "3 hours"}, flexible=None)
    judge_activities([row], {})
    assert row.fits is None and row.unconfirmed == []
    judge_activities([row], {"free_cancellation": True})
    assert row.fits is None and row.unconfirmed == ["free cancellation"]


# ---------- hotels: stars and distance judged on every row (28 Oct 2026) ----------

def _hotel(source, name, price, stars, distance, quotable=True, fits=True):
    return Offer(group="Hotels", source=source, name=name, price_total=price, currency="EUR", price_basis="whole stay", quotable=quotable, fits=fits, flexible=True, link=None,
                 details={"stars": stars, "score": 8.0 if stars else None, "reviews": 300 if stars else None, "distance_from_centre": distance, "meal": "Breakfast included",
                          "cancellation": "Free cancellation", "room_bed": "Double"})


def test_stars_and_distance_asked_on_one_hotel_recipe_count_for_every_hotel_row():
    from myt_mcp.wishes import judge_hotels
    carried = {("ratehawk_hotels", "a"): {"wishes": {"stars_min": 4, "max_distance_km": 2.0, "breakfast": True}}, ("arbitrip_hotels", "b"): {"wishes": {"stars_min": 3, "max_distance_km": 5.0}},
               ("bensaude_hotels", "c"): {"wishes": {"breakfast": True, "stars_min": None, "max_distance_km": None}}}
    assert shared_wishes(carried, None) == {"stars_min": 4, "max_distance_km": 2.0}
    rows = [_hotel("RateHawk", "Czar Lisbon Hotel", 510, 4, "1.8 km from the Lisbon center"), _hotel("RateHawk", "Too far", 400, 4, "3.4 km from the Lisbon center"), _hotel("RateHawk", "Three stars", 300, 3, "500 m from the Lisbon center"),
            _hotel("Bensaude (the hotel's own website)", "NEAT Hotel Avenida - Standard", 467, None, None), _hotel("Arbitrip", "Hotel Principe Real", 414, 4, "(0.9 km from center)", quotable=False, fits=None)]
    judge_hotels(rows, shared_wishes(carried, None))
    czar, far, three, neat, arb = rows
    assert czar.fits is True and not czar.unconfirmed
    assert far.fits is False and three.fits is False                                  # a clear miss on the distance / on the stars
    assert neat.fits is None and neat.unconfirmed == ["stars", "distance from the centre"]      # the page shows neither: marked, never a pick
    assert arb.fits is None and not arb.unconfirmed                                    # it shows both and meets them: its own state is not touched
    judge_hotels(rows, {})                                                              # no wish: nothing changes
    assert neat.fits is None


def test_the_neat_hotel_of_the_azores_is_not_the_best_fit_of_a_lisbon_search_when_stars_and_distance_were_asked():
    """The real 28 Oct 2026 answer: a Bensaude row with stars, score, reviews and distance all 'not shown' was 'Best fit, meets every wish'."""
    from myt_mcp.compose import NotChecked, SourceRead, compose
    from myt_mcp.wishes import judge_hotels
    rows = [_hotel("Bensaude (the hotel's own website)", "NEAT Hotel Avenida - Standard - Winter 26/27", 467, None, None), _hotel("RateHawk", "Czar Lisbon Hotel", 510, 4, "1.8 km from the Lisbon center"),
            _hotel("RateHawk", "Quinta Colina by Shiadu", 557, 4, "548 m from the Lisbon center")]
    judge_hotels(rows, {"stars_min": 4, "max_distance_km": 2.0})
    out = compose("hotels", ["Breakfast included (operator)", "4+ stars (operator)", "within 2 km of the centre (operator)"],
                  [SourceRead(name="RateHawk", read=2, of=255, link="https://x.test/r"), SourceRead(name="Bensaude (the hotel's own website)", read=1, of=1, link="https://x.test/b")],
                  [NotChecked(name="Booking.com", reason="could not be read: not connected")], rows, {}, None, True, "")
    text = out["answer"]
    pick = {line.split("|")[0].strip(): line for line in text.splitlines() if line.startswith(("Best fit", "Recommended", "Cheapest"))}
    assert out["ok"], out.get("problems")
    assert "Czar Lisbon Hotel" in text.split("Best fit")[1].split("\n")[0] and "NEAT" not in text.split("Best fit")[1].split("\n")[0]
    assert "not confirmed: stars, distance from the centre" in text


# ---------- transfers: a comfortable vehicle (28 Oct 2026) ----------

def _car(name, price, fits=True):
    return Offer(group="Transfers", source="RateHawk Transfers", name=name, price_total=price, currency="EUR", price_basis="per vehicle, one way", quotable=True, fits=fits, flexible=True,
                 details={"capacity": "up to 3 people / 3 bags", "waiting_time": "60 min", "cancellation": "Free cancellation 24h before the trip", "provider": None, "meeting_point": "Meeting with a plate", "flight_tracking": "yes"})


def test_a_comfortable_vehicle_is_judged_on_the_class_of_every_transfer_row():
    from myt_mcp.wishes import comfort_of, comfort_unconfirmed
    assert [comfort_of(n) for n in ("Micro: Opel Corsa", "Economy: Toyota Prius", "Comfort: VW Passat", "Electro Comfort: Chevy Bolt EUV", "Business MPV: Mercedes GL", "First class: Mercedes S Class",
                                     "Comfort (Sedan comfort for 4 passengers)", "Premium Minibus (Smart choice for 6 travelers)", "Business (Perfect for business travelers)")] == [False, False, True, True, True, True, True, True, True]
    assert [comfort_of(n) for n in ("MPV: Toyota Highlander", "Minivan: Honda Odyssey", "Minibus: VW T5", "Bus: Ford E-450", "Minivan 4PAX (Fits 4 bags, not just 3)", "Minibus 7PAX (Most efficient for 7 people)", "class not shown: x")] == [None] * 7
    rows = [_car("Micro: Opel Corsa,Renault Clio", 14), _car("Economy: Toyota Prius", 15), _car("Comfort: VW Passat", 16), _car("MPV: Toyota Highlander", 18), _car("Business: Mercedes E Class", 22)]
    note = comfort_unconfirmed(rows)
    assert [o.fits for o in rows] == [False, False, True, None, True] and rows[3].unconfirmed == ["vehicle comfort"]
    assert "2 Micro/Economy row(s)" in note and "1 row(s) of a class that says nothing about comfort" in note
    assert comfort_unconfirmed([_car("Comfort: VW Passat", 16)]) is None


def test_the_real_transfer_answer_names_a_comfort_car_as_best_fit_not_the_micro():
    from myt_mcp.compose import SourceRead, compose
    from myt_mcp.wishes import comfort_unconfirmed
    rows = [_car("Micro: Opel Corsa,Renault Clio", 14), _car("Economy: Toyota Prius", 15), _car("Comfort: VW Passat, Hyundai Sonata", 16), _car("MPV: Toyota Highlander", 18), _car("Business: Mercedes E Class", 22)]
    note = comfort_unconfirmed(rows)
    out = compose("transfers", ["Comfortable tab (operator)", "With flight tracking (operator)"], [SourceRead(name="RateHawk Transfers", read=5, of=5, link="https://x.test/t")], [], rows, {}, "17:50", True, note or "")
    assert out["ok"], out.get("problems")
    best = out["answer"].split("Best fit")[1].split("\n")[0]
    assert "Comfort: VW Passat" in best and "Micro" not in best
    assert "A comfortable vehicle was asked" in out["answer"]


# ---------- through the real compose_answer tool ----------

import pytest


def _typed(source, name, price, details, group, basis="whole stay"):
    return {"group": group, "source": source, "name": name, "price_total": price, "currency": "EUR", "price_basis": basis, "quotable": True, "fits": True, "flexible": True, "details": details}


@pytest.mark.anyio
async def test_compose_answer_judges_the_stars_and_distance_of_every_hotel_row_and_a_comfortable_vehicle_of_every_transfer_row():
    from mcp import Client
    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    from myt_mcp.services import Services
    hotel = lambda name, price, stars, dist: _typed("Direct hotel site", name, price, {"stars": stars, "score": 8.1 if stars else None, "reviews": 300 if stars else None, "distance_from_centre": dist,
                                                                                      "meal": "Breakfast included", "cancellation": "Free cancellation", "room_bed": "Double"}, "Hotels")
    car = lambda name, price: _typed("Kiwitaxi", name, price, {"capacity": "up to 4 people / 3 bags", "waiting_time": "not shown", "cancellation": "free", "provider": "not shown", "meeting_point": "not shown"}, "LIS to hotel", "per vehicle")
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        hotels = (await c.call_tool("compose_answer", {
            "kind": "hotels", "wishes": {"stars_min": 4, "max_distance_km": 2.0}, "filters_used": ["4+ stars (operator)", "within 2 km of the centre (operator)"],
            "sources_read": [{"name": "Direct hotel site", "read": 3, "of": 3, "link": "https://x.test/h"}], "not_checked": [],
            "offers": [hotel("NEAT Hotel Avenida", 467, None, None), hotel("Czar Lisbon Hotel", 510, 4, "1.8 km from the Lisbon center"), hotel("Far hotel", 400, 4, "3.4 km from the Lisbon center")]})).structured_content
        transfers = (await c.call_tool("compose_answer", {
            "kind": "transfers", "pickup_time": "17:50", "filters_used": ["Comfortable tab (operator)"],
            "sources_read": [{"name": "Kiwitaxi", "read": 3, "of": 3, "link": "https://x.test/k"}], "not_checked": [],
            "offers": [car("Micro (Opel Corsa)", 14), car("Comfort (Sedan comfort for 4 passengers)", 40), car("Minivan 4PAX (Fits 4 bags)", 50)]})).structured_content
    assert hotels["ok"], hotels.get("problems")
    best = hotels["answer"].split("Best fit")[1].split("\n")[0]
    assert "Czar Lisbon Hotel" in best and "NEAT" not in best and "not confirmed: stars, distance from the centre" in hotels["answer"] and "Far hotel" not in hotels["answer"].split("Pick")[0]
    assert transfers["ok"], transfers.get("problems")
    best = transfers["answer"].split("Best fit")[1].split("\n")[0]
    assert "Comfort (Sedan comfort" in best and "Micro" not in best and "not confirmed: vehicle comfort" in transfers["answer"] and "A comfortable vehicle was asked" in transfers["answer"]
