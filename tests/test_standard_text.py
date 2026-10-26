"""The standard Hebrew includes lines: the rules against the lists the operator typed by hand in 8 real quotations (26 Oct 2026; the fixture holds only yes/no facts)."""

import json
from pathlib import Path

import pytest

from myt_mcp.quote.standard_text import CATALOG, _applies, choose, trip_facts

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "standard_text_trips.json").read_text())
LINES = {e["id"]: e for side in ("includes", "not_includes") for e in CATALOG[side]}

# where the operator's own list differs from the rules, with the reason known today
KNOWN_DIFFERENCES = {
    ("269362", "domestic_flights"): "the quotation has 3 domestic flights and no line for them (probably forgotten by hand)",
    ("269362", "one_way_fee"): "a rental car, but no one-way fee line",
    ("260808", "one_way_fee"): "a rental car, but no one-way fee line",
}


def test_every_line_has_hebrew_text_a_known_rule_and_a_status():
    assert len(CATALOG["includes"]) == 7 and len(CATALOG["not_includes"]) == 10
    for entry in LINES.values():
        assert entry["status"] in ("confirmed", "draft", "open") and entry["rule"] in ("always", "never", "hotels", "rental_car", "domestic_flight", "lounge")
        assert any("֐" <= ch <= "׿" for ch in entry["text"])
        assert entry["status"] == "confirmed" or entry["question"]
    assert [e["id"] for e in CATALOG["not_includes"]][-3:] == ["closing_framework", "closing_no_bookings", "closing_passport"]          # the closing notes are always the last three


@pytest.mark.parametrize("trip", sorted(FIXTURE))
def test_the_rules_write_what_the_operator_wrote_except_the_lines_she_has_not_decided(trip):
    facts, manual = FIXTURE[trip]["facts"], FIXTURE[trip]["manual"]
    for line_id, entry in LINES.items():
        if entry["status"] == "open":
            continue          # never written by the rules; she wrote them in some quotations only
        if (trip, line_id) in KNOWN_DIFFERENCES:
            assert manual[line_id] != _applies(entry["rule"], facts)
        else:
            assert manual[line_id] == _applies(entry["rule"], facts), (trip, line_id)


def test_choose_writes_stars_and_lists_what_the_operator_still_has_to_confirm():
    facts = {"hotels": True, "rental_car": True, "domestic_flight": False, "lounge": True}
    out = choose(facts, stars="5")
    assert "בדרגת 5 כוכבים" in out["includes"][0] and len(out["includes"]) == 6 and len(out["not_includes"]) == 7     # no domestic flights, none of the three open lines
    assert not any(c["line"] == "hotels" for c in out["to_confirm"])
    assert {"not_in_itinerary", "extra_meals", "international_flights"} <= {c["line"] for c in out["to_confirm"] if c["status"] == "open" and not c["written"]}
    default = choose(facts)
    assert "בדרגת 4/5 כוכבים" in default["includes"][0] and any(c["line"] == "hotels" and c["status"] == "default" for c in default["to_confirm"])
    nothing = choose({"hotels": True, "rental_car": False, "domestic_flight": False, "lounge": False})
    assert not any("השכרת רכב" in t or "דלק" in t for side in ("includes", "not_includes") for t in nothing[side])             # no car: no car lines
    assert nothing["not_includes"][-1].startswith("אנא ודאו")


def test_trip_facts_read_flights_hotels_and_car_lines_from_a_trip():
    v3 = {"trip": {"number": "1"}, "flights": [{"from_airport": "Ben Gurion Airport", "to_airport": "Lisbon", "number": "A"}, {"from_airport": "Lisbon", "to_airport": "Funchal", "number": "B"}],
          "accomodation": [{"product_name": "Hotel", "dates": {}}], "schedule": [], "quotation": {"products": []}}
    facts = trip_facts(v3)
    assert facts["hotels"] and facts["domestic_flight"] and facts["lounge"] and not facts["rental_car"]
