"""GetYourGuide recipes (the list of a search and the exact price of one activity), read from the site's own list and availability calls.

The REAL scripts run in a real browser (Playwright's Chromium) on getyourguide.com pages that serve what the real site served on 6 Nov 2026: the search page with its state (window.__INITIAL_STATE__.sdui, a "See more"
block of route landing-pages/srp holding the template of the list call), POST travelers-api.getyourguide.com/user-interface/landing-pages/srp/blocks answering 24 cards a page (title, city, "3 hours • Private option available",
rating, reviews, badges, the price object with starting_price / base_price / price_category_label, a link gyg://tours/<id>) and a tracking event with result_count; and the activity page with its traveller categories in the
state and POST .../activity-details-page/blocks answering the option card and the WebCheckTourAvailabilityAction tracking event (categories with ages, options with start times and the price of the whole group, price per person
by category). Nothing leaves the machine. The mock prices the group from the travellers the script sends, so a wrong category or count shows as a wrong total."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.getyourguide_activity import getyourguide_activity_recipe
from myt_mcp.sites.getyourguide_find import _fits_hours, _span, filter_list, getyourguide_find_recipe, language_code

DAY = date(2027, 3, 5)
CORS = {"access-control-allow-origin": "https://www.getyourguide.com", "access-control-allow-headers": "*", "access-control-allow-methods": "POST, GET, OPTIONS"}


# ---------------------------------------------------------------- the list


def card(tour, title, meta="3 hours", rating=4.8, reviews=1200, price=70.0, base=None, pct=0, per="per person", badges=(), city="Lisbon", cur="EUR"):
    atoms = [{"id": f"{tour}-context-label", "type": "textAtom", "text": {"text": city}}, {"id": f"{tour}-title", "type": "textAtom", "text": {"text": title}}, {"id": f"{tour}-attributes", "type": "textAtom", "text": {"text": meta}}]
    if rating is not None:
        atoms += [{"id": f"{tour}-polished-rating-text", "type": "textAtom", "text": {"text": f"{rating:g}"}}, {"id": f"{tour}-polished-review-description", "type": "textAtom", "text": {"text": f"({reviews:,})"}}]
    atoms += [{"id": f"{b}-badge", "type": "textAtom", "text": {"text": b}} for b in badges]
    pr = {"base_price": base if base is not None else price, "currency": cur, "currency_symbol": "€", "formatted_base_price": f"€{base or price:g}", "price_category": "individual", "price_category_label": per,
          "starting_price": price, "unformatted_booking_fee": 0, "unformatted_discount_percentage": pct}
    return {"__entity": "block", "id": str(tour), "type": "verticalContainer", "content": atoms + [{"id": f"{tour}-price", "type": "container", "price": pr}],
            "interaction": {"type": "openLinkInteractionConfiguration", "link": f"gyg://tours/{tour}?date_from=2027-03-05&date_to=2027-03-05&ranking_uuid=abc"}}


def cards_page(n, start=1, **extra):
    return [card(1000 + i, f"Lisbon Food Tour number {i}", rating=4.5 + (i % 5) / 10, reviews=100 * i, price=40 + i, **extra) for i in range(start, start + n)]


SPECIAL = [card(603, "Food and Wine Small Group Walking Tour", "3 hours", 4.9, 5219, 70, badges=("topPick",)),
           card(462536, "Eat & Walk Through Lisbon: A Local Food Experience", "3 hours • Private option available • Skip the line", 4.9, 735, 71.1, base=79, pct=10, badges=("topRated",)),
           card(777, "Private Lisbon Food Tour with a Local", "2.5 hours • Private group", 4.7, 80, 240, per="group up to 4"),
           card(888, "Pasta Cooking Class with Unlimited Wine", "2 - 2.5 hours", 4.8, 16903, 125),
           card(999, "Lisbon Food Tour (new)", "1.5 - 3 hours", None, 0, 30, badges=("newActivity",))]

TEMPLATE = {"page": 2, "locationId": 42, "contentIdentifier": "srp-activity-grid", "sortingSelected": "popularity", "filtersUpdated": [], "datesSelected": {"fromDate": "2027-03-05", "toDate": "2027-03-05"},
            "selectedSortingOrderValue": "popularity", "additionalParams": {"q": "Lisbon food tour", "rawUserQuery": "Lisbon food tour"}, "injectedCardsCount": 0, "templateMatcherRuleId": "search.with_location", "templateLocationId": 42}


def search_html(template=TEMPLATE, body="Lisbon food tour"):
    state = {"sdui": {"layout": {"content": [{"type": "verticalList", "content": [{"type": "loadMore", "id": "load-more", "route": "landing-pages/srp", "payload": template}] if template else []}]}}}
    return f"<html><head><title>GetYourGuide</title></head><body><h1>{body}</h1><script>window.__INITIAL_STATE__ = {json.dumps(state)};</script></body></html>"


def list_answer(cards, total=737):
    results = [{"booking_fee": 0, "currency": "EUR", "discounted_price": c_price(c), "original_price": c_price(c), "total_price": c_price(c), "tour_id": int(c["id"]), "virtual_activity_id": 0} for c in cards]
    return {"contractVersion": "1", "content": [{"type": "grid", "id": "grid", "content": cards}],
            "trackingEvents": [{"event": {"eventName": "SearchResultsRequest", "properties": {"result_count": total, "result_count_visible": len(cards), "search_results": results, "extracted_location_details": {"id": 42, "type": "city"}, "sorting": {"field": "popularity", "direction": "desc"}}}}]}


def c_price(c):
    return next(x["price"]["starting_price"] for x in c["content"] if "price" in x)


def run_script(recipe, serve_api, html, url=None, hostname="www.getyourguide.com"):
    sync_api = pytest.importorskip("playwright.sync_api")
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def serve(route):
        u = urlparse(route.request.url)
        if u.hostname == "travelers-api.getyourguide.com":
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=CORS, body="")
            else:
                serve_api(route, u)
        elif u.hostname == hostname:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto(url or recipe["url"])
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out


def run_find(pages=None, seen=None, status=200, html=None, total=737, fail_pages=(), **kw):
    kw.setdefault("query", "Lisbon food tour")
    kw.setdefault("day", DAY)
    recipe = getyourguide_find_recipe(**kw)
    pages = pages if pages is not None else {1: SPECIAL + cards_page(19, 1), 2: cards_page(24, 20)}

    def api(route, u):
        body = json.loads(route.request.post_data or "{}")
        if seen is not None:
            seen.append({"query": parse_qs(u.query), "body": body, "headers": route.request.headers})
        p = body["payload"]["page"]
        if p in fail_pages:
            route.fulfill(status=500, headers=CORS, content_type="text/plain", body="boom")
        elif status != 200 or p not in pages:
            route.fulfill(status=status if status != 200 else 200, headers=CORS, content_type="application/json", body=json.dumps({"content": []}) if status == 200 else "denied")
        else:
            route.fulfill(status=200, headers=CORS, content_type="application/json", body=json.dumps(list_answer(pages[p], total)))
    return run_script(recipe, api, html or search_html()), recipe


def convert_find(out, recipe, **extra):
    wishes = {"expect": {**recipe["expect"], **extra}}
    return convert_all([{"site": "getyourguide_find", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)


def rows_of(out):
    from myt_mcp.sites import expand
    return json.loads(expand(out))["rows"]


def test_the_filters_go_to_the_sites_own_list_call_with_values_that_keep_every_product_that_meets_the_wish():
    f, said = filter_list(max_price=60.5, min_rating=4.6, max_hours=3, language="pt", features=["skip_the_line", "private_tour"])
    got = {x["filterType"]: x["value"] for x in f}
    assert got["reviewRatingRanges"] == ["4.5"]                        # the largest step at or under the wish; the exact rating is judged here
    assert got["durationRanges"] == ["0", "1"]                         # 3 hours may sit in "0-3" or "3-5": both stay in, the exact duration is judged here
    assert got["languages"] == ["pt"] and got["services"] == ["stl", "prt"] and got["price"] == {"min": 0, "max": 61}
    assert len(said) == 5 and any("price of the whole group" in s for s in said)
    assert filter_list(None, 2.0, 100, None, [])[0] == []              # nothing under 3.0, nothing for a stay of days
    assert filter_list(None, 4.0, 8, None, [])[0][1]["value"] == ["0", "1", "2", "3"]
    assert filter_list(None, None, 2, "he", [])[0] == [{"filterType": "durationRanges", "value": ["0"]}]      # Hebrew is not in the site's language list


def test_validation_and_helpers():
    assert getyourguide_find_recipe("Lisbon tours", DAY, 24, 0, None, False, None, 9.0)["expect"]["min_rating"] == 4.5
    for kw in ({"query": ""}, {"query": "x" * 130}, {"query": "a b", "limit": 73}, {"query": "a b", "offset": -1}, {"query": "a b", "max_price": 0}, {"query": "a b", "min_rating": 0}, {"query": "a b", "features": ["nope"]}, {"query": "a b", "sort": "nope"}):
        with pytest.raises(ValueError):
            getyourguide_find_recipe(**kw)
    assert language_code("Hebrew") == "he" and language_code("PT") == "pt" and language_code(None) is None
    with pytest.raises(ValueError):
        language_code("123")
    assert _span("1.5 hours") == (1.5, 1.5) and _span("2 - 2.5 hours") == (2, 2.5) and _span("45 minutes") == (0.75, 0.75) and _span("2 days") == (48, 48) and _span("3 hours • Skip the line") == (3, 3) and _span(None) is None
    assert _span("1 hour - 90 minutes") == (1, 1.5) and _span("9.5 - 10 hours • Skip the line") == (9.5, 10) and _span("Skip the line") is None
    assert _fits_hours("3 hours", 3) is True and _fits_hours("3.5 hours", 3) is False and _fits_hours("1.5 - 3 hours", 2.5) is None and _fits_hours("4 - 5 hours", 3) is False and _fits_hours("n/a", 3) is None
    r = getyourguide_find_recipe("Lisbon food tour", DAY, sort="price")
    assert '"sort": "price_asc"' in r["script"] and r["url"] == "https://www.getyourguide.com/s/?q=Lisbon+food+tour&date_from=2027-03-05&date_to=2027-03-05"


def test_the_script_replays_the_pages_own_list_call_page_by_page_with_the_filters_and_the_sort():
    seen: list = []
    out, recipe = run_find(seen=seen, limit=48, max_price=100, min_rating=4.5, sort="price")
    assert [s["body"]["payload"]["page"] for s in seen] == [1, 2]            # 48 cards = 2 pages of 24
    p = seen[0]["body"]["payload"]
    assert p["filtersUpdated"] == recipe["expect"]["filters"] and p["sortingSelected"] == "price_asc" and p["selectedSortingOrderValue"] == "price_asc"
    assert p["locationId"] == 42 and p["contentIdentifier"] == "srp-activity-grid" and p["templateMatcherRuleId"] == "search.with_location" and p["additionalParams"]["q"] == "Lisbon food tour" and p["datesSelected"]["fromDate"] == "2027-03-05"
    h = seen[0]["headers"]
    assert h["accept-currency"] == "EUR" and h["x-gyg-app-type"] == "Web" and h["visitor-platform"] == "desktop" and "cookie" not in h
    assert seen[0]["query"] == {"q": ["Lisbon food tour"], "date_from": ["2027-03-05"], "date_to": ["2027-03-05"]}
    rows = rows_of(out)
    assert len(rows) == 48 and rows[0]["rank"] == 1 and rows[47]["rank"] == 48
    first = rows[0]
    assert first["id"] == 603 and first["title"] == "Food and Wine Small Group Walking Tour" and first["city"] == "Lisbon" and first["meta"] == "3 hours" and first["rating"] == 4.9 and first["reviews"] == 5219
    assert first["from"] == 70 and first["cur"] == "EUR" and first["per"] == "person" and first["badges"] == ["topPick"] and first["path"] == "/-t603/" and first["was"] is None
    deal = rows[1]
    assert deal["from"] == 71.1 and deal["was"] == 79 and deal["discount_pct"] == 10 and deal["badges"] == ["topRated"]
    assert rows[2]["per"] == "group up to 4" and rows[4]["rating"] is None and rows[4]["badges"] == ["newActivity"]


def test_the_script_reads_a_second_offset_and_takes_the_total_from_the_first_page():
    out, recipe = run_find(limit=10, offset=24)
    rows = rows_of(out)
    assert [r["rank"] for r in rows] == list(range(25, 35))
    res = convert_find(out, recipe)
    assert res[2] == [] and any("results 25 to 34" in n for n in res[4])


def test_every_card_becomes_an_offer_with_the_exact_price_the_deal_and_the_group_price_said():
    out, recipe = run_find(limit=5)
    offers, sources, problems, _, notes = convert_find(out, recipe)
    assert problems == [] and len(offers) == 4        # the pasta class has none of the title words: it is padding
    by = {o.name: o for o in offers}
    first = by["Food and Wine Small Group Walking Tour"]
    assert first.price_total == 70 and first.currency == "EUR" and "per person" in first.price_basis and first.link == "https://www.getyourguide.com/-t603/" and first.details["badges"] == "Top pick"
    deal = by["Eat & Walk Through Lisbon: A Local Food Experience"]
    assert deal.price_total == 71.1 and "was 79 EUR, 10% off" in deal.price_basis and "skip the line" in deal.details["flags"].lower() and "private option" in deal.details["private_or_group"]
    private = by["Private Lisbon Food Tour with a Local"]
    assert private.price_total == 240 and "whole group" in private.price_basis and "per group up to 4" in private.price_basis
    new = by["Lisbon Food Tour (new)"]
    assert new.details["rating"] == "not rated yet"
    assert any("1 of these results have none of the wish's title words" in n for n in notes) and any("1 row(s) are priced per GROUP" in n for n in notes)
    assert sources and "getyourguide" in str(sources).lower()


def test_wishes_are_judged_by_the_server_from_the_rows_and_a_group_price_is_not_called_too_dear_for_one_person():
    out, recipe = run_find(limit=5, max_price=100, min_rating=4.8, max_hours=2.5, free_cancellation=True)
    offers, *_ = convert_find(out, recipe, max_price=100, min_rating=4.8, max_hours=2.5, free_cancellation=True)
    by = {o.name: o for o in offers}
    assert by["Food and Wine Small Group Walking Tour"].fits is False                       # 3 hours is over 2.5
    private = by["Private Lisbon Food Tour with a Local"]
    assert private.fits is False                                                               # rating 4.7 is clearly under 4.8
    new = by["Lisbon Food Tour (new)"]
    assert new.fits is None and {"rating", "duration", "free cancellation"} <= set(new.unconfirmed)       # no rating yet, "1.5 - 3 hours" straddles the limit, the list has no cancellation field
    # the price of a private tour is for the group: over the limit does not say it is over per person
    offers, *_ = convert_find(out, recipe, max_price=100, min_rating=None, max_hours=None, free_cancellation=False)
    private = {o.name: o for o in offers}["Private Lisbon Food Tour with a Local"]
    assert private.fits is None and "price" in private.unconfirmed
    offers, *_ = convert_find(out, recipe, max_price=300, min_rating=None, max_hours=None, free_cancellation=False)
    assert {o.name: o for o in offers}["Private Lisbon Food Tour with a Local"].fits is True


def test_the_sort_orders_of_the_site_are_described_as_they_were_read():
    out, recipe = run_find(limit=3, sort="rating")
    assert any("not strictly by the rating number" in n for n in convert_find(out, recipe)[4])
    out, recipe = run_find(limit=3, sort="price")
    assert any("own price order" in n for n in convert_find(out, recipe)[4])


def test_a_free_cancellation_wish_stays_unconfirmed_on_the_list_and_the_answer_says_why():
    out, recipe = run_find(limit=5, free_cancellation=True)
    offers, _, problems, _, notes = convert_find(out, recipe, free_cancellation=True)
    assert all(o.fits is None and "free cancellation" in o.unconfirmed for o in offers) and any("no cancellation field" in n for n in notes)


def test_language_and_service_wishes_use_the_sites_own_filters_and_hebrew_is_said_not_to_be_one():
    out, recipe = run_find(limit=5, language="pt", features=["skip_the_line"])
    offers, *_ = convert_find(out, recipe, language="pt", features=["skip_the_line"])
    assert all(o.fits is True for o in offers)          # the rows came from the site's own language and service filters
    out, recipe = run_find(limit=5, language="Hebrew")
    offers, _, _, _, notes = convert_find(out, recipe, language="he")
    assert all(o.fits is None and "language he" in o.unconfirmed for o in offers) and any("no 'he'" in n for n in notes)


def test_the_converter_refuses_what_does_not_match_the_page_asked():
    out, recipe = run_find(limit=3)
    run = lambda **extra: convert_find(out, recipe, **extra)[2]      # noqa: E731
    assert any("searched 'Lisbon food tour', not 'Rome pasta'" in p for p in run(query="Rome pasta"))
    assert any("date is '2027-03-05', not 2027-03-06" in p for p in run(day="2027-03-06"))
    assert any("other filters" in p for p in run(filters=[{"filterType": "languages", "value": ["pt"]}]))
    bad = out.replace('"cur":"EUR"', '"cur":"ILS"') if '"cur":"EUR"' in out else out
    ils = json.loads(out)
    assert ils["ok"]
    from myt_mcp.sites.getyourguide_find import convert
    data = {"ok": True, "query_text": "Lisbon food tour", "date_from": "2027-03-05", "filters_sent": [], "rows": [{"title": "Lisbon food tour", "cur": "ILS", "from": 200, "per": "person", "path": "/-t1/"}]}
    assert any("not EUR" in p for p in convert(json.dumps(data), {"expect": {"query": "Lisbon food tour", "day": "2027-03-05", "filters": [], "title_contains": []}}, "g").problems)
    assert any("not the script's JSON" in p for p in convert("nope", {}, "g").problems) and any("script reported: boom" in p for p in convert(json.dumps({"ok": False, "error": "boom"}), {}, "g").problems)
    assert any("no activity cards" in p for p in convert(json.dumps({"ok": True, "rows": [], "cards_on_page": 0}), {}, "g").problems)
    assert bad


def test_a_later_page_that_fails_keeps_the_first_page_and_says_so():
    out, recipe = run_find(limit=48, fail_pages=(2,))
    res = convert_find(out, recipe)
    assert len(rows_of(out)) == 24 and any("Not every page asked for was read: page 2" in n for n in res[4])


def test_the_script_stops_on_a_check_page_a_wrong_page_a_page_without_a_template_and_a_refused_call():
    recipe = getyourguide_find_recipe("Lisbon food tour", DAY, limit=5)
    assert "human check" in json.loads(run_script(recipe, lambda r, u: r.fulfill(status=200, headers=CORS, body="{}"), "<html><body>Performing security verification</body></html>"))["error"]
    assert "not a GetYourGuide search page" in json.loads(run_script(recipe, lambda r, u: None, search_html(), url="https://www.getyourguide.com/lisbon-l42/"))["error"]
    assert "no list template" in json.loads(run_script(recipe, lambda r, u: None, search_html(template=None)))["error"]
    out, _ = run_find(status=403, limit=5)
    assert "did not answer the list (page 1: answered 403)" in json.loads(out)["error"]
    out, _ = run_find(pages={1: []}, limit=5)
    assert "no activity cards" in json.loads(out)["error"]


@pytest.mark.anyio
async def test_the_tools_ask_first_return_the_url_the_filters_and_the_wishes():
    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        asked = (await c.call_tool("getyourguide_find_recipe", {"query": "Lisbon food tour"})).structured_content
        assert asked["ok"] is False and len(asked["ask_operator"]) == 3
        r = (await c.call_tool("getyourguide_find_recipe", {"query": "Lisbon food tour", "day": "2027-03-05", "free_cancellation": True, "max_price": 80, "max_hours": 4, "min_rating": 4.5, "language": "Portuguese", "features": ["skip_the_line"], "sort": "rating"})).structured_content
        assert r["wishes"]["free_cancellation"] is True and r["wishes"]["max_price"] == 80 and r["expect"]["language"] == "pt" and '"sort": "rating_desc"' in r["script"]
        assert any("Applied by GetYourGuide itself" in f and "price filter" in f for f in r["filters_used"]) and any("Language pt" in f for f in r["filters_used"]) and "offset=48" in r["more"]
        none = (await c.call_tool("getyourguide_find_recipe", {"query": "Lisbon food tour", "operator_answered": True})).structured_content
        assert none["expect"]["filters"] == [] and "ask_operator" not in none
        a = (await c.call_tool("getyourguide_activity_recipe", {"url": ACT_URL + "?x=1", "day": "2027-03-05", "adults": 2, "children_ages": [8], "free_cancellation": True})).structured_content
        assert a["url"] == ACT_URL + "?date_from=2027-03-05&date_to=2027-03-05" and a["wishes"]["expect"]["total"] == 3 and a["wishes"]["free_cancellation"] is True and '"ages": [8]' in a["script"]


# ---------------------------------------------------------------- one activity

ACT_URL = "https://www.getyourguide.com/lisbon-l42/lisbon-food-and-wine-walking-tour-t603/"
ADULT = {"categoryId": 1, "title": "Adult", "subtitle": "(Age 13-99)", "participantType": "individual", "count": 1, "isAutonomous": True, "minimumAge": 13, "maximumAge": 99, "minimumParticipants": 1, "maximumParticipants": 25}
CHILD = {"categoryId": 3, "title": "Child", "subtitle": "(Age 12 and younger)", "participantType": "individual", "count": 0, "isAutonomous": False, "minimumAge": 0, "maximumAge": 12, "minimumParticipants": 1, "maximumParticipants": 25}
EACH = {1: 70, 3: 35}


def activity_html(cats=(ADULT, CHILD)):
    page = [{"text": {"text": t}} for t in ("Highlights", "Local food", "Full description", "A walk", "Includes", "Walking tour", "Guide", "Food tastings", "Not suitable for", "Wheelchair users", "Meeting point", "View details", "Important information",
                                           "Group size", "Standard group: Up to 14 people", "What to bring", "Comfortable shoes", "Know before you go", "Vegan options are not available", "See more", "Support")]
    state = {"sdui": {"layout": {"content": [{"participantSelector": {"participants": list(cats)}, "fromPriceAtPageLoad": {"price": 70, "formattedPrice": "€70"}}] + page}}}
    return f"<html><head><title>Lisbon: Food and Wine Walking Tour</title></head><body><h1>Lisbon: Food and Wine Small Group Walking Tour</h1><script>window.__INITIAL_STATE__ = {json.dumps(state)};</script></body></html>"


def option_card(option=603, lines=None):
    lines = lines or ["Food and Wine Walking Tour Shared" if option == 603 else f"Option {option}", "Duration: 3 hours", "Guide: English", "Reserve now & pay later", "Cancel for free until Dec 16", "Meeting point", "Praça Dom Pedro IV", "Select",
                      "Meet at Praça Dom Pedro IV 101, 1100-202 Lisboa, Portugal", "View details", "Tour option", "Select a starting time", "10:30 AM", "Total price", "All taxes and fees included", "Book now"]
    return {"id": f"carousel-option-card-{option}", "type": "carouselOptionCard", "content": [{"id": f"t{i}", "type": "textAtom", "text": {"text": x}} for i, x in enumerate(lines)]}


def availability_answer(counts, day, slots=("10:30 AM", "3:00 PM", "4:30 PM"), slot_prices=None, each=EACH, titles=None, available=True, lines=None, options=(603,), unavailable=None, header=None):
    titles = titles or {1: "Adult", 3: "Child"}
    breakdown = [{"title": titles[k], "price_per_person": {"amount": each[k], "currency": "EUR"}, "total_price": {"amount": each[k] * n, "currency": "EUR"}, "total_participants": n} for k, n in counts.items() if n]
    total = sum(each[k] * n for k, n in counts.items())
    av = []
    if available:
        for opt in options:
            ts = [{"start_time": s, "price": {"amount": (slot_prices or {}).get(s, total), "currency": "EUR"}} for s in slots]
            av.append({"tour_option_id": opt, "languages": ["en"], "time_slots": ts, "price_breakdown": breakdown * len(ts)})
    head = header or ("%d option%s available" % (len(av), "" if len(av) == 1 else "s") if av else "Not available for your selection")
    content = [{"id": "hdr", "type": "textAtom", "text": {"text": head}}] + ([option_card(o, lines) for o in options] if av else [])
    ev = {"eventName": "WebCheckTourAvailabilityAction", "properties": {"tour_id": 603, "date_selected": day, "last_available_date": "2027-11-02", "update_trigger": "checkAvailabilityButton", "available_options": av, "unavailable_options": unavailable or [],
          "pricing_categories": {"available": [{"id": 1, "code": 1, "count": counts.get(1, 0), "title": "Adult", "max_age": 99, "min_age": 13}, {"id": 3, "code": 3, "count": counts.get(3, 0), "title": "Child", "max_age": 12, "min_age": 0}]}}}
    return {"contractVersion": "1", "content": content, "trackingEvents": [{"event": ev}]}


def run_activity(day=DAY, adults=2, ages=(8,), seen=None, status=200, html=None, url=ACT_URL, answer=None, **kw):
    recipe = getyourguide_activity_recipe(url, day, adults, list(ages), "Food tour")

    def api(route, u):
        body = json.loads(route.request.post_data or "{}")
        parts = {p["categoryId"]: p["count"] for p in body["events"][0]["event"]["payload"]["participants"]}
        if seen is not None:
            seen.append({"query": parse_qs(u.query), "body": body, "headers": route.request.headers, "parts": parts})
        if status != 200:
            route.fulfill(status=status, headers=CORS, content_type="text/plain", body="denied")
            return
        route.fulfill(status=200, headers=CORS, content_type="application/json", body=json.dumps(answer or availability_answer(parts, body["events"][0]["event"]["payload"]["selectedDate"], **kw)))
    return run_script(recipe, api, html or activity_html(), url=recipe["url"]), recipe


def convert_activity(out, recipe, **extra):
    wishes = {"expect": {**recipe["expect"], **extra}}
    return convert_all([{"site": "getyourguide_activity", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)


def test_the_script_puts_every_traveller_in_the_category_of_their_age_and_asks_for_the_day_given():
    seen: list = []
    out, recipe = run_activity(seen=seen, adults=2, ages=(8, 3))
    s = seen[0]
    assert s["parts"] == {1: 2, 3: 2}                                      # 2 adults; the 8 and the 3 year old are both "Child (0-12)"
    assert s["body"]["payload"]["activityId"] == 603 and s["body"]["payload"]["contentIdentifier"] == "bookingAssistantConfiguratorContentIdentifier"
    assert s["body"]["payload"]["datesSelected"] == {"fromDate": "2027-03-05", "toDate": "2027-03-05"} and s["body"]["payload"]["fromPriceAtPageLoad"]["price"] == 70
    assert [e["event"]["type"] for e in s["body"]["events"]] == ["bookingAssistantInputsChanged", "participantsSelected"] and s["body"]["events"][0]["event"]["payload"]["selectedDate"] == "2027-03-05"
    assert s["headers"]["accept-currency"] == "EUR" and "cookie" not in s["headers"] and s["query"] == {"date_from": ["2027-03-05"], "date_to": ["2027-03-05"]}
    data = json.loads(__import__("myt_mcp.sites", fromlist=["expand"]).expand(out))
    assert data["day_read"] == "2027-03-05" and data["availability"] == "1 option available" and data["includes"].startswith("Walking tour; Guide; Food tastings")
    assert data["group_size"] == "Standard group: Up to 14 people" and "Vegan options" in data["know_before"] and data["not_suitable"] == "Wheelchair users"
    assert [c["count"] for c in data["categories"]] == [2, 2]


def test_the_offer_carries_the_exact_group_price_the_breakdown_the_start_times_and_the_terms():
    out, recipe = run_activity(adults=2, ages=(8,))
    offers, sources, problems, _, notes = convert_activity(out, recipe)
    assert problems == [] and len(offers) == 1
    o = offers[0]
    assert o.price_total == 175 and o.currency == "EUR" and "whole group (3 travellers; 2 Adult x 70 = 140; 1 Child x 35 = 35)" in o.price_basis and "all taxes and fees included" in o.price_basis
    assert o.name == "Food and Wine Walking Tour Shared (3 hours, Guide: English)" and o.flexible is True and o.supplier == "GetYourGuide"
    assert o.details["start_times"] == "3 start time(s): 10:30, 15:00, 16:30" and o.details["cancellation"] == "Cancel for free until Dec 16" and o.details["pay"] == "reserve now, pay later"
    assert o.details["meeting_point"] == "Praça Dom Pedro IV (Meet at Praça Dom Pedro IV 101, 1100-202 Lisboa, Portugal)" and o.details["private_or_group"].startswith("group (Standard group: Up to 14 people)")
    assert o.link == "https://www.getyourguide.com/lisbon-l42/lisbon-food-and-wine-walking-tour-t603/?date_from=2027-03-05&date_to=2027-03-05"
    assert any("exact price for this date and group" in n for n in notes)


def test_each_option_says_its_own_kind_and_flags_not_the_pages():
    out, recipe = run_activity(options=(1, 2), lines=["Private Lisbon Food Tour", "Duration: 3 hours", "Private", "Just your group, up to 15 people", "Skip the line", "Meeting point", "Rossio", "Select"])
    offers, *_ = convert_activity(out, recipe)
    assert offers[0].details["private_or_group"] == "private group (Just your group, up to 15 people)" and offers[0].details["flags"] == "Skip the line"
    out, recipe = run_activity(lines=["Shared tour", "Duration: 3 hours", "Standard group", "Up to 15 people", "Reserve now & pay later", "Select"])
    assert convert_activity(out, recipe)[0][0].details["private_or_group"] == "standard group (Up to 15 people)"


def test_two_adults_alone_cost_140_like_the_pages_own_total():
    out, recipe = run_activity(adults=2, ages=())
    offers, *_ = convert_activity(out, recipe)
    assert offers[0].price_total == 140


def test_a_price_that_depends_on_the_start_time_and_a_non_refundable_option_are_said():
    lines = ["Evening Food Tour", "Duration: 2 hours", "Non-refundable", "Only 4 spots left", "Meeting point", "Rossio", "Select"]
    out, recipe = run_activity(slot_prices={"3:00 PM": 190}, lines=lines)
    offers, _, _, _, notes = convert_activity(out, recipe)
    o = offers[0]
    assert o.price_total == 175 and "own price" in o.details["start_times"] and "15:00 (EUR 190)" in o.details["start_times"] and o.flexible is False and o.details["availability"] == "Only 4 spots left"
    assert any("depends on the start time" in n for n in notes)


def test_several_options_each_get_their_own_row():
    out, recipe = run_activity(options=(603, 604))
    offers, *_ = convert_activity(out, recipe)
    assert len(offers) == 2 and {o.price_total for o in offers} == {175}


def test_a_date_with_nothing_bookable_is_said_with_the_last_bookable_date():
    out, recipe = run_activity(available=False, unavailable=[{"tour_option_id": 603, "reason": "NOT_ENOUGH_PARTICIPANTS"}])
    offers, _, problems, _, notes = convert_activity(out, recipe)
    assert offers == [] and problems == [] and any("Not available for your selection" in n and "NOT_ENOUGH_PARTICIPANTS" in n and "2027-11-02" in n for n in notes)


def test_an_age_no_category_takes_is_said_in_the_sites_own_categories():
    cats = ({**ADULT, "minimumAge": 18, "title": "Adult"}, {**CHILD, "minimumAge": 6, "maximumAge": 17, "title": "Youth"})
    out, recipe = run_activity(adults=2, ages=(3,), html=activity_html(cats))
    offers, _, problems, _, _ = convert_activity(out, recipe)
    assert offers == [] and any("no traveller category that takes a 3-year-old" in p and "Adult (age 18-99), Youth (age 6-17)" in p for p in problems)


def test_a_traveller_group_the_script_cannot_choose_is_refused_not_guessed():
    out, recipe = run_activity(html=activity_html(({**ADULT, "participantType": "group", "title": "Group"},)))
    assert "priced by a category that is not a person (Group)" in json.loads(out)["error"]


def test_the_activity_refusals():
    out, recipe = run_activity()
    run = lambda **extra: convert_activity(out, recipe, **extra)[2]      # noqa: E731
    assert any("priced 3 traveller(s), not 4" in p for p in run(total=4))
    assert any("answered for 2027-03-05, not 2027-03-06" in p for p in run(day="2027-03-06"))
    assert any("activity 603, not 99" in p for p in run(id=99))
    from myt_mcp.sites.getyourguide_activity import convert
    row = {"n": 1, "option_id": 603, "title": "T", "lines": ["T"], "slots": [{"time": "10:30 AM", "price": 175, "cur": "USD"}], "total": 175, "cur": "USD", "breakdown": []}
    assert any("not EUR" in p for p in convert(json.dumps({"ok": True, "categories": [{"id": 1, "count": 1}], "rows": [row]}), {"expect": {"total": 1}}, "g").problems)
    unpriced = {**row, "cur": "EUR", "total": None, "lines": ["T", "At least 2 participants are required"]}
    res = convert(json.dumps({"ok": True, "categories": [{"id": 1, "count": 1}], "rows": [unpriced]}), {"expect": {"total": 1}}, "g")
    assert res.offers == [] and any("participants are required" in n for n in res.extra_notes)
    assert any("priced other traveller categories" in p for p in convert(json.dumps({"ok": True, "categories": [{"id": 1, "count": 2}], "categories_read": [{"id": 1, "count": 1}], "rows": [{**row, "cur": "EUR"}]}), {"expect": {"total": 2}}, "g").problems)
    with pytest.raises(ValueError):
        getyourguide_activity_recipe("https://www.getyourguide.com/s/?q=x", DAY, 2, [])
    with pytest.raises(ValueError):
        getyourguide_activity_recipe(ACT_URL, DAY, 0, [])
    with pytest.raises(ValueError):
        getyourguide_activity_recipe(ACT_URL, DAY, 2, [18])
    assert getyourguide_activity_recipe("https://www.getyourguide.com/-t603/", DAY, 2, [])["expect"]["id"] == 603


def test_the_activity_script_stops_on_the_wrong_page_a_check_page_a_page_without_categories_and_a_refused_call():
    recipe = getyourguide_activity_recipe(ACT_URL, DAY, 2, [8])
    quiet = lambda r, u: r.fulfill(status=200, headers=CORS, body="{}")      # noqa: E731
    assert "human check" in json.loads(run_script(recipe, quiet, "<html><body>Just a moment...</body></html>"))["error"]
    assert "not a GetYourGuide activity page" in json.loads(run_script(recipe, quiet, activity_html(), url="https://www.getyourguide.com/lisbon-l42/"))["error"]
    assert "no traveller categories" in json.loads(run_script(recipe, quiet, "<html><body><h1>x</h1><script>window.__INITIAL_STATE__ = {\"sdui\": {}};</script></body></html>"))["error"]
    out, _ = run_activity(status=403)
    assert "availability service could not be read (answered 403)" in json.loads(out)["error"]
    other = getyourguide_activity_recipe("https://www.getyourguide.com/lisbon-l42/other-t999/", DAY, 2, [8])
    assert "the page is the activity 603, not 999" in json.loads(run_script(other, quiet, activity_html(), url=ACT_URL))["error"]
    out, _ = run_activity(answer={"content": [], "trackingEvents": []})
    assert "no availability data" in json.loads(out)["error"]
