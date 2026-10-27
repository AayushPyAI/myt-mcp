"""Booking.com attractions, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page built like the real one (27 Oct 2026): activity cards with the site's own data-testid parts
(card-title, review-score, price), 15 cards first and 15 more each time the page is scrolled to the bottom (up to 45), and an address that the site redirects to <city>.en-gb.html. Nothing leaves the machine."""

import json
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.booking_attractions import booking_attractions_recipe
from tests.test_booking_attractions import DAY, EXPECT, RECIPE


def card(i: int, sym: str = "€", price_html: str | None = None) -> str:
    price = price_html or (f"From | {sym} {30 + i} | {sym} {25 + i}.05 | Original price from {sym} {30 + i}. Current price from {sym} {25 + i}.05" if i % 2 == 0 else f"From | {sym} {30 + i} | Current price from {sym} {30 + i}")
    return (f'<div data-testid="card"><a href="/attractions/pt/pr{i}-tour-{i}.html?aid=304142&label=x#srj">go</a><div>#{i + 1} Best seller</div><div data-testid="card-title">Tour number {i}</div>'
            f'<div>{"Duration: 2 hours 30 minutes" if i % 3 == 0 else ""}</div><div data-testid="review-score">User reviews, Fabulous, 9.{i % 10} out of 10 from {1000 + i} reviews</div>'
            f'<div>{"Free cancellation available" if i % 2 == 0 else ""}</div><div data-testid="price">{price.replace(" | ", "<br>")}</div><div>See availability</div></div>')


def page(total=45, **kw) -> str:
    items = [card(i, **kw) for i in range(total)]
    return ("<html><head><meta charset='utf-8'></head><body><h1>Lisbon experiences</h1><div id='list'>" + "".join(items[:15]) + "</div><div style='height:3000px'></div>"
            "<script>const MORE = " + json.dumps(items[15:]) + "; let shown = 0;"
            "window.addEventListener('scroll', function () { if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 5 && shown < MORE.length) { document.getElementById('list').insertAdjacentHTML('beforeend', MORE.slice(shown, shown + 15).join('')); shown += 15; } });</script></body></html>")


def run_script(page_html: str, recipe: dict | None = None, url: str | None = None, tries: int | None = None) -> str:
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = recipe or RECIPE
    script = "async () => { const LOCAL_RETURN = true; " + (f"const CARD_TRIES = {tries}; " if tries else "") + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def serve(route):
        if urlparse(route.request.url).path.startswith("/attractions/"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=page_html)
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page_ = browser.new_page(viewport={"width": 1300, "height": 900})
            page_.route("**/*", serve)
            page_.goto(url or RECIPE["url"].replace("lisbon.html", "lisbon.en-gb.html"))      # the site's own redirect keeps the values and changes the path
            page_.wait_for_load_state("domcontentloaded")
            out = page_.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out


def test_the_real_script_scrolls_for_more_cards_reads_their_parts_and_the_converter_makes_rows():
    data = json.loads(run_script(page(), booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 40)))
    assert data["ok"] is True and len(data["rows"]) == 40 and data["cards_on_page"] >= 40 and data["heading"] == "Lisbon experiences"
    assert data["form"] == {"place": "pt/lisbon", "day": "2027-03-07", "day_to": "2027-03-07", "adults": 2, "currency": "EUR"}
    r0, r1 = data["rows"][0], data["rows"][1]
    assert r0 == {"title": "Tour number 0", "cur": "€", "from": 25.05, "was": 30.0, "rating": 9.0, "reviews": 1000, "duration": "2 hours 30 minutes", "free_cancel": True, "best_seller": "1", "available_from": None, "path": "/attractions/pt/pr0-tour-0.html"}
    assert r1["from"] == 31.0 and r1["was"] is None and r1["duration"] is None and r1["free_cancel"] is False
    offers, sources, problems, _, notes = convert_all([{"site": "booking_attractions", "result": json.dumps(data), "url": RECIPE["url"], "wishes": {"expect": EXPECT}}], {"expect": EXPECT})
    assert problems == [] and len(offers) == 40 and sources[0].read == 40 and sources[0].of == 40 and any("does not say how many" in n for n in notes)


def test_the_real_script_reads_only_the_first_cards_when_the_window_is_small_and_never_presses_anything():
    data = json.loads(run_script(page(), booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 10)))
    assert data["ok"] is True and len(data["rows"]) == 10 and data["cards_on_page"] == 15 and data["rows"][9]["title"] == "Tour number 9"


def test_the_real_script_stops_when_the_address_is_not_the_one_asked():
    url = "https://www.booking.com/attractions/searchresults/pt/porto.en-gb.html?date_from=2027-03-08&date_to=2027-03-08&adults=3&selected_currency=INR"
    data = json.loads(run_script(page(), url=url))
    assert data["ok"] is False and "place pt/porto instead of pt/lisbon" in data["error"] and "day 2027-03-08 instead of 2027-03-07" in data["error"] and "currency INR instead of EUR" in data["error"]


def test_the_real_script_says_it_could_not_read_a_page_with_no_cards_or_a_human_check_or_a_card_it_does_not_know():
    silent = json.loads(run_script("<html><body><h1>Loading</h1></body></html>", tries=2))
    assert silent["ok"] is False and "never say there are none" in silent["error"]
    check = json.loads(run_script("<html><body>Please verify you are human</body></html>"))
    assert check["ok"] is False and "human check" in check["error"] and "do not work around" in check["error"]
    odd = json.loads(run_script(page(total=1, price_html="Sold out")))
    assert odd["ok"] is True and odd["rows"] == [] and len(odd["unparsed"]) == 1


def test_a_price_in_another_currency_reaches_the_converter_and_is_refused_there():
    usd = json.loads(run_script(page(total=2, sym="$")))
    off, _, problems, _, _ = convert_all([{"site": "booking_attractions", "result": json.dumps(usd), "url": RECIPE["url"], "wishes": {"expect": EXPECT}}], {"expect": EXPECT})
    assert off == [] and any("not euro" in p for p in problems)
