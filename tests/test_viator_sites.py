"""Viator recipes (the search list and the exact price of one activity): the REAL scripts run in a real browser (Playwright's Chromium) on viator.com pages that serve what the real site serves (read live 5 Nov 2026):
a search page whose data is embedded as JSON (<script id="globalState">, pageModel.preloadedData.search) with the products' own cards, and an activity page with its product data, its security token and its availability
service (POST /orion/ajax/product-availability, a 403 without the page's token). Nothing leaves the machine. The rows the scripts make go through the converters the server uses."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.viator_activity import viator_activity_recipe
from myt_mcp.sites.viator_find import duration_fit, fmt_minutes, language_code, rating_param, viator_find_recipe

# ---------------------------------------------------------------- the search page


def item(code, title, price, rating, reviews, dur, free=True, was=None, saved=None, badges=(), langs=("en",), dest=("Lisbon", "538"), unit="MINUTES", varies=False, ptype="TRAVELLER_BY_AGE_BAND", cur="EUR"):
    """One product of search.results as Viator embeds it (structure read live 5 Nov 2026)."""
    duration = {"__typename": "FixedDuration", "duration": dur, "unit": unit} if not isinstance(dur, tuple) else {"__typename": "FlexibleDuration", "from": dur[0], "to": dur[1], "unit": unit}
    return {"__typename": "SearchResult", "metaData": {}, "item": {
        "productCode": code, "title": {"text": title, "__typename": "Text"}, "canonicalName": title, "primaryDestination": {"id": dest[1], "name": dest[0], "canonicalName": dest[0]},
        "pricingInfo": {"__typename": "PricingInfo", "fromPrice": {"amount": price, "currency": cur}, "comparisonPrice": {"amount": was, "currency": cur} if was else None, "amountSaved": {"amount": saved, "currency": cur} if saved else None,
                        "pricingType": ptype, "priceVariesByGroupSize": varies, "adjustments": None},
        "productBadges": [{"__typename": "ProductBadgeWithInfo", "type": b, "isPrimary": False} for b in badges], "reviewSummary": {"averageRating": round(rating or 0), "exactRating": rating or 0, "count": reviews},
        "itinerary": {"__typename": "ProductSingleDayTourItinerary", "duration": duration}, "cancellationPolicy": {"__typename": "CancellationPolicy", "freeCancellation": free},
        "offeredLanguages": [{"__typename": "OfferedLanguage", "code": c} for c in langs]}}


SLUGS = {"5383GOURMET": "Lisbon-Small-Group-Gourmet-Portuguese-Food-and-Wine-Tour", "156455P1": "Eats-Street-Art-and-Undiscovered-Lisbon-Food-Tour", "170816P1": "Tastes-and-Traditions-of-Lisbon-Food-Tour"}
# real first products of "Lisbon food tour" (5 Nov 2026), exact prices; the last four are shaped like products the same search returned (a discount, a duration range, no reviews, a non-free one)
PAGE1 = [item("5383GOURMET", "Lisbon Small-Group Portuguese Food and Wine Tour", 66, 4.8, 4875, 180, varies=True, badges=("RECOMMENDED_BY_TRAVELLERS",)),
         item("156455P1", "Winner 2026 Undiscovered Lisbon Food & Wine Tour by Eating Europe", 104, 5, 9088, 210, varies=True),
         item("170816P1", "Devour Lisbon: The Ultimate Portuguese Food Tour", 63, 4.9, 2406, 180, varies=True, langs=("en", "es", "pt")),
         item("5560182P5", "Lisbon Tastings Walk", 71.1, 4.6, 120, 150, was=79, saved=7.9, badges=("SPECIAL_OFFER", "LIKELY_TO_SELL_OUT"), langs=("en", "he")),
         item("156435P15", "Lisbon Food and Wine Private Tour", 130, 5, 41, (180, 480), unit="MINUTES"),
         item("4747P1", "Lisbon Market Visit", 25, None, 0, 90, free=False),
         item("4748P2", "Lisbon Cheese Evening", 40, 4.2, 18, 120)]
PAGE2 = [item("9001P1", "Lisbon Food Cruise", 88, 4.4, 77, 240), item("9002P1", "Lisbon Private Food Day Trip", 310, 4.9, 12, (1, 2), unit="DAYS")]


def search_html(items, links=True, total=200, csrf=True):
    state = {"__TRANSLATION_CDN_URL__": "https://cache.vtrcdn.com/", "__PRELOADED_DATA__": {"csrf": {"headerName": "X-XSRF-TOKEN", "parameterName": "_csrf", "token": "tok-0123"} if csrf else {},
             "pageModel": {"preloadedData": {"search": {"results": items, "totalResults": total, "filters": {"languages": [{"key": k} for k in ("en", "zh", "nl", "fr", "de", "it", "ja", "pt", "ru", "es")],
                           "additionalFilters": [{"key": "ON_SALE", "available": True}, {"key": "FREE_CANCELLATION", "available": True}, {"key": "SKIP_THE_LINE", "available": False}]}}}}}}
    cards = "".join(f'<a href="/tours/Lisbon/{SLUGS.get(i["item"]["productCode"], "Tour-" + i["item"]["productCode"])}/d538-{i["item"]["productCode"]}?pid=P0&mcid=42">{i["item"]["title"]["text"]}</a>' for i in items) if links else ""
    return f'<html><head><title>Viator</title></head><body><h1>Showing results</h1>{cards}<script id="globalState" type="mime/invalid">{json.dumps(state)}</script></body></html>'


def run_find(page1=PAGE1, page2=PAGE2, pages=1, free=False, max_price=None, min_rating=None, max_hours=None, language=None, features=None, sort=None, query="Lisbon food tour", html=None, page2_status=200, seen=None, start_page=1):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = viator_find_recipe(query, "5 Mar 2027", start_page, None, free, max_price, min_rating, max_hours, language, features, sort, pages)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def serve(route):
        u = urlparse(route.request.url)
        if u.hostname != "www.viator.com":
            route.abort()
            return
        if seen is not None:
            seen.append({"path": u.path, "query": parse_qs(u.query)})
        if u.path.startswith("/searchResults/all/2"):
            route.fulfill(status=page2_status, content_type="text/html; charset=utf-8", body=search_html(page2, total=200) if page2_status == 200 else "<html>error</html>")
        elif u.path.startswith("/searchResults/all"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or search_html(page1))
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body="<html><body>x</body></html>")
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto(recipe["url"])
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def convert_find(out, recipe, **extra):
    wishes = {"expect": {**recipe["expect"], **extra}}
    return convert_all([{"site": "viator_find", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)


def test_the_filters_go_in_viators_own_address_with_the_values_the_site_accepts():
    r = viator_find_recipe("Lisbon food tour", None, 1, None, True, 60.0, 4.5, 4.0, "Hebrew", ["on_sale", "private_tour"], "rating", 2)
    q = parse_qs(urlparse(r["url"]).query)
    assert q == {"text": ["Lisbon food tour"], "duration": ["0-240"], "rating": ["4"], "price": ["0-61"], "feature": ["free_cancellation"], "sortType": ["average_review_rating_descending"]}
    assert "language" not in q and any("Hebrew" in n or "'he'" in n for n in r["filter_notes"])       # Viator has no Hebrew filter: judged from each product
    assert r["expect"]["language"] == "he" and r["expect"]["features"] == ["on_sale", "private_tour"] and r["expect"]["pages"] == 2
    one = parse_qs(urlparse(viator_find_recipe("Lisbon food tour", None, 3, None, False, None, None, None, "English", ["new_on_viator"], "newest")["url"]).query)
    assert one == {"text": ["Lisbon food tour"], "feature": ["new_on_viator"], "language": ["en"], "sortType": ["recency_descending"]}
    assert viator_find_recipe("Lisbon food tour", None, 3)["url"].startswith("https://www.viator.com/searchResults/all/3?text=")
    # the price limit is sent one euro higher (Viator's upper bound is exclusive: a product at exactly 25.00 vanished from price=0-25, read live 5 Nov 2026) and the server judges the exact price
    assert parse_qs(urlparse(viator_find_recipe("x tour", None, 1, None, False, 25.0)["url"]).query)["price"] == ["0-26"]
    assert parse_qs(urlparse(viator_find_recipe("x tour", None, 1, None, False, 24.5)["url"]).query)["price"] == ["0-26"]
    assert "duration" not in parse_qs(urlparse(viator_find_recipe("x tour", None, 1, None, False, None, None, 96.0)["url"]).query)       # 4 days: not a duration Viator's filter is for


def test_the_rating_sent_never_drops_a_product_that_meets_the_operators_minimum():
    # live 5 Nov 2026: rating=5 returned only exact 5.0 products ('4.5 & up' in the menu), so it is never sent; 4 and 3 hold everything at or above them
    assert [rating_param(v) for v in (None, 2.5, 3, 3.9, 4, 4.5, 4.8, 5)] == [None, None, 3, 3, 4, 4, 4, 4]
    assert viator_find_recipe("x tour", None, 1, None, False, None, 9.0)["expect"]["min_rating"] == 4.5      # 9 on Booking.com's ten points


def test_validation_and_helpers():
    with pytest.raises(ValueError):
        viator_find_recipe("x tour", None, 8, pages=3)
    with pytest.raises(ValueError):
        viator_find_recipe("x tour", None, 1, features=["flying"])
    with pytest.raises(ValueError):
        viator_find_recipe("x tour", None, 1, sort="price")
    with pytest.raises(ValueError):
        viator_find_recipe("x tour", None, 1, None, False, None, 0)
    assert language_code("Hebrew") == "he" and language_code("en") == "en" and language_code(None) is None
    assert fmt_minutes(180, 180) == "3 hours" and fmt_minutes(90, 210) == "1 hour 30 minutes to 3 hours 30 minutes" and fmt_minutes(1440, 2880) == "1 day to 2 days" and fmt_minutes(None, None) is None
    assert [duration_fit(lo, hi, 4) for lo, hi in ((60, 120), (180, 480), (300, 480), (None, None), (240, 240))] == [True, None, False, None, True]
    assert viator_find_recipe("Lisbon", "7 Mar 2027")["url"].endswith("/searchResults/all?text=Lisbon+tours")       # a one-word query would land on the destination page


def test_the_real_script_reads_the_pages_own_json_and_makes_the_rows_the_converter_expects():
    seen: list = []
    out, recipe = run_find(seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["query_text"] == "Lisbon food tour" and data["results_total"] == 200 and data["page"] == 1 and data["pages_read"] == 1 and data["shown_range"] == "1-7" and data["sort"] == "featured" and data["url_filters"] == {}
    assert data["lang_keys"][:3] == ["en", "zh", "nl"] and data["features_available"] == ["ON_SALE", "FREE_CANCELLATION"] and data["failed_pages"] is None
    rows = {r["code"]: r for r in data["rows"]}
    assert len(rows) == 7 and [r["rank"] for r in data["rows"]] == list(range(1, 8))
    first = rows["5383GOURMET"]
    assert (first["title"], first["price"], first["cur"], first["rating"], first["reviews"], first["mins_from"], first["mins_to"], first["free_cancel"], first["varies"]) == ("Lisbon Small-Group Portuguese Food and Wine Tour", 66, "EUR", 4.8, 4875, 180, 180, True, True)
    assert first["path"] == "/tours/Lisbon/Lisbon-Small-Group-Gourmet-Portuguese-Food-and-Wine-Tour/d538-5383GOURMET" and first["badges"] == ["RECOMMENDED_BY_TRAVELLERS"]      # the card's own link, without its tracking query
    assert rows["5560182P5"]["was"] == 79 and rows["5560182P5"]["saved"] == 7.9 and rows["5560182P5"]["price"] == 71.1 and rows["5560182P5"]["langs"] == ["en", "he"]
    assert (rows["156435P15"]["mins_from"], rows["156435P15"]["mins_to"]) == (180, 480) and rows["4747P1"]["rating"] is None and rows["4747P1"]["free_cancel"] is False
    assert len([s for s in seen if s["path"].startswith("/searchResults")]) == 1      # one page asked: no request of the script's own
    offers, sources, problems, _, notes = convert_find(out, recipe)
    assert not problems and (sources[0].read, sources[0].of) == (7, 200) and not any(o.quotable for o in offers)
    assert offers[0].price_total == 66 and offers[0].link == "https://www.viator.com/tours/Lisbon/Lisbon-Small-Group-Gourmet-Portuguese-Food-and-Wine-Tour/d538-5383GOURMET" and "varies by group size" in offers[0].price_basis
    assert offers[3].price_total == 71.1 and "discounted from 79 EUR" in offers[3].price_basis and offers[3].details["duration"] == "2 hours 30 minutes" and offers[3].details["badges"] == "special offer, likely to sell out"
    assert offers[4].details["duration"] == "3 hours to 8 hours" and offers[5].details["rating"] == "not rated yet" and offers[5].details["cancellation"] == "not free (Viator's own flag)"
    assert any("at most 200 results" in n for n in notes)


def test_two_pages_are_read_in_one_run_with_a_pause_and_a_failing_second_page_is_said():
    seen: list = []
    out, recipe = run_find(pages=2, seen=seen)
    data = json.loads(out)
    assert data["pages_read"] == 1 and len(data["rows"]) == 7       # page 1 held 7, not 24: Viator's last page: nothing more is asked
    full = [item(f"X{i}", f"Lisbon Food Walk {i}", 20 + i, 4.5, 10, 120) for i in range(24)]
    out, recipe = run_find(page1=full, pages=2, seen=seen)
    data = json.loads(out)
    assert data["pages_read"] == 2 and len(data["rows"]) == 24 + len(PAGE2) and data["shown_range"] == "1-26" and [r["rank"] for r in data["rows"]][24:] == [25, 26] and data["rows"][25]["mins_from"] == 1440 and data["rows"][25]["mins_to"] == 2880
    assert [s["path"] for s in seen if s["path"].startswith("/searchResults")][-2:] == ["/searchResults/all", "/searchResults/all/2"]
    out, recipe = run_find(page1=full, pages=2, page2_status=500)
    data = json.loads(out)
    assert data["ok"] is True and data["pages_read"] == 1 and len(data["rows"]) == 24 and data["failed_pages"] and "page 2" in data["failed_pages"][0]
    notes = convert_find(out, recipe)[4]
    assert any("Not every page asked for was read" in n for n in notes)


def test_every_wish_is_judged_by_the_server_from_the_rows_not_only_by_viators_filters():
    out, recipe = run_find(free=True, max_price=75, min_rating=4.5, max_hours=4, features=["on_sale"])
    offers, _, problems, _, _ = convert_find(out, recipe)
    assert not problems
    # Viator was asked for one feature only; the server holds each row to ALL the wishes: only the discounted walk meets price, rating, duration, free cancellation AND the deal
    assert [o.name for o in offers if o.fits] == ["Lisbon Tastings Walk"]
    assert next(o for o in offers if o.name.startswith("Winner 2026")).fits is False       # 104 > 75, and it is not on sale


def test_wishes_one_by_one_on_the_same_rows():
    def fits(**kw):
        out, recipe = run_find(**kw)
        return {o.name: o.fits for o in convert_find(out, recipe)[0]}, convert_find(out, recipe)[0]
    f, _ = fits(max_price=70)
    assert f["Lisbon Small-Group Portuguese Food and Wine Tour"] is True and f["Lisbon Tastings Walk"] is False and f["Lisbon Market Visit"] is True
    f, _ = fits(min_rating=4.5)
    assert f["Lisbon Small-Group Portuguese Food and Wine Tour"] is True and f["Lisbon Cheese Evening"] is False and f["Lisbon Market Visit"] is None       # no reviews: not known, never 'meets'
    f, offers = fits(max_hours=4)
    by = {o.name: o for o in offers}
    assert f["Lisbon Small-Group Portuguese Food and Wine Tour"] is True and f["Winner 2026 Undiscovered Lisbon Food & Wine Tour by Eating Europe"] is True and f["Lisbon Food and Wine Private Tour"] is None
    assert by["Lisbon Food and Wine Private Tour"].unconfirmed == ["duration"]       # 3 h to 8 h: depends on the option chosen
    f, _ = fits(free=True)
    assert f["Lisbon Market Visit"] is False and f["Lisbon Cheese Evening"] is True
    f, _ = fits(language="Hebrew")
    assert f["Lisbon Tastings Walk"] is True and f["Lisbon Small-Group Portuguese Food and Wine Tour"] is False       # Viator has no Hebrew filter: each product's own languages decide
    f, _ = fits(language="es")
    assert f["Devour Lisbon: The Ultimate Portuguese Food Tour"] is True and f["Lisbon Tastings Walk"] is False
    f, _ = fits(features=["on_sale"])
    assert f["Lisbon Tastings Walk"] is True and f["Lisbon Small-Group Portuguese Food and Wine Tour"] is False
    f, _ = fits(features=["likely_to_sell_out"])
    assert f["Lisbon Tastings Walk"] is True and f["Lisbon Cheese Evening"] is False
    f, offers = fits(features=["private_tour"])
    by = {o.name: o for o in offers}
    assert f["Lisbon Food and Wine Private Tour"] is True and f["Lisbon Cheese Evening"] is None and by["Lisbon Cheese Evening"].unconfirmed == ["private tour"]       # the list has no field for it: the title is the only sign


def test_the_converter_refuses_what_does_not_match_the_page_asked():
    out, recipe = run_find()
    exp = recipe["expect"]

    def problems(text, e=exp):
        return convert_all([{"site": "viator_find", "result": text, "url": "u"}], {"expect": e})[2]
    data = json.loads(out)
    assert not problems(out)
    assert any("searched 'Rome food'" in p for p in problems(json.dumps({**data, "query_text": "Rome food"})))
    assert any("result page 1, not 2" in p for p in problems(out, {**exp, "page": 2}))
    assert any("not EUR" in p for p in problems(json.dumps({**data, "rows": [{**data["rows"][0], "cur": "ILS"}]})))
    assert any("script reported" in p for p in problems(json.dumps({"ok": False, "error": "x"})))
    filtered, recipe2 = run_find(max_price=70)
    assert not problems(filtered, recipe2["expect"])
    assert any("carries the filters" in p for p in problems(json.dumps({**json.loads(filtered), "url_filters": {}}), recipe2["expect"]))       # the page was opened without the filters
    assert any("carries the filters" in p for p in problems(json.dumps({**json.loads(filtered), "url_filters": {"price": "0-99"}}), recipe2["expect"]))


def test_the_script_stops_on_a_check_page_and_on_a_page_without_data():
    check = json.loads(run_find(html="<html><body>Performing security verification</body></html>")[0])
    assert check["ok"] is False and "human check" in check["error"] and "do not work around" in check["error"]
    bare = json.loads(run_find(html="<html><body><h1>Lisbon</h1></body></html>")[0])
    assert bare["ok"] is False and "no search data" in bare["error"]


# ---------------------------------------------------------------- the activity page

CODE = "156455P1"
PATH = "/tours/Lisbon/Eats-Street-Art-and-Undiscovered-Lisbon-Food-Tour/d538-156455P1"
URL = "https://www.viator.com" + PATH
BANDS = [{"ageBand": "ADULT", "ageMin": 18, "ageMax": 99, "passengerMin": 1, "passengerMax": 12}, {"ageBand": "YOUTH", "ageMin": 13, "ageMax": 17, "passengerMin": 0, "passengerMax": 12},
         {"ageBand": "CHILD", "ageMin": 4, "ageMax": 12, "passengerMin": 0, "passengerMax": 12}]


def money(v, cur="EUR"):
    return {"currencyCode": cur, "currencySymbol": "€", "amount": v}


def price(now, was=None, cur="EUR"):
    return {"retailPrice": money(was if was else now, cur), "discountedPrice": money(now, cur), "discountAmount": money((was or now) - now, cur), "isDiscounted": bool(was and was > now)}


def grade(title, code, total, bands, times, spots=12, pay="2026-12-15T08:00:00", cur="EUR", available=True, desc="Duration: 3 hours 30 minutes", reserve=True, extra=0):
    """One tourGrade as the availability service returns it (read live 5 Nov 2026)."""
    return {"tourGradeCode": code, "availability": "AVAILABLE" if available else "SOLD_OUT", "date": "2026-12-17", "description": f"<b>{desc}</b>", "languages": ["English"], "languageCodes": ["en"], "price": price(total, cur=cur), "currency": cur,
            "totalRetailPricePlusExtraCharges": money(extra), "productCode": CODE, "title": title,
            "startTimes": [{"tourGradeCode": code, "startTime": t, "startTime24H": t24, "price": price(total, cur=cur), "availabilityResult": "AVAILABLE", "spotsLeft": spots} for t, t24 in times],
            "priceBreakdown": [{"ageBand": b, "numberOfTravelers": n, "price": price(unit, cur=cur)} for b, n, unit in bands], "earliestPaymentDate": pay, "spotsLeft": spots, "languageServices": [{"hasAudioGuide": False, "hasHumanGuide": True, "hasWrittenGuide": False, "locale": "en"}], "isReserveEligible": reserve, "isAvailable": available}


SMALL = ("Small-group Food Tour (12 pax)", "TG11~11:00", 291, [("ADULT", 2, 104), ("CHILD", 1, 83)], [("11:00 AM", "11:00"), ("12:00 PM", "12:00"), ("2:00 PM", "14:00"), ("6:00 PM", "18:00"), ("8:00 PM", "20:00")])
PRIVATE = ("Upgrade to a Private Food Tour", "TG2~13:00", 439, [("ADULT", 2, 159.5), ("CHILD", 1, 120)], [("1:00 PM", "13:00"), ("6:00 PM", "18:00")])


def availability(grades, errors=None, policy=None):
    return {"validationErrors": errors or {}, "productAvailability": {"tourGrades": grades, "tourGradesDisplayLimit": "4", "hasCustomCancellationPolicy": False, "selectedLanguageCodes": []}, "alternativeProducts": [],
            "cancellationPolicyDetails": policy or {"policyType": "REFUNDABLE", "refundEligibleUntilDate": "2026-12-16", "isRefundDeadlineInPast": False}}


def product(code=CODE, bands=BANDS, pricing=None, duration=None, private=False, max_travellers=12):
    return {"pricing": pricing, "isPrivateTour": private, "productCode": code, "title": "Winner 2026 Undiscovered Lisbon Food & Wine Tour by Eating Europe", "supplierName": "Eating Europe Food Tours ", "timeZone": "Europe/Lisbon", "hasFreeCancellation": True, "duration": duration or {"days": 0, "hours": 3, "minutes": 30},
            "availabilityConfig": {"ageBandRanges": bands, "maxTravellersPerBooking": max_travellers}, "productLanguages": {"primaryLanguage": {"code": "en", "displayName": "English"}, "offeredLanguages": [{"code": "en", "displayName": "English"}]},
            "productAttributes": [{"label": "3 hours 30 minutes (approx.)", "type": "DURATION"}, {"label": "Mobile ticket", "type": "MOBILE_PHONE_TICKET"}],
            "departureAndReturnLocations": {"departureLocations": [{"description": "Praça dos Restauradores, 1250-001 Lisboa, Portugal", "instructions": "Your guide will wait by the monument wearing a purple bag!", "type": "START"}],
                                            "returnLocations": [{"description": "R. do Milagre de Santo António 10, 1100-351 Lisboa, Portugal", "instructions": "Subject to change.", "type": "END"}]},
            "description": {"inclusions": {"features": ["7 to 9 food tastings and 3-5 local drinks", "VIP access to a traditional Fado House"]}, "exclusions": {"features": ["Extra drinks", "Hotel pick-up and drop-off"]},
                            "additionalInfo": {"features": ["Confirmation will be received at time of booking", "Not wheelchair accessible"]},
                            "cancellationPolicy": {"cancellationPolicyLabel": "Free cancellation", "cancellationPolicyDescription": "up to 24 hours in advance", "policies": ["You can cancel up to 24 hours in advance of the experience for a full refund."]}}}


def activity_html(prod=None, csrf=True, path=PATH):
    state = {"__PRELOADED_DATA__": {"csrf": {"headerName": "X-XSRF-TOKEN", "parameterName": "_csrf", "token": "tok-9876"} if csrf else {}, "pageModel": {"product": prod or product()}}}
    return f'<html><head><title>Lisbon Small-Group Food and Culture Tour 2026 - BOOK NOW</title></head><body><h1>Food tour</h1><script id="globalState" type="mime/invalid">{json.dumps(state)}</script></body></html>'


CALENDAR = {"dates": {"2026-12-18": {"formattedPrice": "€104.00", "isDiscounted": False}, "2026-12-19": {"formattedPrice": "€104.00", "isDiscounted": False}, "2026-12-21": {"formattedPrice": "€110.00", "isDiscounted": False}, "2026-11-12": {"formattedPrice": "€104.00", "isDiscounted": False}}, "currencyCode": "EUR"}


def run_activity(grades=None, day=date(2026, 12, 17), adults=2, ages=(8,), errors=None, policy=None, seen=None, html=None, prod=None, csrf=True, url=URL, calendar=CALENDAR, status=200, bands=BANDS):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = viator_activity_recipe(url, day, adults, list(ages), "Food tour")
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"
    answer = availability([grade(*SMALL), grade(*PRIVATE)] if grades is None else grades, errors, policy)

    def serve(route):
        u = urlparse(route.request.url)
        if u.hostname != "www.viator.com":
            route.abort()
        elif u.path == "/orion/ajax/product-availability":
            ok = route.request.headers.get("x-xsrf-token") == "tok-9876"
            if seen is not None:
                seen.append({"path": u.path, "token_ok": ok, "body": json.loads(route.request.post_data or "{}")})
            route.fulfill(status=(status if ok else 403), content_type="application/json" if ok else "text/html", body=json.dumps(answer) if ok else "<html>403</html>")
        elif u.path.startswith("/orion/ajax/react/product-price-calendar/"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(calendar))
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or activity_html(prod or product(bands=bands), csrf=csrf))
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto(recipe["url"])
            out = page.evaluate(script)
            browser.close()
    except Exception as e:
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def convert_activity(out, recipe, **extra):
    wishes = {"expect": {**recipe["expect"], **extra}}
    return convert_all([{"site": "viator_activity", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)


def test_the_script_asks_viators_own_availability_service_with_the_pages_token_and_the_age_band_of_each_traveller():
    seen: list = []
    out, recipe = run_activity(seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["code"] == CODE and data["day"] == "2026-12-17" and data["bands_sent"] == {"ADULT": 2, "CHILD": 1} and data["travellers_sent"] == 3 and data["options_found"] == 2 and data["errors"] is None
    ask = next(s for s in seen if s["path"] == "/orion/ajax/product-availability")
    assert ask["token_ok"] and ask["body"] == {"productCode": CODE, "searchDate": "2026-12-17", "ageBands": {"ADULT": "2", "CHILD": "1"}, "source": "commerce_module"}       # the child aged 8 is in the CHILD band (4-12)
    small, private = data["rows"]
    assert (small["option"], small["total"], small["list_total"], small["cur"], small["spots"], small["available"], small["pay_by"], small["reserve"]) == ("Small-group Food Tour (12 pax)", 291, 291, "EUR", 12, True, "2026-12-15T08:00:00", True)
    assert small["breakdown"] == [{"band": "ADULT", "n": 2, "unit": 104, "list": 104}, {"band": "CHILD", "n": 1, "unit": 83, "list": 83}] and [t["t"] for t in small["times"]] == ["11:00", "12:00", "14:00", "18:00", "20:00"]
    assert private["total"] == 439 and private["breakdown"][0]["unit"] == 159.5 and small["langs"] == ["English"] and small["guide"] == ["live guide"] and small["times"][0]["spots"] == 12
    assert data["duration"] == "3 hours 30 minutes" and data["offered_in"] == "English" and data["mobile_ticket"] is True and data["supplier"] == "Eating Europe Food Tours" and data["policy_type"] == "REFUNDABLE" and data["refund_until"] == "2026-12-16"
    assert data["included"].startswith("7 to 9 food tastings") and data["excluded"] == "Extra drinks; Hotel pick-up and drop-off" and "Not wheelchair accessible" in data["additional"] and data["max_travellers"] == 12
    assert data["meeting_text"].startswith("Start: Praça dos Restauradores") and "End: R. do Milagre" in data["meeting_text"] and data["cancel_policy"].startswith("You can cancel up to 24 hours")
    assert data["day_bookable"] is False and data["next_dates"][0] == "2026-12-18 €104.00" and len(data["next_dates"]) == 3      # the calendar does not list the 17th; the next bookable dates follow


def test_the_activity_offers_carry_the_exact_group_price_the_breakdown_and_the_terms():
    out, recipe = run_activity()
    offers, sources, problems, _, notes = convert_activity(out, recipe)
    assert not problems and len(offers) == 2 and (sources[0].read, sources[0].of) == (2, 2) and all(o.quotable for o in offers) and [o.price_total for o in offers] == [291.0, 439.0]
    small, private = offers
    assert small.name.startswith("Winner 2026 Undiscovered Lisbon Food & Wine Tour by Eating Europe - Small-group Food Tour (12 pax) (3 hours 30 minutes)") and small.group == "Food tour, 17 Dec 2026" and small.currency == "EUR"
    assert "whole group (3 travellers; 2 Adults x 104.00 EUR; 1 Child x 83.00 EUR)" in small.price_basis and "2 Adults x 159.50 EUR; 1 Child x 120.00 EUR" in private.price_basis
    d = small.details
    assert d["start_times"] == "5 start time(s): 11:00, 12:00, 14:00, 18:00, 20:00" and d["seats_left"] == "12" and d["pay"] == "Reserve now, pay later possible until 2026-12-15" and d["ticket"] == "mobile ticket"
    assert small.flexible is True and d["cancellation"].startswith("Free cancellation until 2026-12-16 (Viator's policy for this date: You can cancel up to 24 hours in advance") and "before the start time chosen on that day', so for 11:00 before 11:00 on 2026-12-16" in d["cancellation"]
    assert d["meeting_point"].startswith("Start: Praça dos Restauradores") and d["includes"].startswith("7 to 9 food tastings") and d["excludes"] == "Extra drinks; Hotel pick-up and drop-off" and d["language"] == "offered in: English; this option: English (live guide)"
    assert small.link == URL and private.link == URL and private.details["private_or_group"] == "private" and any("several options" in n for n in notes)


def test_a_discount_a_start_time_price_difference_and_a_non_refundable_date_are_said():
    g = grade(*SMALL)
    g["price"] = price(291, was=320)
    g["startTimes"][4]["price"] = price(331)
    out, recipe = run_activity(grades=[g], policy={"policyType": "NON_REFUNDABLE", "refundEligibleUntilDate": None, "isRefundDeadlineInPast": False})
    offers = convert_activity(out, recipe)[0]
    assert len(offers) == 1 and "discounted from 320 EUR" in offers[0].price_basis and "the price differs by start time" in offers[0].details["start_times"] and "20:00 331" in offers[0].details["start_times"]
    assert offers[0].flexible is False and offers[0].details["cancellation"].startswith("Non-refundable")
    past = run_activity(policy={"policyType": "REFUNDABLE", "refundEligibleUntilDate": "2026-12-16", "isRefundDeadlineInPast": True})
    o = convert_activity(*past)[0][0]
    assert o.flexible is not True and o.details["cancellation"].startswith("Free cancellation is no longer possible for this date")


def test_a_date_with_nothing_bookable_and_an_option_that_is_sold_out_are_said():
    out, recipe = run_activity(grades=[], day=date(2026, 12, 17))
    offers, sources, problems, _, _ = convert_activity(out, recipe)
    assert offers == [] and any("no option to book on 2026-12-17" in p and "2026-12-18 €104.00" in p and "does not list this date" in p for p in problems)
    out, recipe = run_activity(grades=[grade(*SMALL), grade(*PRIVATE, available=False)])
    offers, _, problems, _, notes = convert_activity(out, recipe)
    assert not problems and len(offers) == 1 and any("1 option(s) of this activity cannot be booked" in n for n in notes)


def test_the_activity_refusals_and_viators_own_validation_errors():
    out, recipe = run_activity(errors={"OVER_MAX_TRAVELERS": "", "OUT_OF_AGE_RANGE": ""}, grades=[], adults=13, ages=())
    problems = convert_activity(out, recipe)[2]
    assert any("larger than Viator allows" in p and "at most 12 travellers" in p for p in problems) and any("age is outside" in p and "ADULT 18-99" in p for p in problems)
    normal, normal_recipe = run_activity()
    data = json.loads(normal)
    exp = normal_recipe["expect"]

    def problems_of(d, e=exp):
        return convert_all([{"site": "viator_activity", "result": json.dumps(d), "url": "u"}], {"expect": e})[2]
    assert not problems_of(data)
    assert any("not the activity asked" in p for p in problems_of({**data, "url_path": "/tours/Rome/other/d1-X"}))
    assert any("is for 2026-12-18" in p or "answer is for 2026-12-18" in p for p in problems_of({**data, "day": "2026-12-18"}))
    assert any("2 traveller" in p for p in problems_of({**data, "travellers_sent": 2}))
    assert any("not EUR" in p for p in problems_of({**data, "rows": [{**data["rows"][0], "cur": "ILS"}]}))
    assert any("script reported" in p for p in problems_of({"ok": False, "error": "x"}))
    assert any("1 traveller" in p or "2 traveller" in p for p in problems_of({**data, "rows": [{**data["rows"][0], "breakdown": [{"band": "ADULT", "n": 2, "unit": 104, "list": 104}]}]}))


def test_the_script_stops_on_the_wrong_page_a_missing_token_an_age_no_band_takes_and_a_refused_request():
    assert json.loads(run_activity(url=URL.replace("156455P1", "999P9"), html=activity_html())[0])["ok"] is False       # the page's own product is another one
    wrong = json.loads(run_activity(prod=product(code="777P7"))[0])
    assert wrong["ok"] is False and "777P7" in wrong["error"] and "open the url again" in wrong["error"]
    no_token = json.loads(run_activity(csrf=False)[0])
    assert no_token["ok"] is False and "security token" in no_token["error"]
    baby = json.loads(run_activity(ages=(2,))[0])
    assert baby["ok"] is False and "aged 2" in baby["error"] and "CHILD 4-12" in baby["error"]
    refused = json.loads(run_activity(status=500)[0])
    assert refused["ok"] is False and "could not be read" in refused["error"] and "500" in refused["error"]
    check = json.loads(run_activity(html="<html><body>Performing security verification</body></html>")[0])
    assert check["ok"] is False and "human check" in check["error"]
    youth = json.loads(run_activity(ages=(15,), adults=1)[0])
    assert youth["ok"] is True and youth["bands_sent"] == {"ADULT": 1, "YOUTH": 1}


@pytest.mark.anyio
async def test_the_tools_return_the_url_with_the_filters_and_the_wishes():
    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings
    async with Client(create_server(Settings())) as c:
        r = (await c.call_tool("viator_find_recipe", {"query": "Lisbon food tour", "free_cancellation": True, "max_price": 80, "max_hours": 4, "min_rating": 4.5, "language": "Hebrew", "features": ["on_sale"], "sort": "rating", "pages": 2})).structured_content
        q = parse_qs(urlparse(r["url"]).query)
        assert q["price"] == ["0-81"] and q["duration"] == ["0-240"] and q["rating"] == ["4"] and q["feature"] == ["free_cancellation"] and q["sortType"] == ["average_review_rating_descending"] and "language" not in q
        assert r["wishes"]["expect"]["language"] == "he" and r["wishes"]["expect"]["features"] == ["on_sale"] and "page=3" in r["more"]
        assert any("Rating at least 4.5" in f for f in r["filters_used"]) and any("Language he" in f for f in r["filters_used"]) and any("Applied by Viator itself" in f and "price filter" in f for f in r["filters_used"])
        a = (await c.call_tool("viator_activity_recipe", {"url": URL + "?x=1", "day": "2026-12-17", "adults": 2, "children_ages": [8], "free_cancellation": True})).structured_content
        assert a["url"] == URL and a["wishes"]["expect"]["total"] == 3 and a["wishes"]["free_cancellation"] is True and "not touched" in " ".join(a["steps"])


# the live product 57617P3 (5 Nov 2026): "12 Day Private Food and Wine Tour in Portugal and Spain", one age group (Adult 0-120, 1-7 travellers), 12 days, a flat price for the group (hasUnitPricing), 11 EUR of extra charges per
# traveller; for 3 travellers on 10 Dec the availability service says 7,500 (the booking box shows 7,500.00) and 7,533 with the extra charges; its breakdown is '2 Adult at 0' + '1 Adult at 7500'
PATH12 = "/tours/Lisbon/Private-Tour-Portugal-and-Spain-Food-and-Wine-Tour-12-days/d538-57617P3"
BANDS12 = [{"ageBand": "ADULT", "ageMin": 0, "ageMax": 120, "passengerMin": 1, "passengerMax": 7}]
PRICING12 = {"price": {"retailPrice": money(7500), "extraChargeAmount": money(11), "hasTieredPricing": False, "hasUnitPricing": True, "isDiscounted": False}, "maxTravelersPerUnit": 7}
FLAT = ("12 Day Private Food and Wine Tour in Portugal and Spain", "TG1~09:00", 7500, [("ADULT", 2, 0), ("ADULT", 1, 7500)], [("9:00 AM", "09:00")])


def run_flat(adults=2, ages=(8,), extra=7533):
    g = grade(*FLAT, spots=None, pay=None, reserve=False, extra=extra, desc="Pickup included")
    n = adults + len(ages)
    g["date"] = "2026-12-10"
    g["priceBreakdown"] = [{"ageBand": "ADULT", "numberOfTravelers": n - 1, "price": price(0)}, {"ageBand": "ADULT", "numberOfTravelers": 1, "price": price(7500)}]       # the whole price sits on one line, the others show 0 (read live)
    g["languages"] = ["Portuguese", "English", "Spanish"]
    pol = {"policyType": "REFUNDABLE", "refundEligibleUntilDate": "2026-12-07", "isRefundDeadlineInPast": False}
    prod = product(code="57617P3", bands=BANDS12, pricing=PRICING12, duration={"days": 12, "hours": 0, "minutes": 0}, private=True, max_travellers=7)
    prod["title"] = "12 Day Private Food and Wine Tour in Portugal and Spain"
    return run_activity(grades=[g], day=date(2026, 12, 10), adults=adults, ages=ages, policy=pol, prod=prod, url="https://www.viator.com" + PATH12)


def test_a_private_multi_day_activity_priced_per_group_is_said_to_be_a_flat_price_and_its_extra_charges_are_named():
    seen: list = []
    out, recipe = run_flat()
    data = json.loads(out)
    assert data["ok"] is True and data["bands_sent"] == {"ADULT": 3} and data["unit_pricing"] is True and data["max_per_unit"] == 7 and data["extra_per_traveller"] == 11 and data["private_tour"] is True and data["duration"] == "12 days"       # the child of 8 is in the one Adult 0-120 group
    offers, _, problems, _, notes = convert_activity(out, recipe)
    assert not problems and len(offers) == 1 and offers[0].price_total == 7500.0
    o = offers[0]
    assert "a flat price for the whole group of up to 7, not per person" in o.price_basis and "x 0.00" not in o.price_basis and "Adult x" not in o.price_basis
    assert "Viator lists 33 EUR of extra charges on top (its own total with them is 7533 EUR)" in o.price_basis and "confirm before quoting" in o.price_basis and o.details["extra_charges"] == "33 EUR on top of the price (11 EUR per traveller)"
    assert o.details["cancellation"].startswith("Free cancellation until 2026-12-07") and "so for 09:00 before 09:00 on 2026-12-07" in o.details["cancellation"] and o.details["pay"] == "Reserve now, pay later is not offered for this option" and o.details["start_times"] == "1 start time(s): 09:00"
    assert "(12 days)" in o.name and o.details["private_or_group"] == "private" and o.details["language"].endswith("this option: Portuguese, English, Spanish (live guide)")
    none = convert_activity(*run_flat(extra=0))[0][0]
    assert "Viator lists no extra charges" in none.price_basis and none.details["extra_charges"] == "none listed"


def test_a_group_larger_than_one_unit_is_said():
    out, recipe = run_flat(adults=8, ages=())
    problems = convert_activity(out, recipe)[2]
    assert any("priced per group of at most 7 travellers" in p and "8 travellers need more than one group" in p for p in problems)


def test_the_search_list_says_a_unit_priced_product_is_a_flat_group_price():
    page = [item("57617P3", "12 Day Private Food and Wine Tour in Portugal and Spain", 7500, None, 0, (17280, 17280), ptype="UNIT", dest=("Lisbon", "538")), item("1P1", "Lisbon Food Walk", 40, 4.5, 10, 120)]
    out, recipe = run_find(page1=page)
    offers = convert_find(out, recipe)[0]
    assert "for the whole group (Viator prices this activity per group, a flat price, not per person)" in offers[0].price_basis and offers[0].details["duration"] == "12 days" and "per person" in offers[1].price_basis


def test_an_age_group_the_activity_does_not_have_is_said_in_viators_own_words():
    """Read live 5 Nov 2026 on '3 Days Private Tour In Lisbon' (one group, Adult 0-99): asking for a CHILD gives UNSUPPORTED_AGE_BAND and no options."""
    out, recipe = run_activity(grades=[], errors={"UNSUPPORTED_AGE_BAND": "Child"}, bands=[{"ageBand": "ADULT", "ageMin": 0, "ageMax": 99, "passengerMin": 1, "passengerMax": 8}])
    problems = convert_activity(out, recipe)[2]
    assert any("no age group of that kind" in p and "ADULT 0-99" in p for p in problems)
    ok = json.loads(out)
    assert ok["bands_sent"] == {"ADULT": 3}       # the child of 8 is sent in the one group that holds that age, so Viator is not asked for a CHILD at all


def test_a_senior_age_is_accepted_and_goes_in_the_age_group_that_holds_it():
    senior_bands = [{"ageBand": "ADULT", "ageMin": 18, "ageMax": 64, "passengerMin": 1, "passengerMax": 12}, {"ageBand": "SENIOR", "ageMin": 65, "ageMax": 99, "passengerMin": 0, "passengerMax": 12}]
    out, recipe = run_activity(adults=1, ages=(70,), bands=senior_bands)
    assert json.loads(out)["bands_sent"] == {"ADULT": 1, "SENIOR": 1}
    with pytest.raises(ValueError, match="ages 0-99"):
        viator_activity_recipe(URL, date(2026, 12, 17), 2, [120])
