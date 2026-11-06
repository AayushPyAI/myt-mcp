"""Booking.com attractions, ONE activity (booking_attraction): the address, the converter on what Booking.com's own availability service gave (read live 5 Nov 2026: GetAvailability on the Lisbon Oceanarium,
2 adults + 1 child on 18 Dec: the page's Total 77.50 = 2 x 29.90 + 17.70) and the tool."""

import json
from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.sites import convert_all, modules
from myt_mcp.sites.booking_attraction import booking_attraction_recipe, convert

SLUG = "pr4z1zrjq9hl-skip-the-queue-tickets-into-the-lisbon-oceanarium"
URL = f"https://www.booking.com/attractions/pt/{SLUG}.html"
DAY = date(2026, 12, 18)
RECIPE = booking_attraction_recipe(URL + "?x=1", DAY, 2, [8], "Oceanarium")
EXPECT = RECIPE["expect"]


def slot(time="10:00", total=77.5, bookable=True, units=100, why=None):
    return {"time": time, "total": total, "state": "available" if bookable else "sold_out", "units": units, "until": f"2026-12-18T{time}:00Z", "bookable": bookable, "why": why or []}


def row(ticket="Ticket", total=77.5, slots=None, free=False, label="Non-refundable", until=None, unfit=None, kinds=None, differs=True, cur="EUR", adult=True, includes="Admission"):
    return {"offer_id": "OFqQ7wUOEP0K", "ticket": ticket, "availability_type": "date_time", "cur": cur, "kinds": kinds if kinds is not None else [
        {"type": "adult", "label": "Adult", "count": 2, "price": 29.9, "public_price": 29.9, "constraint": "(age 13-64)", "discounted": False},
        {"type": "children", "label": "Child", "count": 1, "price": 17.7, "public_price": 17.7, "constraint": "(age 3-12)", "discounted": False}], "unfit": unfit or [],
            "total": total, "totals_differ": differs, "slots": slots if slots is not None else [slot("10:00", 77.5), slot("10:30", 77.5), slot("11:00", 80.0)], "adult_required": adult,
            "cancel": {"free": free, "refundable_now": free, "label": None if free else label, "until": until, "period": "P1D" if free else None, "percentage": 100 if free else None}, "includes": includes, "not_included": None}


def answer(rows=None, **over):
    base = {"ok": True, "path": f"/attractions/pt/{SLUG}.en-gb.html", "slug": SLUG, "country": "pt", "activity": "Tickets into The Lisbon Oceanarium", "product_id": "PR4z1zRjQ9hl", "operated_by": "Musement", "day": "2026-12-18",
            "travellers": {"adults": 2, "ages": [8]}, "currency": "EUR", "slots_total": 18, "includes": "Admission", "not_included": None, "additional": "Please bring your ticket on your phone.", "meeting": "Esplanada Dom Carlos I s/nº, Lisbon",
            "unavailable": None, "rows": rows if rows is not None else [row()]}
    base.update(over)
    return json.dumps(base)


def test_the_address_asks_the_date_and_euro_and_the_request_holds_the_group():
    assert RECIPE["url"] == URL + "?date=2026-12-18&selected_currency=EUR"
    assert EXPECT["slug"] == SLUG and EXPECT["day"] == "2026-12-18" and EXPECT["adults"] == 2 and EXPECT["ages"] == [8] and EXPECT["total"] == 3 and EXPECT["group"] == "Oceanarium, 18 Dec 2026" and EXPECT["country"] == "pt"
    assert '"ages": [8]' in RECIPE["script"] and f'"slug": "{SLUG}"' in RECIPE["script"] and "__REQUEST__" not in RECIPE["script"] and "window.__mytParts" in RECIPE["script"]


@pytest.mark.parametrize("args", [("https://www.booking.com/hotel/pt/x.html", 2, []), (URL, 0, [8]), (URL, 16, []), (URL, 2, [100]), (URL, 0, []), (URL, 0, [8])])
def test_a_bad_link_or_group_is_refused(args):
    with pytest.raises(ValueError):
        booking_attraction_recipe(args[0], DAY, args[1], args[2])


def test_the_price_for_the_group_is_the_sum_of_the_tickets_with_the_breakdown_the_times_and_the_terms():
    rows = convert(answer(), {"expect": EXPECT}, "Activities")
    assert rows.problems == [] and rows.read == 1 and rows.total == 1
    o = rows.offers[0]
    assert o.price_total == 77.5 and o.currency == "EUR" and o.quotable is False and o.name == "Tickets into The Lisbon Oceanarium (Ticket)" and o.supplier == "Musement" and o.group == "Oceanarium, 18 Dec 2026"
    assert "whole group (3 travellers; 2 x Adult (age 13-64) at 29.90 EUR; 1 x Child (age 3-12) at 17.70 EUR), taxes and charges included (Booking.com's total), for 2026-12-18, the first time 10:00" in o.price_basis
    d = o.details
    assert d["start_times"] == "3 start time(s): 10:00, 10:30, 11:00; the price differs by time: 10:00 77.5, 10:30 77.5, 11:00 80 EUR" and d["cancellation"] == "Non-refundable" and o.flexible is False and d["seats_left"] == "100"
    assert d["meeting_point"] == "Esplanada Dom Carlos I s/nº, Lisbon" and d["includes"] == "Admission" and d["know_before"] == "Please bring your ticket on your phone." and d["booking_rule"] == "an adult must be in the booking"
    assert o.link == URL + "?date=2026-12-18&selected_currency=EUR" and any("sum of its own ticket prices" in n for n in rows.extra_notes)


def test_the_duration_comes_from_the_products_own_data_when_the_activity_has_one():
    """Read live 5 Nov 2026: the Fatima tour has 'Duration: 9 hours' (PT9H) in its product data, the Oceanarium entrance ticket has none."""
    assert convert(answer(duration="9 hours", duration_iso="PT9H"), {"expect": EXPECT}, "Activities").offers[0].details["duration"] == "9 hours"
    assert convert(answer(), {"expect": EXPECT}, "Activities").offers[0].details["duration"] == "none given by Booking.com (an entrance ticket has none)"


def test_free_cancellation_comes_with_its_exact_cutoff_and_judges_the_wish():
    free = row(free=True, until="2026-12-17T10:00:00", label=None)
    off = convert(answer([free]), {"expect": EXPECT, "free_cancellation": True}, "Activities").offers[0]
    assert off.flexible is True and off.fits is True and off.details["cancellation"] == "Free cancellation until 2026-12-17 10:00 (Booking.com's own data)"
    nonref = convert(answer([row()]), {"expect": EXPECT, "free_cancellation": True}, "Activities").offers[0]
    assert nonref.fits is False and nonref.flexible is False
    unasked = convert(answer([row()]), {"expect": EXPECT}, "Activities").offers[0]
    assert unasked.fits is None


def test_several_ticket_offers_are_several_rows_and_a_group_a_ticket_cannot_take_is_said():
    skip = row("Skip-the-line ticket", 90.0, slots=[slot("10:00", 90.0)], differs=False)
    full = row("Entrance ticket", 70.0, slots=[slot("10:00", 70.0, bookable=False, why=["only 1 Adult left"])])
    res = convert(answer([row(), skip, full]), {"expect": EXPECT}, "Activities")
    assert [o.name for o in res.offers] == ["Tickets into The Lisbon Oceanarium (Ticket)", "Tickets into The Lisbon Oceanarium (Skip-the-line ticket)"] and res.read == 2
    assert any("several ticket offers" in n for n in res.extra_notes) and any("'Entrance ticket' cannot take this group on 2026-12-18: only 1 Adult left" in n for n in res.extra_notes)


def test_a_date_with_no_time_slot_is_said_and_never_called_sold_out():
    res = convert(answer([], unavailable="Booking.com lists no time slot on 2026-12-18", slots_total=0), {"expect": EXPECT}, "Activities")
    assert res.offers == [] and res.problems == [] and any("lists no time slot on 2026-12-18" in n and "never 'sold out'" in n for n in res.extra_notes)


def test_a_time_slot_with_no_price_is_a_reading_fault_never_a_free_ticket():
    """5 Nov 2026, first server-side read: the later time slots showed a price of 0 because the tickets were matched by ids that differ per slot."""
    res = convert(answer([row(slots=[slot("10:00", 77.5), slot("10:30", 0.0), slot("11:00", 0.0)], differs=True)]), {"expect": EXPECT}, "Activities")
    assert any("gave no price for 2 of its time slot(s) (10:30, 11:00)" in p for p in res.problems)
    assert res.offers[0].details["start_times"] == "1 start time(s): 10:00"


def test_a_ticket_with_no_kind_for_a_traveller_or_another_currency_or_a_wrong_group_is_refused_never_guessed():
    assert any("has no kind for: 8" in p for p in convert(answer([row(unfit=["8"])]), {"expect": EXPECT}, "Activities").problems)
    assert any("not euro" in p for p in convert(answer([row(cur="USD")]), {"expect": EXPECT}, "Activities").problems)
    few = row(kinds=[{"type": "adult", "label": "Adult", "count": 2, "price": 29.9, "constraint": "(age 13-64)"}])
    assert any("priced for 2 traveller(s), not 3" in p for p in convert(answer([few]), {"expect": EXPECT}, "Activities").problems)
    assert any("gave no price for 1 of its time slot(s) (10:00)" in p for p in convert(answer([row(total=0.0, slots=[slot("10:00", 0.0)])]), {"expect": EXPECT}, "Activities").problems)


@pytest.mark.parametrize("change,fragment", [
    ({"slug": "other-activity"}, "the page is the activity 'other-activity'"),
    ({"day": "2026-12-19"}, "the answer is for 2026-12-19, not 2026-12-18"),
    ({"travellers": {"adults": 3, "ages": [8]}}, "the travellers sent were 3 adults and ages [8], not 2 adults and ages [8]"),
    ({"rows": []}, "no ticket price could be read"),
])
def test_an_answer_for_something_else_is_refused_with_the_fix(change, fragment):
    problems = convert(answer(**change), {"expect": EXPECT}, "Activities").problems
    assert any(fragment in p for p in problems), problems


def test_a_script_error_and_a_text_that_is_not_json_come_back_as_a_readable_problem():
    assert "reported: Booking.com shows a human check" in convert(json.dumps({"ok": False, "error": "Booking.com shows a human check (captcha)."}), {"expect": EXPECT}, "Activities").problems[0]
    assert "not the script's JSON text" in convert("Total EUR 77.50", {"expect": EXPECT}, "Activities").problems[0]


def test_the_converter_is_found_by_the_server_and_works_through_convert_all():
    assert "booking_attraction" in modules()
    offers, sources, problems, by_price, notes = convert_all([{"site": "booking_attraction", "result": answer(), "url": RECIPE["url"], "wishes": {"expect": EXPECT}}], {"expect": EXPECT})
    assert problems == [] and len(offers) == 1 and sources[0].read == 1 and by_price is False


@pytest.mark.anyio
async def test_the_tool_returns_the_address_the_script_and_the_wishes_and_refuses_a_bad_link():
    async with Client(create_server(Settings())) as c:
        got = (await c.call_tool("booking_attraction_recipe", {"url": URL, "day": "2026-12-18", "adults": 2, "children_ages": [8], "free_cancellation": True})).structured_content
        assert got["url"] == URL + "?date=2026-12-18&selected_currency=EUR" and got["wishes"]["expect"]["total"] == 3 and got["wishes"]["free_cancellation"] is True and "script" in got
        assert any("Free cancellation only" in f for f in got["filters_used"])
        bad = await c.call_tool("booking_attraction_recipe", {"url": "https://www.booking.com/hotel/pt/x.html", "day": "2026-12-18", "adults": 2, "children_ages": []})
        assert bad.is_error and "Booking.com activity link" in bad.content[0].text


def test_a_senior_is_priced_in_the_senior_kind_and_a_group_of_seniors_needs_no_other_adult():
    r = booking_attraction_recipe(URL, DAY, 0, [70, 72])
    assert r["expect"]["adults"] == 0 and r["expect"]["ages"] == [70, 72] and r["expect"]["total"] == 2 and '"ages": [70, 72]' in r["script"]
    with pytest.raises(ValueError, match="at least one adult"):
        booking_attraction_recipe(URL, DAY, 0, [8, 12])
