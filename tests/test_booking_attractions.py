"""Booking.com attractions (booking.com/attractions): the address, the converter on what the real page gave (27 Oct 2026) and the tool."""

import json
from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.sites import convert_all, modules
from myt_mcp.sites.booking_attractions import booking_attractions_recipe, convert, places

DAY = date(2027, 3, 7)
RECIPE = booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2)
EXPECT = RECIPE["expect"]
FORM = {"place": "pt/lisbon", "day": "2027-03-07", "day_to": "2027-03-07", "adults": 2, "currency": "EUR"}


def row(title="Tickets into The Lisbon Oceanarium", frm=26.0, cur="€", rating=9.2, reviews=4205, duration=None, free=False, was=None, best="1", path="/attractions/pt/pr4z1zrjq9hl-skip-the-queue-tickets-into-the-lisbon-oceanarium.html", avail=None):
    """A card as the script reads it; the first one is the real first card of 27 Oct 2026 (Lisbon, 7 Mar 2027, 2 adults, EUR)."""
    return {"title": title, "cur": cur, "from": frm, "was": was, "rating": rating, "reviews": reviews, "duration": duration, "free_cancel": free, "best_seller": best, "available_from": avail, "path": path}


def answer(rows=None, **over):
    base = {"ok": True, "form": dict(FORM), "heading": "Lisbon experiences", "cards_on_page": 15, "unparsed": [], "rows": rows if rows is not None else [row()]}
    base.update(over)
    return json.dumps(base)


def test_the_address_asks_the_day_the_travellers_and_euro_for_the_place():
    url = RECIPE["url"]
    assert url == "https://www.booking.com/attractions/searchresults/pt/lisbon.html?date_from=2027-03-07&date_to=2027-03-07&adults=2&selected_currency=EUR"
    assert EXPECT["group"] == "Booking.com attractions in Lisbon, 07 Mar 2027" and "__EXPECT__" not in RECIPE["script"] and "__LIMIT__" not in RECIPE["script"]
    assert places()["lisbon"]["path"] == "pt/lisbon"


@pytest.mark.parametrize("bad", [dict(place_path="lisbon"), dict(place_path="pt/"), dict(place_path="pt/lisbon", adults=0), dict(place_path="pt/lisbon", limit=61)])
def test_a_bad_place_or_window_is_refused(bad):
    with pytest.raises(ValueError):
        booking_attractions_recipe(bad["place_path"], "X", DAY, bad.get("adults", 2), bad.get("limit", 30))


def test_a_card_becomes_a_comparison_only_row_with_the_from_price_and_what_the_card_says():
    rows = convert(answer([row(), row("Lisboa: Tour Fatima", 35.0, rating=9.6, reviews=56, duration="9 hours", free=True, was=35.0, best=None)]), {"expect": EXPECT}, "Activities")
    assert rows.problems == [] and rows.read == 2 and rows.total == 2
    a, b = rows.offers
    assert a.price_total == 26.0 and a.currency == "EUR" and a.quotable is False and a.details["rating"] == "9.2 (4,205 reviews)" and a.details["duration"] == "not shown on the card"
    assert a.details["badges"] == "#1 Best seller" and a.link.startswith("https://www.booking.com/attractions/pt/pr4z1zrjq9hl")
    assert b.details["duration"] == "9 hours" and "Free cancellation" in b.details["cancellation"] and b.group == EXPECT["group"] and "per person" in b.price_basis
    assert any("not by price" in n for n in rows.extra_notes) and any("does not say how many" in n for n in rows.extra_notes)


def test_a_discounted_card_says_what_it_cost_before():
    r = convert(answer([row("Lisbon: Sintra", 29.05, was=35.0)]), {"expect": EXPECT}, "Activities").offers[0]
    assert r.price_total == 29.05 and "was EUR 35 before the discount" in r.price_basis


def test_the_wishes_judge_the_cards_and_an_unknown_value_is_not_met():
    exp = {**EXPECT, "free_cancellation": True, "max_price": 30.0, "min_rating": 9.0}
    rows = convert(answer([row("A", 26.0, free=True), row("B", 40.0, free=True), row("C", 20.0, free=False), row("D", 20.0, rating=None, reviews=None, free=True)]), {"expect": exp}, "Activities")
    by = {o.name: o.fits for o in rows.offers}
    assert by == {"A": True, "B": False, "C": None, "D": None}        # D: no rating shown, C: free cancellation not shown: unknown, never assumed


def test_title_words_leave_out_the_cards_that_do_not_have_them_and_say_how_many():
    exp = {**EXPECT, "title_contains": ["sintra"]}
    rows = convert(answer([row("Lisbon: Sintra and Cascais"), row("Fado night"), row("Pena Palace tickets")]), {"expect": exp}, "Activities")
    assert [o.name for o in rows.offers] == ["Lisbon: Sintra and Cascais"] and rows.read == 3
    assert any("2 of these cards have none of the wish's title words (sintra)" in n for n in rows.extra_notes)


@pytest.mark.parametrize("change,fragment", [
    ({"form": {**FORM, "day": "2027-03-08"}}, "day 2027-03-08 instead of 2027-03-07"),
    ({"form": {**FORM, "adults": 3}}, "adults 3 instead of 2"),
    ({"form": {**FORM, "currency": "INR"}}, "currency INR instead of EUR"),
    ({"form": {**FORM, "place": "pt/porto"}}, "place pt/porto instead of pt/lisbon"),
    ({"unparsed": ["#9 something new"]}, "does not know"),
    ({"rows": []}, "could not be read, never that there are none"),
])
def test_a_page_that_searched_something_else_or_changed_is_refused_with_the_fix(change, fragment):
    problems = convert(answer(**change), {"expect": EXPECT}, "Activities").problems
    assert any(fragment in p for p in problems), problems


def test_a_price_in_another_currency_is_refused_never_converted():
    r = convert(answer([row(cur="Rs.")]), {"expect": EXPECT}, "Activities")
    assert r.offers == [] and any("not euro" in p for p in r.problems)


def test_a_script_error_and_a_text_that_is_not_json_come_back_as_a_readable_problem():
    assert "reported: Booking.com shows a human check" in convert(json.dumps({"ok": False, "error": "Booking.com shows a human check (captcha)."}), {"expect": EXPECT}, "Activities").problems[0]
    assert "not the script's JSON text" in convert("From | EUR 35", {"expect": EXPECT}, "Activities").problems[0]


def test_the_converter_is_found_by_the_server_and_works_through_convert_all():
    assert "booking_attractions" in modules()
    offers, sources, problems, by_price, notes = convert_all([{"site": "booking_attractions", "result": answer(), "url": RECIPE["url"], "wishes": {"expect": EXPECT}}], {"expect": EXPECT})
    assert problems == [] and len(offers) == 1 and sources[0].read == 1 and sources[0].of == 1 and by_price is False


@pytest.mark.anyio
async def test_the_tool_knows_lisbon_asks_for_a_path_for_another_city_and_returns_the_address_and_wishes():
    async with Client(create_server(Settings())) as c:
        got = (await c.call_tool("booking_attractions_recipe", {"place": "Lisbon", "day": "2027-03-07", "free_cancellation": True, "max_price": 50, "title_contains": ["Sintra"]})).structured_content
        assert got["url"] == RECIPE["url"] and got["wishes"]["expect"]["title_contains"] == ["sintra"] and got["wishes"]["expect"]["free_cancellation"] is True
        assert "Free cancellation (operator)" in got["filters_used"] and "Max 50 EUR per person (operator)" in got["filters_used"] and any("sintra" in f for f in got["filters_used"])
        other = (await c.call_tool("booking_attractions_recipe", {"place": "Porto", "day": "2027-03-07"})).structured_content
        assert other["ok"] is False and other["searched"] is False and other["known_places"] == ["Lisbon"] and "place_path" in other["next"]
        porto = (await c.call_tool("booking_attractions_recipe", {"place": "Porto", "day": "2027-03-07", "place_path": "pt/porto"})).structured_content
        assert "/pt/porto.html?" in porto["url"] and porto["wishes"]["expect"]["place"] == "pt/porto"
        bad = await c.call_tool("booking_attractions_recipe", {"place": "X", "day": "2027-03-07", "place_path": "porto"})
        assert bad.is_error and "country code" in bad.content[0].text
