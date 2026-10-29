"""Fixes after the 29 Oct 2026 real runs: flight tracking only on an airport pick-up, 'Most flexible' never a row with a missing wish and no word, 'N+' when the list was cut, the cars caution for an
off-airport pick-up, plain failure words as a reason, the repaired parts told truthfully, the stars a Bensaude hotel's own page states."""

import json

import pytest

from myt_mcp.compose import NotChecked, Offer, SourceRead, compose, is_airport, tracking_applies, tracking_unconfirmed
from myt_mcp.sites import check_parts, convert_all
from tests.test_compose import _car, _cars, _tr, _train, _trains, _transfers


# ---------- flight tracking belongs to an airport pick-up ----------

def test_a_leg_from_an_airport_is_judged_on_flight_tracking_and_a_leg_from_a_hotel_is_not():
    for group, applies in (("Lisbon Airport (LIS) -> Praça do Comércio, 12 Jan 2027", True), ("Praça do Comércio -> Lisbon Airport (LIS), 19 Jan 2027", False),
                           ("Humberto Delgado Airport (LIS) to Pousada de Lisboa, 12 Jan 2027", True), ("Pousada de Lisboa to Humberto Delgado Airport (LIS), 19 Jan 2027", False),
                           ("Transfers", True), ("LIS to Hotel Avenida", True)):
        assert tracking_applies(group) is applies, group
    assert is_airport("Humberto Delgado Airport (LIS)") and is_airport("LIS") and is_airport("Faro Airport") and not is_airport("Pousada de Lisboa, Praça do Comércio")


def _leg_offer(group, source, tracking):
    return Offer(group=group, source=source, name="Comfort", price_total=16.0, currency="EUR", price_basis="per vehicle", quotable=True, fits=True, details={"flight_tracking": tracking})


def test_compose_marks_flight_tracking_only_on_the_airport_leg_and_says_which_leg_was_not_judged():
    out_leg, back_leg = "Lisbon Airport (LIS) -> Praça do Comércio, 12 Jan 2027", "Praça do Comércio -> Lisbon Airport (LIS), 19 Jan 2027"
    rows = [_leg_offer(out_leg, "Kiwitaxi", "not shown"), _leg_offer(back_leg, "Kiwitaxi", "not shown"), _leg_offer(out_leg, "RateHawk Transfers", "yes"), _leg_offer(back_leg, "RateHawk Transfers", "not applicable")]
    note = tracking_unconfirmed(rows)
    assert rows[0].unconfirmed == ["flight tracking"] and rows[0].fits is None                 # airport pick-up, the row does not say: not confirmed
    assert rows[1].unconfirmed == [] and rows[1].fits is True                                    # from the hotel: not judged
    assert rows[2].fits is True and rows[3].fits is True
    assert "not judged on the leg Praça do Comércio -> Lisbon Airport (LIS), 19 Jan 2027" in note and "Kiwitaxi" in note


def test_ratehawk_transfers_from_a_hotel_keep_their_rows_when_flight_tracking_was_asked():
    """29 Oct 2026: 24 RateHawk rows of the leg from the hotel (no tracking option there) were dropped as 'no tracking' and only Kiwitaxi was left."""
    rows = [_tr("Sedan", 16, "3", "3", False), _tr("Minivan", 21, "4", "4", False)]
    hotel_leg = {"expect": {"pickup": "Pousada de Lisboa", "dropoff": "Humberto Delgado Airport (LIS)", "day": "2027-01-19", "time": "15:45", "adults": 2, "children": 0}, "min_bags": 2, "flight_tracking": True}
    form = {"from": "Pousada de Lisboa, Praça do Comércio - Small Luxury Hotel", "to": "Humberto Delgado Airport (LIS)", "when": "19 Jan, Tue, 15:45", "passengers": "2 adults"}
    offers, _, problems, _, _ = convert_all([{"site": "ratehawk_transfers", "result": _transfers(rows, form=form, sort_tab="Cheapest"), "url": "u", "wishes": hotel_leg}], None)
    assert not [p for p in problems if "searched" in p], problems
    assert [o.fits for o in offers] == [True, True] and all("not applicable" in o.details["flight_tracking"] for o in offers)
    airport_leg = {**hotel_leg, "expect": {**hotel_leg["expect"], "pickup": "Humberto Delgado Airport (LIS)", "dropoff": "Pousada de Lisboa", "day": "2027-01-12", "time": "17:45"}}
    form2 = {"from": "Humberto Delgado Airport (LIS)", "to": "Pousada de Lisboa, Praça do Comércio - Small Luxury Hotel", "when": "12 Jan, Tue, 17:45", "passengers": "2 adults"}
    offers2, _, _, _, _ = convert_all([{"site": "ratehawk_transfers", "result": _transfers(rows, form=form2, sort_tab="Cheapest"), "url": "u", "wishes": airport_leg}], None)
    assert [o.fits for o in offers2] == [False, False]                                          # at an airport a row with no tracking is still a miss


# ---------- Most flexible ----------

def _flex(name, price, fits, flexible=True, unconfirmed=None):
    return Offer(group="g", source="S", name=name, price_total=price, currency="EUR", price_basis="p", quotable=True, fits=fits, flexible=flexible, unconfirmed=unconfirmed or [],
                 details={"capacity": "x", "waiting_time": "x", "cancellation": "x", "provider": "x", "meeting_point": "x"})


def _most_flexible(rows):
    out = compose("transfers", ["Comfortable tab (operator)"], [SourceRead(name="S", read=len(rows), of=len(rows), link="https://x.test/l")], [], rows, {}, "10:00", True, "")
    assert out["ok"], out.get("problems")
    return [line for line in out["answer"].splitlines() if "Most flexible" in line and line.lstrip().startswith("|")][0]


def test_most_flexible_is_a_row_that_meets_every_wish_and_otherwise_says_what_is_wrong_with_it():
    """29 Oct 2026: a Micro car (not comfortable, not in the table) and a ROOM-ONLY rate (no breakfast) were 'Most flexible' with no word."""
    fine = _flex("Comfort", 16, True)
    micro = _flex("Micro", 14, False)
    unsure = _flex("Minivan", 21, None, unconfirmed=["vehicle comfort"])
    assert "Comfort - 16.00" in _most_flexible([fine, micro, unsure]) and "NOT" not in _most_flexible([fine, micro, unsure])
    line = _most_flexible([_flex("Sedan", 30, True, flexible=False), micro, unsure])
    assert "Minivan" in line and "not every wish is confirmed for it (vehicle comfort)" in line
    line = _most_flexible([_flex("Sedan", 30, True, flexible=False), micro])
    assert "Micro" in line and "it does NOT meet every wish of the operator" in line
    assert "not determined" in _most_flexible([_flex("Sedan", 30, True, flexible=False)])


# ---------- N+ when the list was cut ----------

def test_a_source_whose_list_was_cut_shows_n_of_n_plus():
    cars = [_car("Opel Corsa", 40.0, gearbox="Automatic"), _car("Fiat 500", 45.0, gearbox="Automatic")]
    cut = convert_all([{"site": "ratehawk_cars", "result": _cars(cars, reached_cap=True), "url": "u"}], None)[1][0]
    whole = convert_all([{"site": "ratehawk_cars", "result": _cars(cars), "url": "u"}], None)[1][0]
    assert cut.more is True and whole.more is False
    rows = [_train()]
    loading = convert_all([{"site": "ratehawk_trains", "result": _trains(rows, all_loaded=False), "url": "u"}], None)[1][0]
    loaded = convert_all([{"site": "ratehawk_trains", "result": _trains(rows, all_loaded=True), "url": "u"}], None)[1][0]
    assert loading.more is True and loaded.more is False


def test_the_sources_line_writes_the_plus():
    def row(source):
        return Offer(group="g", source=source, name=f"{source} car", price_total=10.0, currency="EUR", price_basis="p", quotable=True, fits=True,
                     details={"capacity": "x", "waiting_time": "x", "cancellation": "x", "provider": "x", "meeting_point": "x"})
    out = compose("transfers", ["x (operator)"], [SourceRead(name="Cut source", read=30, of=30, more=True, link="https://x.test/l"), SourceRead(name="Whole source", read=5, of=5, link="https://x.test/m")],
                  [], [row("Cut source"), row("Whole source")], {}, "10:00", True, "")
    assert out["ok"], out.get("problems")
    assert "Cut source (30 of 30+ read)" in out["answer"] and "Whole source (5 of 5 read)" in out["answer"]


# ---------- cars: an off-airport pick-up ----------

def test_a_cars_pick_that_is_a_shuttle_to_an_office_gets_the_terminal_caution():
    def car(name, price, place):
        return Offer(group="Cars", source="RateHawk Car rental", name=name, price_total=price, currency="EUR", price_basis="whole rental", quotable=True, fits=True, flexible=True,
                     details={"company": "greenmotion", "gearbox": "Automatic", "seats_bags": "5", "excess": "1,800", "fuel": "Full to full", "mileage": "Unlimited", "deposit": "2,100",
                              "cancellation": "Free cancellation", "pickup_place": place})
    out = compose("cars", ["Automatic (operator)"], [SourceRead(name="RateHawk Car rental", read=2, of=2, link="https://x.test/c")], [],
                  [car("Peugeot 208", 31.07, "Transfer to the rental place"), car("Peugeot 208 B", 50.73, "At the airport")], {}, "10:00", True, "")
    assert out["ok"], out.get("problems")
    assert "Caution on the Best fit (RateHawk Car rental: Peugeot 208)" in out["answer"] and "not at the airport terminal (Transfer to the rental place)" in out["answer"]


# ---------- a site's failure in plain words ----------

def test_a_reason_that_says_the_page_went_wrong_is_accepted_and_a_lazy_one_is_not():
    one = Offer(group="g", source="S", name="a", price_total=10.0, currency="EUR", price_basis="p", quotable=True, fits=True, details={"capacity": "x", "waiting_time": "x", "cancellation": "x", "provider": "x", "meeting_point": "x"})
    run = lambda reason: compose("transfers", ["x (operator)"], [SourceRead(name="S", read=1, of=1, link="https://x.test/l")], [NotChecked(name="RateHawk Cars", reason=reason)], [one], {}, "10:00", True, "")
    assert run("the page showed 'Something went wrong :(' when opened")["ok"] and run("the page did not load")["ok"] and run("timed out after 60 s")["ok"]
    bad = run("for time")
    assert not bad["ok"] and any("'for time'" in p for p in bad["problems"])


# ---------- repaired parts are said ----------

def test_a_repaired_part_is_marked_so_the_answer_can_say_so():
    from tests.test_site_scripts import _escaped_part
    part = _escaped_part(["Café € 10", "Hotel Lisboa"])
    typed = part.replace("\\u20ac", "€").replace("\\u00e9", "é")
    fixed, plain = {"site": "ofran", "result": typed}, {"site": "ofran2", "result": _escaped_part(["plain"], "r2")}
    assert check_parts([fixed, plain]) == []
    assert fixed.get("repaired") is True and "repaired" not in plain


# ---------- Bensaude: the stars a hotel's own page states ----------

def test_bensaude_shows_the_stars_its_own_page_states_and_judges_the_wish_on_them():
    from myt_mcp.sites.bensaude_hotels import convert, known_stars
    from tests.test_bensaude import _data
    assert known_stars(30) == 4 and known_stars(9880610) == 4 and known_stars(31) is None and known_stars(29) is None
    expect = {"hotel_id": 30, "check_in": "06/03/2027", "check_out": "08/03/2027", "adults": 2}
    four = convert(_data(hotel="Hotel Açores Lisboa", hotel_id=30), {"expect": expect, "stars_min": 4}, "Hotels")
    assert all(o.details["stars"] == 4 and o.fits is not None for o in four.offers) and not any("no star rating" in n for n in four.extra_notes)
    five = convert(_data(hotel="Hotel Açores Lisboa", hotel_id=30), {"expect": expect, "stars_min": 5}, "Hotels")
    assert all(o.fits is False for o in five.offers)
    unknown = convert(_data(hotel="NEAT Hotel Avenida", hotel_id=31), {"expect": {**expect, "hotel_id": 31}, "stars_min": 4}, "Hotels")
    assert all(o.details["stars"] is None and o.fits is None for o in unknown.offers) and any("no star rating" in n for n in unknown.extra_notes)
