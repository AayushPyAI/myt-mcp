from myt_mcp.labels import activity_glance, cars_glance, discount_pct, flights_glance, free_cancellation


def test_discount_pct_and_free_cancellation_text():
    assert discount_pct(36, 72) == 50 and discount_pct(100, 100) is None and discount_pct(None, 5) is None
    assert free_cancellation("Cancel for free until Nov 19") is True
    assert free_cancellation("Non-refundable") is False
    assert free_cancellation("Free cancellation before 10:00; no refund after") is True
    assert free_cancellation("") is None and free_cancellation(None) is None


def test_activity_glance_picks_cheapest_and_cheapest_free_cancellation():
    out = activity_glance([
        {"option": "A", "time": "10:00", "price": 46.0, "price_before_discount": 92.0, "free_cancellation": False},
        {"option": "A", "time": "14:30", "price": 88.0, "free_cancellation": False},
        {"option": "B", "time": "10:00", "price": 60.0, "free_cancellation": True, "cancellation": "Cancel for free until Nov 19"},
        {"option": "C", "time": "10:00", "price": None},
    ])
    assert out["priced_choices"] == 3
    assert out["cheapest"]["price"] == 46.0 and out["cheapest"]["discount_pct"] == 50
    assert out["most_flexible"]["option"] == "B" and out["most_flexible"]["price"] == 60.0
    assert activity_glance([{"option": "X", "price": None}])["cheapest"] is None


def test_cars_glance_cheapest_automatic_and_zero_excess():
    cars = [{"car": "Panda", "transmission": "Manual", "price": 54.81, "cdw_excess": 1000},
            {"car": "T-Cross", "transmission": "Automatic", "price": 73.79, "price_before_discount": 91.83, "cdw_excess": 0},
            {"car": "Yaris", "transmission": "Automatic", "price": 80.0, "cdw_excess": 500}]
    out = cars_glance(cars)
    assert out["cheapest"]["car"] == "Panda"
    assert out["cheapest_automatic"]["car"] == "T-Cross" and out["cheapest_automatic"]["discount_pct"] == 20
    assert out["cheapest_zero_excess"]["car"] == "T-Cross"
    assert cars_glance([])["cheapest"] is None


def test_flights_glance_cheapest_and_cheapest_nonstop():
    options = [{"total_price": 224.68, "legs": [{"flights": ["S4 131", "SP 403"], "departs": "2026-12-10 08:15", "stops": 1, "fare": "SPL"}]},
               {"total_price": 147.36, "legs": [{"flights": ["S4 121"], "departs": "2026-12-10 06:00", "stops": 0, "fare": "SPL"}]},
               {"total_price": 120.0, "legs": [{"flights": ["S4 9"], "departs": "2026-12-10 05:00", "stops": 1, "fare": "SPL"}]}]
    out = flights_glance(options)
    assert out["cheapest"]["total_price"] == 120.0 and out["cheapest_nonstop"]["flights"] == ["S4 121"]
    assert flights_glance([])["cheapest"] is None
