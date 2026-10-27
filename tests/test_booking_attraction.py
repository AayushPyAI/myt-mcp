"""Booking.com attractions, ONE activity (booking.com/attractions/<cc>/<slug>.html): the address, the converter on what the real page gave (27 Oct 2026) and the tool."""

import json
from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.sites import convert_all, modules
from myt_mcp.sites.booking_attraction import booking_attraction_recipe, convert

URL = "https://www.booking.com/attractions/pt/pr4z1zrjq9hl-skip-the-queue-tickets-into-the-lisbon-oceanarium.en-gb.html?aid=1#x"
SLUG = "pr4z1zrjq9hl-skip-the-queue-tickets-into-the-lisbon-oceanarium"
DAY = date(2027, 3, 7)
RECIPE = booking_attraction_recipe(URL, DAY, 2, [], "Oceanarium")
EXPECT = RECIPE["expect"]
KINDS = [{"label": "Adult (age 13-64)", "price": 29.9, "count": 2, "wanted": 2}, {"label": "Child (age 3-12)", "price": 17.7, "count": 0, "wanted": 0},
         {"label": "Senior (age 65+)", "price": 19.9, "count": 0, "wanted": 0}, {"label": "Infant (age 0-2)", "price": 0.0, "count": 0, "wanted": 0}]


def row(**over):
    """The ticket box as the script reads it; prices and wording are the real Oceanarium page of 27 Oct 2026 (10 Nov 2026, 2 adults: the page's own Total was 59.80)."""
    base = {"ticket": "Non-refundable", "times": ["10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30"], "time_chosen": "10:00", "kinds": KINDS, "symbol": "€", "total": 59.8, "taxes": True, "computed": 59.8, "symbol_kinds": "€"}
    base.update(over)
    return base


def answer(rows=None, **over):
    base = {"ok": True, "form": {"slug": SLUG, "date": "2027-03-07", "currency": "EUR"}, "title": "Tickets into The Lisbon Oceanarium", "chosen_day": "Sun 7 Mar", "operated_by": "Musement",
            "includes": "Admission", "additional": "Please bring your ticket with you to the attraction.", "unavailable": None, "steppers": 4, "rows": rows if rows is not None else [row()]}
    base.update(over)
    return json.dumps(base)


def test_the_address_asks_the_date_and_euro_and_drops_the_lists_own_query():
    assert RECIPE["url"] == f"https://www.booking.com/attractions/pt/{SLUG}.html?date=2027-03-07&selected_currency=EUR"
    assert EXPECT["slug"] == SLUG and EXPECT["day_label"] == "Sun 7 Mar" and EXPECT["total"] == 2 and EXPECT["group"] == "Oceanarium, 07 Mar 2027"
    assert "__EXPECT__" not in RECIPE["script"] and "Next" in RECIPE["script"]


@pytest.mark.parametrize("url", ["", "https://www.getyourguide.com/lisbon/x-t1/", "https://www.booking.com/attractions/searchresults/pt/lisbon.html", "https://www.booking.com/hotel/pt/x.html"])
def test_a_link_that_is_not_an_activity_page_is_refused(url):
    with pytest.raises(ValueError):
        booking_attraction_recipe(url, DAY, 2, [])


def test_bad_groups_are_refused():
    for adults, ages in ((0, [5]), (16, []), (2, [18]), (0, [])):
        with pytest.raises(ValueError):
            booking_attraction_recipe(URL, DAY, adults, ages)


def test_the_ticket_box_becomes_a_comparison_only_row_with_the_pages_own_total_and_its_breakdown():
    rows = convert(answer(), {"expect": EXPECT}, "Activities")
    assert rows.problems == [] and rows.read == 1
    o = rows.offers[0]
    assert o.price_total == 59.8 and o.currency == "EUR" and o.quotable is False and o.flexible is False and o.supplier == "Musement" and o.group == "Oceanarium, 07 Mar 2027"
    assert o.name == "Tickets into The Lisbon Oceanarium (Non-refundable)" and "2 x Adult (age 13-64) at 29.90" in o.price_basis and "taxes and charges included" in o.price_basis and "2027-03-07" in o.price_basis
    assert o.details["start_times"].startswith("10 start time(s): 10:00, 10:30, 11:00, 11:30, 12:00, 12:30, ... last 14:30 (first chosen: 10:00") and o.details["cancellation"] == "Non-refundable"
    assert o.details["includes"] == "Admission" and o.details["operated_by"] == "Musement" and o.details["duration"] == "not shown on the ticket box"
    assert any("page's own Total" in n for n in rows.extra_notes)


def test_a_group_with_a_child_is_counted_in_the_kind_of_the_childs_age_in_the_breakdown():
    kinds = [{**KINDS[0], "count": 2, "wanted": 2}, {**KINDS[1], "count": 1, "wanted": 1}] + KINDS[2:]
    rec = booking_attraction_recipe(URL, DAY, 2, [8])
    o = convert(answer([row(kinds=kinds, total=77.5, computed=77.5)]), {"expect": rec["expect"]}, "Activities").offers[0]
    assert o.price_total == 77.5 and "3 travellers" in o.price_basis and "2 x Adult (age 13-64) at 29.90; 1 x Child (age 3-12) at 17.70" in o.price_basis


def test_a_date_the_site_cannot_book_is_told_as_it_is_and_never_as_sold_out():
    rows = convert(answer([], unavailable="Your selected date is unavailable, please choose another one", chosen_day=None), {"expect": EXPECT}, "Activities")
    assert rows.offers == [] and rows.problems == []
    assert any("unavailable" in n and "never 'sold out'" in n for n in rows.extra_notes)


def test_the_free_cancellation_wish_is_judged_on_the_tickets_own_wording():
    wishes = {"expect": EXPECT, "free_cancellation": True}
    assert convert(answer([row(ticket="Non-refundable")]), wishes, "Activities").offers[0].fits is False
    free = convert(answer([row(ticket="Free cancellation until 8 Mar 2027, 10:00")]), wishes, "Activities").offers[0]
    assert free.fits is True and free.flexible is True
    assert convert(answer([row(ticket="Standard ticket")]), wishes, "Activities").offers[0].fits is None      # a wording that says nothing: unknown, never assumed
    assert convert(answer([row(ticket="Non-refundable")]), {"expect": EXPECT}, "Activities").offers[0].fits is None      # no wish, no judgement


@pytest.mark.parametrize("change,fragment", [
    ({"form": {"slug": "pr999-other", "date": "2027-03-07", "currency": "EUR"}}, "is the activity 'pr999-other', not"),
    ({"form": {"slug": SLUG, "date": "2027-03-07", "currency": "USD"}}, "currency in the address is USD, not EUR"),
    ({"rows": [row(symbol="$")]}, "not euro"),
    ({"rows": [row(total=0)]}, "shows no total for the group"),
    ({"rows": [row(kinds=[{**KINDS[0], "count": 1}] + KINDS[1:])]}, "Adult (age 13-64): 1 instead of 2"),
    ({"rows": []}, "never that the activity is sold out"),
])
def test_a_page_that_is_another_activity_or_priced_or_counted_wrongly_is_refused_with_the_fix(change, fragment):
    problems = convert(answer(**change), {"expect": EXPECT}, "Activities").problems
    assert any(fragment in p for p in problems), problems


def test_a_total_that_is_not_the_tickets_added_up_is_shown_as_the_pages_own_with_a_note():
    rows = convert(answer([row(total=55.0, computed=59.8)]), {"expect": EXPECT}, "Activities")
    assert rows.offers[0].price_total == 55.0 and any("differs from the tickets added up" in n for n in rows.extra_notes)


def test_a_script_error_and_a_text_that_is_not_json_come_back_as_a_readable_problem():
    assert "reported: the ticket box is not on the page" in convert(json.dumps({"ok": False, "error": "the ticket box is not on the page"}), {"expect": EXPECT}, "Activities").problems[0]
    assert "not the script's JSON text" in convert("Total | 59.80", {"expect": EXPECT}, "Activities").problems[0]


def test_the_converter_is_found_by_the_server_and_works_through_convert_all():
    assert "booking_attraction" in modules()
    offers, sources, problems, _, notes = convert_all([{"site": "booking_attraction", "result": answer(), "url": RECIPE["url"], "wishes": {"expect": EXPECT}}], {"expect": EXPECT})
    assert problems == [] and len(offers) == 1 and sources[0].read == 1 and any("activity's page is the quoted source" in n for n in notes)


@pytest.mark.anyio
async def test_the_tool_returns_the_address_and_wishes_and_refuses_a_link_that_is_not_an_activity_page():
    async with Client(create_server(Settings())) as c:
        got = (await c.call_tool("booking_attraction_recipe", {"url": URL, "day": "2027-03-07", "adults": 2, "children_ages": [8], "activity": "Oceanarium", "free_cancellation": True})).structured_content
        assert got["url"].startswith("https://www.booking.com/attractions/pt/pr4z1zrjq9hl") and got["wishes"]["free_cancellation"] is True and got["wishes"]["expect"]["total"] == 3
        assert "Free cancellation only (operator)" in got["filters_used"] and "Prices in EUR (server default)" in got["filters_used"]
        bad = await c.call_tool("booking_attraction_recipe", {"url": "https://www.booking.com/hotel/pt/x.html", "day": "2027-03-07", "adults": 2, "children_ages": []})
        assert bad.is_error and "never guess it" in bad.content[0].text
        nobody = await c.call_tool("booking_attraction_recipe", {"url": URL, "day": "2027-03-07", "adults": 0, "children_ages": [5]})
        assert nobody.is_error and "at least one adult" in nobody.content[0].text
