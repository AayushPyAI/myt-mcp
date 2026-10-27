"""Bensaude Hotels, integration: the REAL script runs in a real browser (Playwright's Chromium) on the REAL markup of the booking engine saved on 27 Oct 2026
(tests/fixtures/bensaude: the availability page of Terra Nostra Garden Hotel, 6 to 8 Mar 2027, 2 adults, and two rate plan detail pages, scripts and styles removed),
the page's own requests are answered from the fixtures (nothing leaves the machine), and the script's answer goes through the server's converter."""

import json
from datetime import date
from pathlib import Path

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.bensaude_hotels import bensaude_hotels_recipe

FIXTURES = Path(__file__).parent / "fixtures" / "bensaude"


class _Day(date):
    @classmethod
    def today(cls):
        return date(2026, 10, 27)


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def run_script_on(html: str, wait_tries: int | None = None) -> tuple[str, dict]:
    """The recipe's own script on `html`, the way the server's own browser runs a script (LOCAL_RETURN: the whole answer comes back)."""
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = bensaude_hotels_recipe(29, date(2027, 3, 6), date(2027, 3, 8))
    script = "async () => { const LOCAL_RETURN = true; " + (f"const ROOM_TRIES = {wait_tries}; " if wait_tries else "") + recipe["script"].replace("await (async", "return (async", 1) + " }"
    detail_1, detail_2 = _read("detail_1.html"), _read("detail_2.html")

    def answer(route):
        url = route.request.url
        if "availability.aspx" in url:
            route.fulfill(status=200, content_type="text/html", body=html)
        elif "RatePlanDetail" in url:
            route.fulfill(status=200, content_type="text/html", body=detail_2 if "RatePlanID=314" in url else detail_1)
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1300, "height": 900})
            page.route("**/*", answer)
            page.goto(recipe["url"])
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def test_the_real_script_reads_every_rate_plan_of_the_real_page_and_the_converter_turns_it_into_offers(monkeypatch):
    monkeypatch.setattr("myt_mcp.sites.bensaude_hotels.date", _Day)
    out, recipe = run_script_on(_read("availability.html"))
    data = json.loads(out)
    assert data["ok"] is True and data["hotel"] == "Terra Nostra Garden Hotel" and data["hotel_id"] == 29 and data["adults"] == 2 and data["children_on_page"] == 0
    assert data["check_in"] == "06/03/2027" and data["check_out"] == "08/03/2027" and len(data["rows"]) == 11 and data["details_read"] == 11 and data["details_failed"] == 0
    wishes = {"expect": recipe["expect"], "breakfast": True, "free_cancellation": True}
    offers, sources, problems, by_price, notes = convert_all([{"site": "bensaude_hotels", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)
    assert problems == [] and len(offers) == 11 and sources[0].read == 11
    by = {o.name: o for o in offers}
    cosy = by["Terra Nostra Garden Hotel - Cosy Art Deco - FLEX"]            # the room name carries no "Recommended" badge
    assert (cosy.price_total, cosy.currency, cosy.flexible, cosy.fits, cosy.quotable) == (322.0, "EUR", True, True, True)
    assert cosy.details["meal"] == "Breakfast included" and cosy.details["cancellation"].startswith("free cancellation until 27 Feb 2027") and cosy.details["local_tax"].startswith("€2 per night")
    half = by["Terra Nostra Garden Hotel - Cosy Art Deco - TN Special"]
    assert half.price_total == 466.0 and half.details["meal"].startswith("Half board") and half.details["special_offer"] is True
    assert sorted(o.price_total for o in offers)[:4] == [322.0, 394.0, 466.0, 466.0] and max(o.price_total for o in offers) == 2122.0
    assert any("public website rate" in n for n in notes)


def test_the_real_script_stops_when_the_page_still_prices_a_child_from_an_earlier_search():
    """27 Oct 2026, seen live: after one search with a child, the same address with children=0 still showed rate links with children=1 (3 rooms, higher prices)."""
    html = _read("availability.html").replace("children=0", "children=1").replace("totalExtraChildren=0", "totalExtraChildren=1")
    data = json.loads(run_script_on(html)[0])
    assert data["ok"] is False and data["children_on_page"] == 2 and "NEW Chrome window" in data["error"]


def test_the_real_script_says_it_could_not_read_a_page_without_rooms():
    data = json.loads(run_script_on("<html><body><div>Hotel / Destination</div></body></html>", wait_tries=2)[0])
    assert data["ok"] is False and "no rooms are shown" in data["error"]
