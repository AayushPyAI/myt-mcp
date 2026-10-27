"""Europcar cars, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page built from the REAL card markup of europcar.com saved on 27 Oct 2026
(tests/fixtures/europcar/card.html: one car card with its "Vehicle details" open, scripts removed). The page keeps what the real one does: 10 cars first and 10 more after each scroll,
"Vehicle details" closed until clicked, the "Pick up / Return" summary and the address the recipe gave; nothing leaves the machine. The script's answer goes through the server's converter."""

import json
import re
from pathlib import Path

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.europcar_cars import europcar_cars_recipe

FIXTURES = Path(__file__).parent / "fixtures" / "europcar"
DETAILS_START = '<div class="ecw-vehicle-more-details ecw-vehicle-card__more-details">'
DETAILS_END = '<div class="ecw-vehicle-card__basic-information__price-section'
CARS = [("CITROEN C4 AUTOMATIC", "Compact", "5", "A", 43.25, 3458.64), ("PEUGEOT 2008", "Compact", "5", "M", 39.89, 3100.0), ("FIAT 500 ELECTRIC", "Mini", "4", "A", 60.0, 0.0),
        ("TOYOTA YARIS", "Economy", "5", "A", 35.5, 2900.0), ("RENAULT CLIO", "Economy", "5", "M", 31.2, 2500.0), ("VW GOLF", "Compact", "5", "M", 48.0, 3300.0),
        ("OPEL CORSA", "Economy", "5", "M", 29.9, 2400.0), ("SEAT IBIZA", "Economy", "5", "M", 30.1, 2450.0), ("KIA PICANTO", "Mini", "4", "M", 25.0, 2000.0),
        ("FORD FOCUS", "Compact", "5", "A", 52.0, 3400.0), ("BMW 1 SERIES", "Premium", "5", "A", 80.0, 4100.0), ("MERCEDES A CLASS", "Premium", "5", "A", 85.0, 4200.0),
        ("TOYOTA COROLLA", "Intermediate", "5", "A", 55.0, 3500.0), ("SKODA OCTAVIA", "Intermediate", "5", "M", 50.0, 3300.0), ("VOLVO V60", "Estate", "5", "A", 90.0, 4300.0),
        ("CITROEN BERLINGO", "Minivan", "7", "M", 70.0, 3800.0), ("RENAULT ESPACE", "Minivan", "7", "A", 95.0, 4500.0), ("FORD TRANSIT", "Van", "9", "M", 99.0, 4600.0),
        ("HYUNDAI I10", "Mini", "4", "A", 27.0, 2100.0), ("NISSAN QASHQAI", "SUV", "5", "A", 65.0, 3700.0), ("PEUGEOT 3008", "SUV", "5", "A", 68.0, 3750.0),
        ("TESLA MODEL 3", "Premium", "5", "A", 110.0, 0.0), ("AUDI A3", "Premium", "5", "A", 88.0, 4150.0), ("FIAT PANDA", "Mini", "4", "M", 24.0, 1900.0), ("MINI COOPER", "Compact", "4", "A", 62.0, 3000.0)]


def _card(template: str, car, symbol: str) -> tuple[str, str]:
    """(the card's HTML with its details closed, the details HTML) from the real card with this car's values."""
    name, klass, seats, gear, per_day, excess = car
    html = template.replace("CITROEN C4 AUTOMATIC", name).replace("OR SIMILAR Compact", f"OR SIMILAR {klass}")
    html = html.replace(" $43.25 <span", f" {symbol}{per_day:,.2f} <span").replace("TOTAL $86.50", f"TOTAL {symbol}{per_day * 2:,.2f}").replace("Excess: $3,458.64", f"Excess: {symbol}{excess:,.2f}")
    start = html.index("features-icons")
    end = html.index("features-list")
    counter = iter([seats, "5", "2", gear, "A/C", "19"])
    html = html[:start] + re.sub(r"<p>[^<]*</p>", lambda m: f"<p>{next(counter)}</p>", html[start:end]) + html[end:]
    i, j = html.index(DETAILS_START), html.index(DETAILS_END)
    return html[:i] + html[j:], html[i:j]


def build_page(symbol: str = "$", first: int = 10, total: int = 25) -> str:
    template = (FIXTURES / "card.html").read_text(encoding="utf-8")
    parts = [_card(template, car, symbol) for car in CARS[:total]]
    cards = [p[0] for p in parts]
    details = json.dumps([p[1] for p in parts])
    script = f"""<script>
const CARDS = {json.dumps(cards)}; const DETAILS = {details}; let shown = {first};
const list = document.getElementById('list');
const add = (n) => {{ for (let i = shown; i < Math.min(shown + n, CARDS.length); i++) {{ list.insertAdjacentHTML('beforeend', CARDS[i].replace('class="ecw-vehicle-card"', 'class="ecw-vehicle-card" data-i="' + i + '"')); }} shown = Math.min(shown + n, CARDS.length); }};
for (let i = 0; i < shown; i++) list.insertAdjacentHTML('beforeend', CARDS[i].replace('class="ecw-vehicle-card"', 'class="ecw-vehicle-card" data-i="' + i + '"'));
window.addEventListener('scroll', () => {{ if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 50) setTimeout(() => add(10), 200); }});
document.addEventListener('click', (e) => {{ const b = e.target.closest('.ecw-vehicle-card__basic-information__more-details button'); if (!b) return; const card = b.closest('.ecw-vehicle-card');
  if (!card.querySelector('.ecw-vehicle-more-details')) b.closest('.ecw-vehicle-card__basic-information__more-details').insertAdjacentHTML('afterend', DETAILS[card.dataset.i]); }});
</script>"""
    body = ('<div>Log in</div><div>US</div><div>Help</div><div>1</div><div>RENTAL LOCATION</div><div>Pick up</div><div>Lisbon Airport</div><div>2027-03-06 10:00</div><div>Return</div><div>Lisbon Airport</div>'
            '<div>2027-03-08 10:00</div><div>2</div><div>VEHICLE</div><div>Recommended</div>')
    return f'<html><body>{body}<section class="vehicles-offers"><div id="list"></div></section>{script}</body></html>'


def run_script_on(html: str, url: str | None = None, tries: int | None = None) -> tuple[str, dict]:
    """The recipe's own script on `html` at the recipe's address, the way the server's own browser runs a script (LOCAL_RETURN: the whole answer comes back)."""
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = europcar_cars_recipe("Lisbon Airport", "LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", 30, "IL")
    script = "async () => { const LOCAL_RETURN = true; " + (f"const CARD_TRIES = {tries}; " if tries else "") + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def answer(route):
        if "/reservation/vehicles" in route.request.url:
            route.fulfill(status=200, content_type="text/html", body=html)
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1300, "height": 900})
            page.route("**/*", answer)
            page.goto(url or recipe["url"])
            out = page.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe


def test_the_real_script_scrolls_the_whole_list_opens_the_details_and_the_converter_judges_the_wishes():
    out, recipe = run_script_on(build_page())
    data = json.loads(out)
    assert data["ok"] is True and data["age"] == 30 and data["residency"] == "IL" and data["cards_read"] == 25 and len(data["rows"]) == 25         # 10 first, then 10 + 5 after the scrolls
    assert data["form"] == {"pickup_place": "Lisbon Airport", "pickup_when": "2027-03-06 10:00", "dropoff_place": "Lisbon Airport", "dropoff_when": "2027-03-08 10:00"}
    first = data["rows"][0]
    assert (first["car"], first["klass"], first["seats"], first["doors"], first["bags"], first["gearbox"], first["ac"], first["min_age"]) == ("CITROEN C4 AUTOMATIC", "OR SIMILAR Compact", "5", "5", "2", "A", "A/C", "19")
    assert (first["total"], first["per_day"], first["symbol"], first["pay"], first["excess"], first["excess_text"]) == (86.5, 43.25, "$", "PAY AT DESK", 3458.64, "Excess: $3,458.64")
    assert first["mileage"] == "Unlimited mileage" and first["protection"] == "Basic protection included" and all(r["excess"] is not None for r in data["rows"])
    wishes = {"expect": recipe["expect"], "automatic": True, "zero_excess": True, "min_seats": 5}
    offers, sources, problems, by_price, notes = convert_all([{"site": "europcar_cars", "result": out, "url": recipe["url"], "wishes": wishes}], wishes)
    assert problems == [] and len(offers) == 25 and sources[0].read == 25 and {o.currency for o in offers} == {"USD"}
    fits = {o.name.split(" (")[0]: o.fits for o in offers}
    assert fits["TESLA MODEL 3"] is True and fits["FIAT 500 ELECTRIC"] is False and fits["CITROEN C4 AUTOMATIC"] is False       # zero excess AND automatic AND 5 seats: only the Tesla
    assert sum(1 for v in fits.values() if v) == 1 and all(not o.quotable for o in offers)
    assert any("priced this search in USD" in n for n in notes) and any("public website price" in n for n in notes)
    fx = {"factors": {"USD": 0.8885}, "date": "2026-10-26", "age_days": 1, "source": "Bank of Israel representative rates"}
    euro = convert_all([{"site": "europcar_cars", "result": out, "url": recipe["url"], "wishes": {**wishes, "fx": fx}}], {**wishes, "fx": fx})[0]
    assert {o.currency for o in euro} == {"EUR"} and next(o for o in euro if o.name.startswith("CITROEN")).price_total == round(86.5 * 0.8885, 2)


def test_the_real_script_reads_euro_prices_and_a_short_list_without_more_scrolling():
    data = json.loads(run_script_on(build_page("€", first=4, total=4))[0])
    assert data["cards_read"] == 4 and data["rows"][2]["symbol"] == "€" and data["rows"][2]["total"] == 120.0
    wishes = {"expect": europcar_cars_recipe("Lisbon Airport", "LIST01", "LIST01", "2027-03-06", "10:00", "2027-03-08", "10:00", 30, "IL")["expect"], "max_total": 100}
    offers = convert_all([{"site": "europcar_cars", "result": json.dumps(data), "url": "u", "wishes": wishes}], wishes)[0]
    assert {o.currency for o in offers} == {"EUR"} and {o.name.split(" (")[0]: o.fits for o in offers} == {"CITROEN C4 AUTOMATIC": True, "PEUGEOT 2008": True, "FIAT 500 ELECTRIC": False, "TOYOTA YARIS": True}


def test_the_real_script_stops_when_the_address_is_not_the_one_asked():
    url = "https://www.europcar.com/en-us/reservation/vehicles?vehicleType=CR&pickupLocation=LIST01&driverAge=26&countryOfResidence=IN"
    data = json.loads(run_script_on(build_page(total=3), url=url)[0])
    assert data["ok"] is False and "driver age 26 instead of 30" in data["error"] and "residency IN instead of IL" in data["error"]


def test_the_real_script_says_it_could_not_read_a_page_without_cars():
    data = json.loads(run_script_on("<html><body><section class='vehicles-offers'></section></body></html>", tries=2)[0])
    assert data["ok"] is False and "no cars are shown" in data["error"] and "never say sold out" in data["error"]
