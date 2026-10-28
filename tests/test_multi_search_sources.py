"""A source read several times for different searches (two Bensaude hotels, the two legs of a transfer): 28 Oct 2026 answers showed '18 of 9 read', '29 of 24 read', one link for two hotels and
the two legs as one table (the same car at the same price on the way back collapsed into one row)."""

import json

from myt_mcp.compose import NotChecked, Offer, SourceRead, compose, unify_groups
from myt_mcp.sites import convert_all


def _transfers(when, frm, to, rows):
    return json.dumps({"ok": True, "form": {"from": frm, "to": to, "when": when, "passengers": "2 adults"}, "page_ticked": [], "rows_read": len(rows), "sort_tab": "Comfortable", "price_order": "ascending", "rows": rows})


def _car(cls, price):
    return {"vehicle": f"{cls} car", "vehicle_class": cls, "passengers": "3", "bags": "3", "waiting": "60 min", "meeting": "Meeting with a plate", "flight_tracking": True,
            "cancellation": "Free cancellation 24h before the trip", "price": price, "currency": "EUR", "child_seat": None}


def test_the_two_legs_of_a_transfer_stay_two_tables_and_every_row_of_both_is_counted_with_both_links():
    rows = [_car("Comfort", 16), _car("Business", 22), _car("Minivan", 21)]            # the same cars at the same prices on both legs
    out = {"pickup": "Humberto Delgado Airport (LIS)", "dropoff": "Pousada de Lisboa", "day": "2027-01-12", "time": "17:45", "adults": 2, "children": 0}
    back = {"pickup": "Pousada de Lisboa", "dropoff": "Humberto Delgado Airport (LIS)", "day": "2027-01-19", "time": "15:45", "adults": 2, "children": 0}
    items = [{"site": "ratehawk_transfers", "result": _transfers("12 Jan, Tue, 17:45", "Humberto Delgado Airport (LIS)", "Pousada de Lisboa, Praça do Comércio", rows), "url": "https://rh.test/out", "wishes": {"expect": out}},
             {"site": "ratehawk_transfers", "result": _transfers("19 Jan, Tue, 15:45", "Pousada de Lisboa, Praça do Comércio", "Humberto Delgado Airport (LIS)", rows), "url": "https://rh.test/back", "wishes": {"expect": back}}]
    offers, sources, problems, _, _ = convert_all(items, None)
    assert not problems, problems
    assert len(offers) == 6 and len({o.group for o in offers}) == 2 and sorted(g[-11:] for g in {o.group for o in offers}) == ["12 Jan 2027", "19 Jan 2027"]
    assert (sources[0].read, sources[0].of) == (6, 6)
    assert "https://rh.test/out" in sources[0].link and "https://rh.test/back" in sources[0].link and "12 Jan 2027" in sources[0].link


def _bensaude(hotel, hotel_id):
    return json.dumps({"ok": True, "hotel": hotel, "hotel_id": hotel_id, "check_in": "12/01/2027", "check_out": "19/01/2027", "adults": 2, "agent_login": None,
                       "rows": [{"room": f"{hotel[:4]} room {i}", "room_desc": "Double", "plan": "FLEX", "description": "Breakfast included", "special": False, "price": 400.0 + i * 30, "cancel": "", "tax": "", "pay": "credit card", "nightly": ""} for i in range(3)]})


def test_two_bensaude_hotels_are_two_searches_with_their_own_totals_and_links():
    items = [{"site": "bensaude_hotels", "result": _bensaude("Hotel Açores Lisboa", 30), "url": "https://b.test/30",
              "wishes": {"expect": {"hotel_id": 30, "hotel_name": "Hotel Açores Lisboa", "check_in": "12/01/2027", "check_out": "19/01/2027", "adults": 2}}},
             {"site": "bensaude_hotels", "result": _bensaude("NEAT Hotel Avenida", 31), "url": "https://b.test/31",
              "wishes": {"expect": {"hotel_id": 31, "hotel_name": "NEAT Hotel Avenida", "check_in": "12/01/2027", "check_out": "19/01/2027", "adults": 2}}}]
    offers, sources, problems, _, _ = convert_all(items, None)
    assert not [p for p in problems if "searched" in p], problems
    assert len(offers) == 6 and (sources[0].read, sources[0].of) == (6, 6)
    assert "Hotel Açores Lisboa: https://b.test/30" in sources[0].link and "NEAT Hotel Avenida: https://b.test/31" in sources[0].link


def test_a_refused_reason_shows_what_the_assistant_wrote():
    """28 Oct 2026: El Al and iWay were refused three times and the message never said which words were refused."""
    offer = Offer(group="g", source="X", name="a", price_total=10.0, currency="EUR", price_basis="p", quotable=True, fits=True, details={})
    out = compose("flights", ["Direct (operator)"], [SourceRead(name="X", read=1, of=1, link="https://x.test/l")], [NotChecked(name="iWay", reason="the page stayed blank in my tab")], [offer], {}, None, True, "")
    assert not out["ok"] and any("iWay: the reason 'the page stayed blank in my tab' is not one of the allowed ones" in p for p in out["problems"])


def _o(source, group):
    return Offer(group=group, source=source, name="x", price_total=1.0, currency="EUR", price_basis="p")


def test_one_transfer_leg_named_two_ways_is_one_group_by_its_date_but_never_when_a_source_has_two_legs_that_day():
    rows = [_o("Kiwitaxi", "LIS -> Praça do Comércio 12 Jan 2027"), _o("RateHawk Transfers", "Humberto Delgado Airport (LIS) to Pousada de Lisboa, 12 Jan 2027"),
            _o("Kiwitaxi", "Praça do Comércio -> LIS 19 Jan 2027"), _o("RateHawk Transfers", "Pousada de Lisboa to Humberto Delgado Airport (LIS), 19 Jan 2027")]
    unify_groups(rows, by_date=True)
    assert len({o.group for o in rows}) == 2 and rows[0].group == rows[1].group and rows[2].group == rows[3].group
    same_day = [_o("Kiwitaxi", "LIS -> Hotel 12 Jan 2027"), _o("Kiwitaxi", "Hotel -> LIS 12 Jan 2027"), _o("RateHawk Transfers", "Humberto Delgado Airport to Pousada de Lisboa, 12 Jan 2027")]
    unify_groups(same_day, by_date=True)
    assert len({o.group for o in same_day}) == 3                                       # Kiwitaxi has two legs that day: the direction matters, so the names stay as they are
    same_words = [_o("Kiwitaxi", "LIS -> Hotel 12 Jan 2027"), _o("RateHawk Transfers", "LIS to Hotel, 12 Jan 2027")]
    unify_groups(same_words)
    assert same_words[0].group == same_words[1].group                                  # the same words written two ways were already one group
    flights = [_o("Skyscanner", "Tel Aviv to Lisbon, 12 Jan 2027"), _o("TAP", "TLV -> LIS 12 Jan 2027")]
    unify_groups(flights)
    assert flights[0].group != flights[1].group                                        # without by_date (every kind but transfers) the date alone never joins groups
