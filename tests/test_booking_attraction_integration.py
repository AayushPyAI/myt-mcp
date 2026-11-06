"""Booking.com attractions, ONE activity, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page that serves what the real site serves (read live 5 Nov 2026): the product embedded as an Apollo
store (getProduct: id, name, operatedBy, whatsIncluded, addresses, offers), the page's tokens in its inline data, and POST accommodations.booking.com/dml/graphql, operation GetAvailability, answering the time slots of the
date with each ticket offer's kinds of ticket and their prices (Adult 29.90, Child 17.70, Senior 19.90, Infant 0). Nothing leaves the machine."""

from __future__ import annotations

import json
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.booking_attraction import booking_attraction_recipe
from tests.test_booking_attraction import SLUG, URL

PID = "PR4z1zRjQ9hl"


def kind(ident, ty, label, price, lo=None, hi=None, adult_like=False, left=10000, max_per=15, min_per=0, cancel=None):
    return {"__typename": "AttractionsOfferItem", "id": ident, "offerItemId": ident, "type": ty, "label": label, "isAdultLike": adult_like, "unitsRequired": 1, "minPerReservation": min_per, "maxPerReservation": max_per, "ticketsAvailable": left,
            "constraint": {"label": f"(age {lo}-{hi})" if hi else f"(age {lo}+)", "minAge": lo, "maxAge": hi, "type": "age"}, "price": {"chargeAmount": price, "currency": "EUR", "publicAmount": price, "discounts": []},
            "cancellationPolicy": cancel or {"comparedTo": None, "hasFreeCancellation": False, "isStillRefundable": False, "label": "Non-refundable", "message": None, "percentage": None, "period": None, "until": None}}


def kinds(adult=29.9, child=17.7, left=10000, only_adult=False, cancel=None):
    out = [kind("K-sen", "senior", "Senior", 19.9, 65, None, left=left, cancel=cancel), kind("K-adu", "adult", "Adult", adult, 13, 64, True, left=left, cancel=cancel), kind("K-inf", "infant", "Infant", 0, 0, 2, left=left, cancel=cancel), kind("K-chi", "children", "Child", child, 3, 12, left=left, cancel=cancel)]
    return [k for k in out if k["type"] == "adult"] if only_adult else out


def with_ids(offers, i):
    """The real service gives every time slot its own ticket ids (read live 5 Nov 2026): the same kinds, other ids."""
    out = []
    for o in offers:
        o = json.loads(json.dumps(o))
        for k in o["items"]:
            k["id"] = f"{k['id']}-slot{i}"
            k["offerItemId"] = k["id"]
        out.append(o)
    return out


def make_slots(day, offers=None, times=("10:00", "10:30", "11:00"), state="available"):
    out = []
    for i, t in enumerate(times):
        slot_offers = with_ids(offers or [{"__typename": "AttractionsOffer", "id": "OFqQ7wUOEP0K", "label": "Ticket", "availabilityType": "date_time", "reservationRestrictions": {"adultRequiredForReservation": True, "maxOfferItemsPerReservation": None, "minOfferItemsPerReservation": 0},
                                  "items": kinds(adult=29.9 + (2.0 if t == "11:00" else 0))}], i)
        out.append({"__typename": "AttractionsTimeSlot", "timeSlotId": f"ATS-{PID}-{day}-{i}", "startTime": t, "startDate": day, "reservableUntil": f"{day}T{t}:00Z", "unitsAvailable": 100, "availabilityState": state, "timeSlotOffers": slot_offers})
    return out


def apollo_store(duration=None):
    product = {"duration": duration, "__typename": "AttractionsProduct", "id": PID, "slug": SLUG, "name": "Tickets into The Lisbon Oceanarium", "operatedBy": "Musement", "whatsIncluded": ["Admission"], "notIncluded": None,
               "additionalInfo": "Lisbon Oceanarium has ramps and lifts.\r\n\r\nPlease bring your ticket on your phone.", "addresses": {"arrival": None, "attraction": [{"address": "Esplanada Dom Carlos I s/nº", "city": "Lisbon", "country": "pt"}]},
               "offers": [{"__typename": "Offer", "id": "OFqQ7wUOEP0K", "label": "Ticket", "whatsIncluded": None, "notIncluded": None}, {"__typename": "Offer", "id": "OFlPzM5GTNN4", "label": "Entrance ticket", "whatsIncluded": ["Entry"], "notIncluded": ["Guide"]}]}
    key = f"AttractionsProduct:{{\"slug\":\"{SLUG}\"}}"
    return {"ROOT_QUERY": {"__typename": "Query", "attractionsProduct": {f"getProduct:{{\"input\":{{\"slug\":\"{SLUG}\",\"urlCode\":\"\"}}}}": {"__ref": key}}}, key: product}


def page_html(store=None, check=False):
    if check:
        return "<html><body>Are you a person or a robot? Press &amp; hold</body></html>"
    blob = f'<script type="application/json" data-capla-store-data="apollo">{json.dumps(store if store is not None else apollo_store())}</script>'
    return f'<html><head><title>Tickets into The Lisbon Oceanarium</title></head><body><h1>Oceanarium</h1><script>window.__ctx = {{"csrfToken":"tok-1","pageviewId":"pv-1"}};</script>{blob}</body></html>'


def run_script(adults=2, ages=(8,), slots=None, status=200, seen=None, html=None, check=False, path=None, slug=SLUG, day=date(2026, 12, 18), store=None):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = booking_attraction_recipe(f"https://www.booking.com/attractions/pt/{slug}.html", day, adults, list(ages), "Oceanarium")
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def serve(route):
        u = urlparse(route.request.url)
        if u.hostname == "accommodations.booking.com" and u.path == "/dml/graphql":
            cors = {"access-control-allow-origin": "https://www.booking.com", "access-control-allow-credentials": "true"}
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers={**cors, "access-control-allow-headers": "*", "access-control-allow-methods": "POST"})
                return
            body = json.loads(route.request.post_data)
            if seen is not None:
                seen.append({"op": body["operationName"], "input": body["variables"]["input"], "query_args": {k: v[0] for k, v in parse_qs(u.query).items()}, "headers": dict(route.request.headers), "query": body["query"][:40]})
            if status != 200:
                route.fulfill(status=status, content_type="application/json", headers=cors, body="{}")
                return
            data = {"data": {"attractionsProduct": {"getAvailability": {"timeslots": slots if slots is not None else make_slots(body["variables"]["input"]["date"])}}}}
            route.fulfill(status=200, content_type="application/json", headers=cors, body=json.dumps(data))
        elif u.hostname == "www.booking.com":
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or page_html(store, check))
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto("https://www.booking.com" + (path or f"/attractions/pt/{SLUG}.en-gb.html") + "?aid=304142&label=mkt1&date=2026-12-18&selected_currency=EUR")
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def convert_one(out, recipe, **extra):
    wishes = {"expect": recipe["expect"], **extra}
    return convert_all([{"site": "booking_attraction", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)


def test_the_real_script_asks_the_availability_service_for_the_date_and_adds_the_group_up_the_way_the_page_does():
    seen: list = []
    out, recipe = run_script(seen=seen)
    data = json.loads(out)
    assert data["ok"] is True and data["slug"] == SLUG and data["country"] == "pt" and data["activity"] == "Tickets into The Lisbon Oceanarium" and data["product_id"] == PID and data["operated_by"] == "Musement" and data["day"] == "2026-12-18"
    assert data["slots_total"] == 3 and data["unavailable"] is None and data["includes"] == "Admission" and data["meeting"] == "Esplanada Dom Carlos I s/nº, Lisbon" and data["additional"].startswith("Lisbon Oceanarium has ramps and lifts. Please bring")
    ask = seen[0]
    assert ask["op"] == "GetAvailability" and ask["input"] == {"date": "2026-12-18", "id": PID, "urlCode": "", "includeSoldOut": True} and ask["query"].startswith("query GetAvailability") and ask["query_args"]["date"] == "2026-12-18"
    assert ask["headers"]["x-booking-csrf-token"] == "tok-1" and ask["headers"]["x-booking-pageview-id"] == "pv-1" and ask["headers"]["x-booking-context-aid"] == "304142"
    r = data["rows"][0]
    assert r["ticket"] == "Ticket" and r["cur"] == "EUR" and r["total"] == 77.5 and r["totals_differ"] is True and r["unfit"] == [] and r["adult_required"] is True
    assert [(k["label"], k["count"], k["price"]) for k in r["kinds"]] == [("Adult", 2, 29.9), ("Child", 1, 17.7)] and [(s["time"], s["total"], s["bookable"]) for s in r["slots"]] == [("10:00", 77.5, True), ("10:30", 77.5, True), ("11:00", 81.5, True)]
    assert r["cancel"]["free"] is False and r["cancel"]["label"] == "Non-refundable" and r["includes"] is None
    offers, sources, problems, _, notes = convert_one(out, recipe)
    assert not problems and len(offers) == 1 and offers[0].price_total == 77.5 and offers[0].details["start_times"].endswith("11:00 81.5 EUR") and offers[0].link == URL + "?date=2026-12-18&selected_currency=EUR"


def test_the_duration_of_the_activity_is_read_from_its_product_data():
    out, _ = run_script(store=apollo_store({"__typename": "AttractionsDuration", "label": "Duration: 9 hours", "min": None, "max": None, "type": "FIXED", "value": "PT9H"}))
    data = json.loads(out)
    assert data["duration"] == "9 hours" and data["duration_iso"] == "PT9H"
    none = json.loads(run_script()[0])
    assert none["duration"] is None and none["duration_iso"] is None


def test_each_traveller_goes_in_the_kind_whose_age_range_holds_their_age():
    out, _ = run_script(adults=1, ages=(15, 1, 5))
    r = json.loads(out)["rows"][0]
    assert {k["label"]: k["count"] for k in r["kinds"]} == {"Adult": 2, "Infant": 1, "Child": 1}       # the adult and the 15-year-old are Adult (13-64), 1 is an Infant, 5 a Child (adults are always priced as Adult: the tool takes children's ages only)
    assert r["total"] == round(2 * 29.9 + 0 + 17.7, 2)


def test_a_senior_and_a_group_of_seniors_are_priced_in_the_senior_kind():
    r = json.loads(run_script(adults=1, ages=(70, 72))[0])["rows"][0]
    assert {k["label"]: k["count"] for k in r["kinds"]} == {"Adult": 1, "Senior": 2} and r["total"] == round(29.9 + 2 * 19.9, 2) and all(s["bookable"] and s["total"] > 0 for s in r["slots"])
    r = json.loads(run_script(adults=0, ages=(70, 72))[0])["rows"][0]
    assert {k["label"]: k["count"] for k in r["kinds"]} == {"Senior": 2} and r["total"] == round(2 * 19.9, 2)


def test_free_cancellation_comes_with_its_cutoff_and_a_group_the_tickets_cannot_take_is_said():
    free = {"comparedTo": "start", "hasFreeCancellation": True, "isStillRefundable": True, "label": None, "message": None, "percentage": 100, "period": "P1D", "until": "2026-12-17T10:00:00"}
    offers = [{"__typename": "AttractionsOffer", "id": "OFfree", "label": "Skip-the-line ticket", "availabilityType": "date_time", "reservationRestrictions": {"adultRequiredForReservation": False, "maxOfferItemsPerReservation": None, "minOfferItemsPerReservation": 0}, "items": kinds(adult=35.0, cancel=free)},
              {"__typename": "AttractionsOffer", "id": "OFfew", "label": "Entrance ticket", "availabilityType": "date_time", "reservationRestrictions": {"adultRequiredForReservation": False, "maxOfferItemsPerReservation": None, "minOfferItemsPerReservation": 0}, "items": kinds(left=1)}]
    out, recipe = run_script(slots=make_slots("2026-12-18", offers, times=("10:00",)))
    data = json.loads(out)
    assert [r["ticket"] for r in data["rows"]] == ["Skip-the-line ticket", "Entrance ticket"] and data["rows"][0]["cancel"]["free"] is True and data["rows"][1]["slots"][0]["bookable"] is False and "only 1 Adult left" in data["rows"][1]["slots"][0]["why"][0]
    res = convert_one(out, recipe, free_cancellation=True)
    assert [o.name for o in res[0]] == ["Tickets into The Lisbon Oceanarium (Skip-the-line ticket)"] and res[0][0].fits is True and res[0][0].details["cancellation"] == "Free cancellation until 2026-12-17 10:00 (Booking.com's own data)"
    assert any("'Entrance ticket' cannot take this group" in n for n in res[4])


def test_a_ticket_with_no_kind_for_a_traveller_is_said_and_a_date_with_no_slot_is_unavailable():
    only_adult = [{"__typename": "AttractionsOffer", "id": "OFadult", "label": "Ticket", "availabilityType": "date_time", "reservationRestrictions": {"adultRequiredForReservation": False, "maxOfferItemsPerReservation": None, "minOfferItemsPerReservation": 0}, "items": kinds(only_adult=True)}]
    out, recipe = run_script(slots=make_slots("2026-12-18", only_adult, times=("10:00",)), ages=(8,))
    assert json.loads(out)["rows"][0]["unfit"] == ["8"] and any("has no kind for: 8" in p for p in convert_one(out, recipe)[2])
    out, recipe = run_script(slots=[])
    data = json.loads(out)
    assert data["ok"] is True and data["unavailable"] == "Booking.com lists no time slot on 2026-12-18" and data["rows"] == []
    res = convert_one(out, recipe)
    assert res[0] == [] and any("never 'sold out'" in n for n in res[4])


def test_the_script_stops_on_the_wrong_page_a_failing_service_a_human_check_and_a_page_that_is_not_an_activity():
    other = json.loads(run_script(slug="another-activity-slug", html=page_html())[0])
    assert other["ok"] is False and "the page is the activity '" + SLUG + "', not 'another-activity-slug'" in other["error"]
    failing = json.loads(run_script(status=500)[0])
    assert failing["ok"] is False and "availability service could not be read" in failing["error"] and "500" in failing["error"]
    assert "human check" in json.loads(run_script(check=True)[0])["error"]
    assert "no activity data" in json.loads(run_script(html="<html><body><h1>x</h1></body></html>")[0])["error"]
    bad = json.loads(run_script(path="/hotel/pt/ritz.html")[0])
    assert bad["ok"] is False and "not a Booking.com activity page" in bad["error"]


def tiered_offers():
    """Read live 5 Nov 2026 (the Fatima day trip): a group tour with five identical Adult items (1-15 per booking, 35 each) and a private tour with one Adult item per group size (min = max per booking: 450 for 1, 225 each for 2 ... 56.25 each for 8)."""
    def adult(price, lo, hi, n):
        return [dict(kind(f"K-{n}-{i}", "adult", "Adult", price, 0, 99, True, min_per=lo, max_per=hi), constraint={"label": "(age 0-99)", "minAge": 0, "maxAge": 99, "type": "age"}) for i in range(n)]
    restr = {"adultRequiredForReservation": False, "maxOfferItemsPerReservation": None, "minOfferItemsPerReservation": 0}
    group = {"__typename": "AttractionsOffer", "id": "OFgroup", "label": "Guided Group Tour", "availabilityType": "date_time", "reservationRestrictions": restr, "items": adult(35.0, 1, 15, 5)}
    sizes = {1: 450.0, 2: 225.0, 3: 150.0, 4: 112.5, 5: 90.0, 6: 75.0, 7: 64.28, 8: 56.25}
    private_items = [it for size, price in sizes.items() for it in adult(price, size, size, 2)]      # every size twice (variants)
    private = {"__typename": "AttractionsOffer", "id": "OFprivate", "label": "Guided Group Tour - Private", "availabilityType": "date_time", "reservationRestrictions": restr, "items": private_items}
    return [group, private]


def test_an_offer_with_many_items_of_one_kind_is_priced_by_the_item_whose_booking_limits_hold_the_group():
    for n, per_person in ((1, 450.0), (3, 150.0), (8, 56.25)):
        out, recipe = run_script(adults=n, ages=(), slots=make_slots("2026-12-18", tiered_offers(), times=("08:00",)))
        data = json.loads(out)
        group, private = data["rows"]
        assert group["total"] == round(35.0 * n, 2) and [(k["label"], k["count"]) for k in group["kinds"]] == [("Adult", n)]        # five identical items are one kind, never five
        assert private["total"] == round(per_person * n, 2) and private["kinds"][0]["price"] == per_person and private["slots"][0]["bookable"] is True
        offers, _, problems, _, _ = convert_one(out, recipe)
        assert not problems and [o.price_total for o in offers] == [round(35.0 * n, 2), round(per_person * n, 2)]
    out, recipe = run_script(adults=9, ages=(), slots=make_slots("2026-12-18", tiered_offers(), times=("08:00",)))
    private = json.loads(out)["rows"][1]
    assert private["slots"][0]["bookable"] is False and "no ticket takes 9 in one booking" in private["slots"][0]["why"][0]
    res = convert_one(out, recipe)
    assert [o.name.split("(")[-1] for o in res[0]] == ["Guided Group Tour)"] and any("'Guided Group Tour - Private' cannot take this group" in n for n in res[4])
