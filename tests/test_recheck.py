"""Re-checking an existing quotation: the plan lists lines and tools, the report accepts only prices that are in a compose_answer text (synthetic payload, no client data)."""

from datetime import date

import pytest

from myt_mcp.composed import ComposedStore
from myt_mcp.quote.recheck import classify, plan, report
from tests.test_reservations import _line, _res, _v3

TODAY = date(2026, 10, 26)


def _kind(line, category, transport=None, line_type=None):
    line["type"] = {"name": category}
    if transport:
        line["second_category"] = {"name": transport}
    if line_type:
        line["first_category"] = {"name": line_type}
    return line


def v3():
    lines = [_kind(_line(98430, "TAP AIR PORTUGAL", "FLR to LIS TP875 CLANEW", 598.0, 1, 1, "2027-03-06"), "Transportation", "Plane", "Ride"),
             _kind(_line(40, "Trenitalia", "Frecciarossa 9520", 125.0, 1, 1, "2027-03-04"), "Transportation", "Train", "Ride"),
             _kind(_line(10, "RateHawk", "Transfer FCO - Hotel Mia", 91.53, 1, 1, "2027-03-01"), "Transportation", "Car", "Ride"),
             _kind(_line(20, "Get your guide", "Vatican tour", 256.51, 1, 1, "2027-03-03"), "Attraction", None, "Entrance"),
             _kind(_line(30, "Pure Azores", "Sete Cidades tour", 255.0, 1, 1, "2027-03-10"), "Attraction", None, "Entrance"),
             _kind(_line(50, "Hadas", "Guide day", 300.0, 1, 1, "2027-03-02"), "Staff", None, "Day")]
    res = [_res(1, 98430, "TAP AIR PORTUGAL", "FLR to LIS TP875 CLANEW", 530.38, 1, 1, "2027-03-06"), _res(2, 40, "Trenitalia", "Frecciarossa 9520", 125.0, 1, 1, "2027-03-04"),
           _res(3, 10, "RateHawk", "Transfer FCO - Hotel Mia", 81.0, 1, 1, "2027-03-01"), _res(4, 20, "Get your guide", "Vatican tour", 227.0, 1, 1, "2027-03-03")]
    return _v3(res, {1: "NotSent", 2: "NotSent", 3: "NotSent", 4: "NotSent"}, lines)


def test_every_line_is_classified_and_the_ones_without_a_tool_say_so():
    got = {x["product"]: x for x in plan(v3(), TODAY)["lines"]}
    assert got["FLR to LIS TP875 CLANEW"]["kind"] == "flights" and got["FLR to LIS TP875 CLANEW"]["tools"][0] == "tap_recipe" and got["FLR to LIS TP875 CLANEW"]["net"] == 530.38
    assert got["Frecciarossa 9520"]["tools"] == ["train_prices (Trenitalia)"]
    assert got["Transfer FCO - Hotel Mia"]["kind"] == "transfers" and "ratehawk_transfers_recipe" in got["Transfer FCO - Hotel Mia"]["tools"]
    assert got["Vatican tour"]["tools"] == ["getyourguide_activity_recipe"] and "link" in got["Vatican tour"]["needs"]
    assert got["Sete Cidades tour"]["tools"] == [] and "no price tool" in got["Sete Cidades tour"]["no_tool"] and got["Sete Cidades tour"]["net"] is None
    assert got["Guide day"]["kind"] == "other"
    counts = plan(v3(), TODAY)["counts"]
    assert counts == {"lines": 6, "can_be_priced_again": 4, "no_tool": 2, "without_reservation_net": 2}
    assert classify({"product": "VW T-Cross", "supplier": "Ofran", "transport": "Car", "category": "Transportation"})["tools"] == ["ratehawk_cars_recipe", "ofran_recipe"]


COMPOSED_TEXT = ("| Source | Option | Price |\n| TAP Air Portugal | TP1863 17:00-18:35 fare CLANEW | 530.38 EUR |\n| Trenitalia | Frecciarossa 9520 09:08 Standard BASE | 125.00 EUR |\n"
                 "| RateHawk Transfers | Economy: Skoda Octavia | 81.00 EUR |\n| GetYourGuide | Vatican tour, English, 10:00 | 212.00 EUR |\n")


def store():
    s = ComposedStore()
    s.remember("flights", COMPOSED_TEXT)
    return s


def check(line, option, price, currency="EUR"):
    return {"line": line, "option": option, "price": price, "currency": currency}


def test_the_report_compares_with_the_reservation_net_and_counts_what_was_not_checked():
    out = report(v3(), [check(1, "TP1863 17:00-18:35 fare CLANEW", 530.38), check(2, "Frecciarossa 9520", 125.0), check(3, "Economy: Skoda Octavia", 81.0), check(4, "Vatican tour, English", 212.0)], store(), TODAY)
    assert out["ok"] and out["counts"] == {"lines": 6, "re_checked": 4, "same": 3, "changed": 1, "not_checked": 2}
    assert "4 of 6 lines re-checked: 3 same, 1 changed (together -15.00); 2 not checked." in out["answer"]
    assert "-15.00 (-6.6%)" in out["answer"]
    assert "line 5 Sete Cidades tour: its supplier has no price tool here" in out["answer"] and "line 6 Guide day: no tool here has a price for this line" in out["answer"]


def test_a_price_that_is_in_no_compose_answer_is_refused_whatever_the_assistant_says():
    out = report(v3(), [check(4, "Vatican tour, English", 199.0), check(2, "Frecciarossa 9520", 125.0), check(9, "x", 1.0)], store(), TODAY)
    assert out["ok"] is False
    assert any("line 4" in p and "199.00 EUR is in no compose_answer" in p for p in out["problems"]) and any("line 9" in p and "no such line" in p for p in out["problems"])
    assert report(v3(), [check(4, "Another tour", 212.0)], store(), TODAY)["ok"] is False          # the right price on the wrong row
    assert report(v3(), [check(2, "Frecciarossa 9520", 125.0), check(2, "Frecciarossa 9520", 125.0)], store(), TODAY)["problems"] == ["line 2: given twice"]


def test_thousands_separators_and_a_foreign_currency_are_handled_and_the_report_is_remembered_for_check_answer():
    s = ComposedStore()
    s.remember("flights", "| TAP | TP8920 13:40 | 1,744.00 EUR |\n| RateHawk | LY376 | 808.00 USD |")
    data = v3()
    out = report(data, [check(1, "TP8920 13:40", 1744.0), check(2, "LY376", 808.0, "USD")], s, TODAY)
    assert out["ok"] and out["counts"]["changed"] == 1 and "currency differs (EUR against USD)" in out["answer"]
    assert any("re-checked" in t for t in s.recent("recheck")) and "1744.00 EUR" in out["answer"]
