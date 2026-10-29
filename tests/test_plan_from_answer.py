"""A row of a composed answer the operator chose becomes a supplier-reservation line (29 Oct 2026): found again by what the answer shows, priced from the server's own row, supplier from the directory."""

import pytest
from mcp import Client

from myt_mcp.composed import OFFERS
from myt_mcp.compose import Offer
from myt_mcp.myt.plan_from_answer import find_offer, lines_from_choices
from tests.test_reservations import FakeMYT, _v3, create_server_for


def _offer(source, name, price, group, supplier=None, quotable=True, fits=True, basis="per vehicle, one way", unconfirmed=None, currency="EUR"):
    return Offer(group=group, source=source, name=name, price_total=price, currency=currency, price_basis=basis, quotable=quotable, fits=fits, supplier=supplier, unconfirmed=unconfirmed or [], details={})


LEG1, LEG2 = "Lisbon Airport (LIS) to Praça do Comércio, 12 Jan 2027", "Praça do Comércio to Lisbon Airport (LIS), 19 Jan 2027"
OFFERS_IN = [
    _offer("RateHawk Transfers", "Comfort: VW Passat, Hyundai Sonata", 16.0, LEG1, supplier="RateHawk Transfers"),
    _offer("RateHawk Transfers", "Comfort: VW Passat, Hyundai Sonata", 16.0, LEG2, supplier="RateHawk Transfers"),
    _offer("Kiwitaxi", "Comfort (Sedan comfort for 4 passengers)", 40.0, LEG1),
    _offer("iWay (the agency account, list price)", "Standard: Toyota Corolla", 25.45, LEG1, quotable=False),
    _offer("RateHawk Transfers", "Micro: Opel Corsa", 14.0, LEG1, supplier="RateHawk Transfers", fits=False),
]


def test_a_chosen_row_becomes_a_line_with_the_servers_own_price_supplier_and_day():
    out = lines_from_choices("transfers", [{"source": "RateHawk Transfers", "name": "Comfort: VW Passat", "price": 16.0, "group": "12 Jan 2027"}], OFFERS_IN)
    assert out["problems"] == [] and len(out["lines"]) == 1
    line = out["lines"][0]
    assert (line["supplier_id"], line["category"], line["start_date"], line["price"], line["quantity"], line["nights"], line["currency"]) == (85936, "Transport", "2027-01-12", 16.0, 1.0, 1, "EUR")
    assert "RateHawk Transfers" in line["comments"] and line["supplier"].endswith("RateHawk")
    both = lines_from_choices("transfers", [{"source": "RateHawk Transfers", "name": "Comfort: VW Passat", "price": 16.0}], OFFERS_IN)
    assert both["lines"] == [] and "2 rows" in both["problems"][0] and "group" in both["problems"][0]          # the same row on both legs: say which leg


def test_a_row_that_cannot_be_reserved_is_refused_with_the_reason_never_guessed():
    run = lambda **c: lines_from_choices("transfers", [{"source": "x", "name": "x", **c}], OFFERS_IN)["problems"]
    assert "not a supplier in the MYT directory" in run(source="Kiwitaxi", name="Comfort", price=40.0)[0]
    assert "comparison row" in run(source="iWay", name="Standard", price=25.45)[0]
    assert "does not meet every wish" in run(source="RateHawk Transfers", name="Micro", price=14.0)[0]
    typed = run(source="RateHawk Transfers", name="Comfort: VW Passat", price=15.0, group="12 Jan")                 # a price the answer does not show
    assert "no row of 'RateHawk Transfers' named like" in typed[0] and "close: Comfort: VW Passat, Hyundai Sonata 16.00" in typed[0]
    assert "no composed transfers answer" in lines_from_choices("transfers", [{"source": "a", "name": "b"}], [])["problems"][0]
    twice = lines_from_choices("transfers", [{"source": "RateHawk Transfers", "name": "Comfort", "price": 16.0, "group": "12 Jan"}] * 2, OFFERS_IN)
    assert len(twice["lines"]) == 1 and "chosen twice" in twice["problems"][0]


def test_a_hotel_needs_its_day_its_nights_a_lodging_supplier_and_is_priced_per_night():
    hotel = _offer("RateHawk", "Flores Guest House", 537.0, "Hotels", supplier=None, basis="whole stay: 7 nights for 2 guests")
    arbitrip = _offer("Arbitrip", "Quinta Colina By Shiadu", 476.0, "Hotels", basis="whole stay, tax included", quotable=True)
    run = lambda **c: lines_from_choices("hotels", [c], [hotel, arbitrip])
    assert "dmc supplier" in run(source="RateHawk", name="Flores", price=537.0)["problems"][0] or "give `start_date`" in run(source="RateHawk", name="Flores", price=537.0)["problems"][0]
    refused = run(source="RateHawk", name="Flores", price=537.0, start_date="2027-01-12", nights=7)
    assert "dmc supplier" in refused["problems"][0] and "lodging supplier" in refused["problems"][0]           # RateHawk is a DMC: a hotel needs a lodging supplier
    ok = run(source="RateHawk", name="Flores", price=537.0, start_date="2027-01-12", nights=7, supplier="Arbitrip")
    assert ok["problems"] == [] and ok["lines"][0]["supplier_id"] == 102638 and ok["lines"][0]["category"] == "Lodging" and ok["lines"][0]["price"] == 76.71 and ok["lines"][0]["nights"] == 7
    assert "nights" in run(source="Arbitrip", name="Quinta", price=476.0, start_date="2027-01-12")["problems"][0]
    assert "start_date" in run(source="Arbitrip", name="Quinta", price=476.0, nights=7)["problems"][0]


def test_a_car_takes_its_days_from_the_basis_and_a_row_not_confirmed_for_a_wish_is_a_warning():
    car = _offer("Ofran", "Nissan Qashqai", 165.72, "Cars", basis="whole rental, 4 days, total of the page", supplier="Ofran", fits=None, unconfirmed=["large bags"])
    out = lines_from_choices("cars", [{"source": "Ofran", "name": "Qashqai", "price": 165.72, "start_date": "2027-01-13"}], [car])
    assert out["problems"] == [] and out["lines"][0]["supplier_id"] == 83265 and out["lines"][0]["nights"] == 4 and out["lines"][0]["price"] == 41.43
    assert any("not confirmed for: large bags" in w for w in out["warnings"])


def test_a_flight_row_goes_under_its_airline_and_the_row_finder_ignores_case_and_punctuation():
    tap = _offer("TAP Air Portugal", "TP8920 13:40-17:50 operated by El Al Israel Airlines Ltd. (direct, 6h 10) fare PLUSINT", 648.70, "TLV to LIS, 12 Jan 2027", supplier="TAP Air Portugal", basis="whole group (2 seated travellers)")
    out = lines_from_choices("flights", [{"source": "tap air portugal", "name": "tp8920 13:40 plusint", "price": 648.7}], [tap])
    assert out["problems"] == [] and out["lines"][0]["supplier_id"] == 98430 and out["lines"][0]["start_date"] == "2027-01-12" and out["lines"][0]["price"] == 648.7
    assert find_offer([tap], {"source": "TAP", "name": "PLUSINT"})[0] is tap


@pytest.mark.anyio
async def test_compose_answer_keeps_its_rows_and_plan_from_answer_shows_the_plan_and_sends_nothing():
    OFFERS.clear()
    myt = FakeMYT(_v3([], {}, []))
    async with Client(await create_server_for(myt)) as c:
        row = {"group": "Cars", "source": "Ofran", "name": "Nissan Qashqai", "price_total": 165.72, "currency": "EUR", "price_basis": "whole rental, 4 days, total of the page", "quotable": True,
               "fits": True, "flexible": True, "supplier": "Ofran",
               "details": {"company": "Ofran", "gearbox": "Automatic", "seats_bags": "5", "excess": "x", "fuel": "x", "mileage": "x", "deposit": "x", "cancellation": "free"}}
        composed = (await c.call_tool("compose_answer", {"kind": "cars", "pickup_time": "10:00", "filters_used": ["Automatic (operator)"], "offers": [row],
                                                         "sources_read": [{"name": "Ofran", "read": 1, "of": 1, "link": "https://x.test/c"}], "not_checked": []})).structured_content
        assert composed["ok"], composed.get("problems")
        assert [o.name for o in OFFERS.recent("cars")] == ["Nissan Qashqai"]
        plan = (await c.call_tool("plan_from_answer", {"trip_id": 1001, "kind": "cars", "choices": [{"source": "Ofran", "name": "Nissan Qashqai", "price": 165.72, "start_date": "2027-03-13"}]})).structured_content
        none = (await c.call_tool("plan_from_answer", {"trip_id": 1001, "kind": "cars", "choices": [{"source": "Ofran", "name": "Nissan Qashqai", "price": 99.0}]})).structured_content
    assert plan["sent"] is False and myt.create_calls == [] and plan["problems"] == [] and len(plan["lines"]) == 1 and plan["plan"]["reservations"] == 1
    assert plan["plan"]["orders"][0]["supplier_id"] == 83265 and plan["plan"]["total_by_currency"] == {"EUR": 165.72} and "plan_supplier_reservations" in plan["next"]
    assert plan["lines"][0]["nights"] == 4 and plan["lines"][0]["price"] == 41.43
    assert none["lines"] == [] and "no row of 'Ofran'" in none["problems"][0] and "plan" not in none and myt.create_calls == []
    OFFERS.clear()


def test_the_offer_store_replaces_a_row_it_already_holds_and_keeps_kinds_apart():
    OFFERS.clear()
    one = _offer("S", "a", 10.0, "g")
    OFFERS.remember("cars", [one])
    OFFERS.remember("cars", [_offer("S", "a", 10.0, "g"), _offer("S", "b", 12.0, "g")])
    OFFERS.remember("hotels", [_offer("S", "h", 99.0, "g")])
    assert sorted(o.name for o in OFFERS.recent("cars")) == ["a", "b"] and [o.name for o in OFFERS.recent("hotels")] == ["h"] and OFFERS.recent("flights") == []
    OFFERS.clear()
