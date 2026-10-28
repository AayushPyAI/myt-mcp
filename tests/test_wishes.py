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
