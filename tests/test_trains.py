

def test_station_matches_abbreviated_names_but_not_other_stations():
    from myt_mcp.tools.trains import station_matches

    assert station_matches("Firenze Santa Maria Novella", "Firenze S. M. Novella")
    assert station_matches("Florence Santa Maria Novella", "Firenze S. M. Novella")
    assert not station_matches("Firenze Marte", "Firenze S. M. Novella")
    assert not station_matches("Firenze Santa Maria Novella", "Firenze Campo Di Marte")
    assert not station_matches("romma", "Bromma")


def test_highlights_pick_cheapest_and_fastest_of_the_trains_shown():
    from myt_mcp.trenitalia.parse import minutes, highlights

    def row(dep, dur, price, bookable=True):
        return {"departure": dep, "arrival": "x", "trains": [dep], "changes": 0, "duration": dur, "cheapest_price": price,
                "bookable": bookable}

    rows = [row("09:10", "1h 36min", 100.0), row("10:15", "3h 37min", 77.4), row("10:30", "1h 41min", 120.0),
            row("11:00", "1h 30min", 55.0, bookable=False)]
    out = highlights(rows)
    assert out["cheapest_of_shown"]["price"] == 77.4 and out["fastest_of_shown"]["departure"] == "09:10"   # not-bookable 11:00 ignored
    assert out["trains_shown"] == 4 and "later trains were not read" in out["note"]
    assert minutes("1h 36min") == 96 and minutes("45min") == 45 and minutes("2h") == 120 and minutes(None) is None
    assert "cheapest_of_shown" not in highlights([row("09:00", "1h", 0.0)])
