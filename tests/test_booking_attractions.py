"""Booking.com attractions (booking.com/attractions): the address, the converter on what Booking.com's own data gave (read live 5 Nov 2026: the Apollo store and the SearchResultsProducts service) and the tool."""

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
NO_FILTERS = {"filterByLabel": [], "filterByMinRating": [], "filterBySupportedLanguage": []}
SEARCHED = {"place": "pt/lisbon", "day": "2027-03-07", "day_to": "2027-03-07", "adults": 2, "currency": "EUR", "filters": NO_FILTERS}
SORTS = [{"sort": "Our top picks", "key": "trending", "read": 30, "has_next": True, "first_page_from": "page"}, {"sort": "Best reviewed", "key": "highest_weighted_rating", "read": 30, "has_next": True, "first_page_from": "api"}]
SLUG = "pr4z1zrjq9hl-skip-the-queue-tickets-into-the-lisbon-oceanarium"


def row(title="Tickets into The Lisbon Oceanarium", frm=25.5, cur="EUR", rating5=4.6, reviews=4218, duration="3 hours", free=False, public=None, best=1, sort="Our top picks", slug=SLUG, flags=None, until=None, ident="PR4z1zRjQ9hl"):
    """An activity as the script reads it; the first one is the real first activity of Lisbon (read 5 Nov 2026: 25.5 EUR, 4.6 of 5 from 4,218 reviews, the page showed 9.2 and 26)."""
    return {"sort": sort, "rank": 1, "id": ident, "title": title, "slug": slug, "cur": cur, "from": frm, "public_from": public if public is not None else frm, "discounted": public is not None and public != frm, "rating5": rating5, "reviews": reviews,
            "scale": "FIVE_POINT", "duration": duration, "duration_iso": "PT3H" if duration else None, "duration_type": "FIXED" if duration else None, "free_cancel": free, "refundable_now": free, "cancel_until": until, "cancel_period": "P1D" if free else None,
            "labels": ["free_cancellation"] if free else [], "flags": flags if flags is not None else (["bestseller"] if best else []), "best_seller": best, "best_seller_text": "#1 Best seller in Lisbon" if best else None, "primary_label": None}


def answer(rows=None, **over):
    base = {"ok": True, "place": "pt/lisbon", "country": "pt", "searched": dict(SEARCHED), "page_filters": NO_FILTERS, "filters_match": True, "ufi": -2167973, "results_matching": 4128, "results_in_city": 4128,
            "sorts": [dict(x) for x in SORTS], "failed": None, "rows": rows if rows is not None else [row()]}
    base.update(over)
    return json.dumps(base)


def test_the_address_asks_the_day_the_travellers_and_euro_and_no_filter_unless_the_trip_has_one():
    assert RECIPE["url"] == "https://www.booking.com/attractions/searchresults/pt/lisbon.html?date_from=2027-03-07&date_to=2027-03-07&adults=2&selected_currency=EUR"
    assert EXPECT["group"] == "Booking.com attractions in Lisbon, 07 Mar 2027" and EXPECT["labels"] == [] and EXPECT["min_rating"] == [] and EXPECT["filters"] == NO_FILTERS
    assert "__REQUEST__" not in RECIPE["script"] and '"highest_weighted_rating"' in RECIPE["script"] and '"limit": 30' in RECIPE["script"]
    assert places()["lisbon"]["path"] == "pt/lisbon"


def test_the_trips_wishes_become_the_sites_own_filters_in_the_address_and_in_the_request():
    r = booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 30, ["Sintra"], True, 40.0, 8.5, True, "EN")
    assert r["url"].endswith("&filter_by_label[]=free_cancellation&filter_by_label[]=skip_the_line&filter_by_min_rating[]=4.0&filter_by_language[]=en")
    assert r["expect"]["min_rating"] == ["4.0"] and r["expect"]["min_rating_wish"] == 8.5 and r["expect"]["language"] == ["en"] and r["expect"]["title_contains"] == ["sintra"] and r["expect"]["max_price"] == 40.0
    assert r["expect"]["filters"] == {"filterByLabel": ["free_cancellation", "skip_the_line"], "filterByMinRating": ["4.0"], "filterBySupportedLanguage": ["en"]} and '"filterByMinRating": ["4.0"]' in r["script"]
    assert booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, min_rating=9.6)["expect"]["min_rating"] == ["4.5"]
    assert booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, min_rating=5.0)["expect"]["min_rating"] == []      # the site has no box that low: judged on the activities


@pytest.mark.parametrize("bad", [dict(place_path="lisbon"), dict(place_path="pt/"), dict(place_path="pt/lisbon", adults=0), dict(place_path="pt/lisbon", limit=61), dict(place_path="pt/lisbon", language="xx")])
def test_a_bad_place_window_or_language_is_refused(bad):
    with pytest.raises(ValueError):
        booking_attractions_recipe(bad["place_path"], "X", DAY, bad.get("adults", 2), bad.get("limit", 30), language=bad.get("language"))


def test_an_activity_becomes_a_comparison_only_row_with_the_exact_from_price_the_ten_point_rating_and_the_cancellation_cutoff():
    rows = convert(answer([row(), row("Lisboa: Tour Fatima", 29.05, rating5=4.8, reviews=56, duration="9 hours", free=True, public=35.0, best=None, until="2027-03-06T10:00:00", slug="pr6i3usz5kzw-fatima-tour", ident="PRfat")]), {"expect": EXPECT}, "Activities")
    assert rows.problems == [] and rows.read == 2 and rows.total == 4128
    a, b = rows.offers
    assert a.price_total == 25.5 and a.currency == "EUR" and a.quotable is False and a.details["rating"] == "9.2 (4,218 reviews)" and a.details["duration"] == "3 hours" and a.details["from_tab"] == "Top picks"
    assert a.details["badges"] == "#1 Best seller in Lisbon" and a.link == f"https://www.booking.com/attractions/pt/{SLUG}.en-gb.html" and a.details["cancellation"] == "not free (Booking.com's own flag)" and a.flexible is None
    assert b.details["duration"] == "9 hours" and b.details["cancellation"] == "Free cancellation until 2027-03-06 10:00 (Booking.com's own data)" and b.flexible is True and b.group == EXPECT["group"]
    assert "exact (the page shows it rounded up)" in b.price_basis and "discounted from EUR 35" in b.price_basis and "per person" in b.price_basis
    assert any("Read: Our top picks: 30 activities, Best reviewed: 30 activities" in n for n in rows.extra_notes) and any("Booking.com says 4,128 activities match this search (of 4,128 in the city)" in n for n in rows.extra_notes)


def test_the_languages_and_the_date_an_activity_is_bookable_from_come_from_booking_coms_own_data():
    r = row(ident="lang")
    r.update({"guide_langs": ["German", "English"], "audio_langs": ["Portuguese"], "available_from": "2026-11-07", "booking_window_days": 180})
    o = convert(answer([r]), {"expect": EXPECT}, "Activities").offers[0]
    assert o.details["language"] == "guide in German, English; audio in Portuguese" and o.details["available_from"] == "bookable from 2026-11-07 (up to 180 days ahead)"
    plain = convert(answer([row()]), {"expect": {**EXPECT, "language": ["en"]}}, "Activities").offers[0]
    assert plain.details["language"] == "filtered by Booking.com for en" and plain.details["available_from"] is None


def test_the_same_activity_in_top_picks_and_best_reviewed_is_one_row_with_both_labels():
    rows = convert(answer([row(sort="Our top picks"), row(sort="Best reviewed"), row("Tuk tuk tour", 60.0, rating5=5.0, reviews=2552, sort="Best reviewed", ident="PRtuk", slug="prtuk-tuk")]), {"expect": EXPECT}, "Activities")
    assert len(rows.offers) == 2 and rows.offers[0].details["from_tab"] == "Top picks and Best reviewed" and rows.offers[1].details["from_tab"] == "Best reviewed"


def test_the_wishes_judge_the_activities_and_an_unknown_value_is_not_met():
    exp = {**EXPECT, "free_cancellation": True, "max_price": 30.0, "min_rating_wish": 9.0}
    rows = convert(answer([row("A", 26.0, free=True, ident="a"), row("B", 40.0, free=True, ident="b"), row("C", 20.0, free=False, ident="c"), row("D", 20.0, rating5=None, reviews=None, free=True, ident="d"), row("E", 20.0, rating5=4.2, free=True, ident="e")]), {"expect": exp}, "Activities")
    by = {o.name: o.fits for o in rows.offers}
    assert by == {"A": True, "B": False, "C": False, "D": None, "E": False}        # C: Booking.com says it is not free cancellation; D: no rating yet (unknown, never assumed); E: 8.4 on its ten points
    assert next(o for o in rows.offers if o.name == "D").unconfirmed == ["rating"]


def test_skip_the_line_is_booking_coms_own_filter_and_a_row_is_marked_from_its_own_flag():
    exp = {**EXPECT, "labels": ["skip_the_line"]}
    rows = convert(answer([row("A", ident="a", flags=["aiBadgesSkipTheLine"]), row("B", ident="b", flags=[])], searched={**SEARCHED, "filters": {**NO_FILTERS, "filterByLabel": ["skip_the_line"]}}), {"expect": {**exp, "filters": {**NO_FILTERS, "filterByLabel": ["skip_the_line"]}}}, "Activities")
    assert [o.fits for o in rows.offers] == [True, None] and rows.offers[0].details["badges"].endswith("skip the line") and rows.offers[1].unconfirmed == ["skip the line"] and any("Skip the line is Booking.com's own filter" in n for n in rows.extra_notes)


def test_title_words_leave_out_the_activities_that_do_not_have_them_and_say_how_many():
    exp = {**EXPECT, "title_contains": ["sintra"]}
    rows = convert(answer([row("Lisbon: Sintra and Cascais", ident="a"), row("Fado night", ident="b"), row("Pena Palace tickets", ident="c")]), {"expect": exp}, "Activities")
    assert [o.name for o in rows.offers] == ["Lisbon: Sintra and Cascais"] and rows.read == 3
    assert any("2 of these results have none of the wish's title words (sintra)" in n for n in rows.extra_notes)


def test_the_filters_the_request_carried_must_be_the_ones_asked():
    r = booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 30, None, True, None, 9.0)
    sent = {"filterByLabel": ["free_cancellation"], "filterByMinRating": ["4.5"], "filterBySupportedLanguage": []}
    assert convert(answer(searched={**SEARCHED, "filters": sent}), {"expect": r["expect"]}, "Activities").problems == []
    assert any("request carried the filters" in p for p in convert(answer(), {"expect": r["expect"]}, "Activities").problems)
    assert any("request carried the filters" in p for p in convert(answer(searched={**SEARCHED, "filters": {**sent, "filterByLabel": ["skip_the_line"]}}), {"expect": r["expect"]}, "Activities").problems)


@pytest.mark.parametrize("change,fragment", [
    ({"searched": {**SEARCHED, "day": "2027-03-08"}}, "day 2027-03-08 instead of 2027-03-07"),
    ({"searched": {**SEARCHED, "adults": 3}}, "adults 3 instead of 2"),
    ({"searched": {**SEARCHED, "currency": "INR"}}, "currency INR instead of EUR"),
    ({"searched": {**SEARCHED, "place": "pt/porto"}}, "place pt/porto instead of pt/lisbon"),
    ({"sorts": [SORTS[0]]}, "both the Our top picks and the Best reviewed sorts must be read"),
    ({"sorts": [SORTS[0], {**SORTS[1], "read": 0}], "failed": ["Best reviewed page 2: answered 500"]}, "no activity of the Best reviewed sort was read (Best reviewed page 2: answered 500)"),
    ({"rows": []}, "could not be read, never that there are none"),
])
def test_a_page_that_searched_something_else_or_changed_is_refused_with_the_fix(change, fragment):
    problems = convert(answer(**change), {"expect": EXPECT}, "Activities").problems
    assert any(fragment in p for p in problems), problems


def test_a_price_in_another_currency_is_refused_never_converted():
    r = convert(answer([row(cur="INR")]), {"expect": EXPECT}, "Activities")
    assert r.offers == [] and any("not euro" in p for p in r.problems)


def test_a_script_error_and_a_text_that_is_not_json_come_back_as_a_readable_problem():
    assert "reported: Booking.com shows a human check" in convert(json.dumps({"ok": False, "error": "Booking.com shows a human check (captcha)."}), {"expect": EXPECT}, "Activities").problems[0]
    assert "not the script's JSON text" in convert("From | EUR 35", {"expect": EXPECT}, "Activities").problems[0]


def test_the_converter_is_found_by_the_server_and_works_through_convert_all():
    assert "booking_attractions" in modules()
    offers, sources, problems, by_price, notes = convert_all([{"site": "booking_attractions", "result": answer(), "url": RECIPE["url"], "wishes": {"expect": EXPECT}}], {"expect": EXPECT})
    assert problems == [] and len(offers) == 1 and sources[0].read == 1 and sources[0].of == 4128 and by_price is False      # read 1 of the 4,128 activities Booking.com says exist in the city


@pytest.mark.anyio
async def test_the_tool_knows_lisbon_asks_for_a_path_for_another_city_and_returns_the_address_and_wishes():
    async with Client(create_server(Settings())) as c:
        got = (await c.call_tool("booking_attractions_recipe", {"place": "Lisbon", "day": "2027-03-07", "free_cancellation": True, "max_price": 50, "title_contains": ["Sintra"], "min_rating": 9, "skip_the_line": True, "language": "en"})).structured_content
        assert "filter_by_label[]=free_cancellation&filter_by_label[]=skip_the_line&filter_by_min_rating[]=4.5&filter_by_language[]=en" in got["url"] and got["wishes"]["expect"]["title_contains"] == ["sintra"]
        for line in ("Free cancellation (operator; the site's own filter)", "Skip the line (operator; the site's own filter)", "Max 50 EUR per person (operator)", "Language en (operator; the site's own filter)"):
            assert line in got["filters_used"], got["filters_used"]
        assert any("sintra" in f for f in got["filters_used"]) and any("Rating 9 or more" in f for f in got["filters_used"]) and any("agency rule" in f for f in got["filters_used"])
        other = (await c.call_tool("booking_attractions_recipe", {"place": "Athens", "day": "2027-03-07", "title_contains": ["tour"]})).structured_content
        assert other["ok"] is False and other["searched"] is False and other["known_places"][:3] == ["Lisbon", "Porto", "Faro"] and len(other["known_places"]) == len(set(other["known_places"])) and "place_path" in other["next"]
        porto = (await c.call_tool("booking_attractions_recipe", {"place": "Porto", "day": "2027-03-07", "title_contains": ["tour"]})).structured_content      # known since 6 Nov 2026
        assert "/pt/porto.html?" in porto["url"] and porto["wishes"]["expect"]["place"] == "pt/porto"
        madeira = (await c.call_tool("booking_attractions_recipe", {"place": "Madeira", "day": "2027-03-07", "title_contains": ["tour"]})).structured_content
        assert "/pt/funchal.html?" in madeira["url"]
        athens = (await c.call_tool("booking_attractions_recipe", {"place": "Athens", "day": "2027-03-07", "place_path": "gr/athens", "title_contains": ["tour"]})).structured_content
        assert "/gr/athens.html?" in athens["url"]
        bad = await c.call_tool("booking_attractions_recipe", {"place": "X", "day": "2027-03-07", "place_path": "porto", "title_contains": ["tour"]})
        assert bad.is_error and "country code" in bad.content[0].text



@pytest.mark.anyio
async def test_the_tool_needs_title_words_because_the_list_is_the_whole_city():
    async with Client(create_server(Settings())) as c:
        for words in (None, [], ["  "]):
            args = {"place": "Lisbon", "day": "2027-03-07"} | ({} if words is None else {"title_contains": words})
            r = await c.call_tool("booking_attractions_recipe", args)
            assert r.is_error and "title_contains is needed" in r.content[0].text and "57 of 60" in r.content[0].text
