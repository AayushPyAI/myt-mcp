"""iWay, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page built like the real one (27 Oct 2026): header with the account's currency button and the Rides link, the two
address boxes, "En route: 9 km ≈ 30m" and "Choose car class" with one button.class-item per vehicle class (class, passengers, bags, car, price, "Order now"). Nothing leaves the machine."""

import json
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.iway_transfers import iway_transfers_recipe
from tests.test_iway import DAY, EXPECT, FX, RECIPE

CLASSES = [("Standard", 3, 3, "Toyota Corolla and similar", "$28.41"), ("Business", 3, 3, "Mercedes-Benz E-class w213 and similar", "$37.16"),
           ("Minivan", 6, 4, "Mercedes-Benz Vito and similar", "$41.53"), ("Minivan VIP", 6, 4, "Mercedes-Benz V-class and similar", "$65.57")]


def page(classes=CLASSES, logged_in=True, from_name="Airport Lisbon Portela", to_name="Praça do Comércio", price_text=None) -> str:
    buttons = "".join(f'<button class="class-item"><span class="class-item__inner-wrapper"><div>{k}</div><div>{p}</div><div>{b}</div><div>{car}</div><div>{price_text or price}</div><div>Order now</div></span></button>' for k, p, b, car, price in classes)
    account = '<a href="https://account.iway.io/rides">Rides</a>' if logged_in else '<a href="/login">Log in</a>'
    listing = f'<div class="iwns__class-list"><p>Choose car class</p><div><button>Copy offers</button></div>{buttons}</div>' if classes else ""
    return f"""<html><head><meta charset='utf-8'></head><body><header><a href="/booking">New booking</a>{account}<button>USD</button></header>
<main><h1>Transfer</h1><input placeholder="Address, airport, hotel or other place" value="{from_name}"><input placeholder="Address, airport, hotel or other place" value="{to_name}">
<div>En route: 9 km ≈ 30m</div>{listing}</main></body></html>"""


def run_script(page_html: str, recipe: dict | None = None, url: str | None = None, tries: int | None = None) -> str:
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = recipe or RECIPE
    script = "async () => { const LOCAL_RETURN = true; " + (f"const ITEM_TRIES = {tries}; " if tries else "") + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def serve(route):
        if urlparse(route.request.url).path.startswith("/booking"):
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=page_html)
        else:
            route.abort()
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page_ = browser.new_page(viewport={"width": 1300, "height": 900})
            page_.route("**/*", serve)
            page_.goto(url or recipe["url"])
            page_.wait_for_load_state("domcontentloaded")
            out = page_.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out


def test_the_real_script_reads_the_four_classes_the_places_the_route_and_the_login_and_the_converter_makes_euro_rows():
    data = json.loads(run_script(page()))
    assert data["ok"] is True and data["unparsed"] == [] and len(data["rows"]) == 4
    assert data["form"] == {"from_id": EXPECT["from_id"], "to_id": EXPECT["to_id"], "from_name": "Airport Lisbon Portela", "to_name": "Praça do Comércio", "header_currency": "USD", "logged_in": True, "route": ["9", "30m"]}
    assert data["rows"][0] == {"klass": "Standard", "passengers": 3, "bags": 3, "car": "Toyota Corolla and similar", "symbol": "$", "price": 28.41}
    assert data["rows"][3] == {"klass": "Minivan VIP", "passengers": 6, "bags": 4, "car": "Mercedes-Benz V-class and similar", "symbol": "$", "price": 65.57}      # the price, not the 6 of its capacity
    offers, sources, problems, _, notes = convert_all([{"site": "iway_transfers", "result": json.dumps(data), "url": RECIPE["url"], "wishes": {"expect": EXPECT, "fx": FX}}], {"expect": EXPECT, "fx": FX})
    assert problems == [] and len(offers) == 4 and offers[3].price_total == round(65.57 * 0.8932, 2) and sources[0].read == 4


def test_the_real_script_stops_when_the_page_has_other_places_than_the_url_asked_or_no_list():
    other = RECIPE["url"].replace(EXPECT["to_id"], "ChIJother")
    wrong = json.loads(run_script(page(), url=other))
    assert wrong["ok"] is False and "to is another place than asked" in wrong["error"]
    nolist = json.loads(run_script(page(classes=[]), tries=2))
    assert nolist["ok"] is False and "never say there is no transfer" in nolist["error"]
    elsewhere = json.loads(run_script(page(), url="https://iway.io/booking/rent?from=a&to=b"))
    assert elsewhere["ok"] is False and "not the iWay booking page" in elsewhere["error"]


def test_a_human_check_is_never_worked_around_and_a_logged_out_page_is_told():
    check = json.loads(run_script("<html><body>Please verify you are human</body></html>"))
    assert check["ok"] is False and "human check" in check["error"] and "do not work around" in check["error"]
    out = json.loads(run_script(page(logged_in=False)))
    assert out["form"]["logged_in"] is False
    _, _, _, _, notes = convert_all([{"site": "iway_transfers", "result": json.dumps(out), "url": RECIPE["url"], "wishes": {"expect": EXPECT, "fx": FX}}], {"expect": EXPECT, "fx": FX})
    assert any("did not show the agency account as logged in" in n for n in notes)


def test_a_class_with_no_price_line_is_left_to_the_converter_as_an_unknown_card_and_a_page_for_other_places_is_refused_there():
    odd = json.loads(run_script(page(classes=[("Standard", 3, 3, "Toyota Corolla", "Sold out")])))
    assert odd["ok"] is True and odd["rows"] == [] and len(odd["unparsed"]) == 1
    _, _, problems, _, _ = convert_all([{"site": "iway_transfers", "result": json.dumps(odd), "url": RECIPE["url"], "wishes": {"expect": EXPECT, "fx": FX}}], {"expect": EXPECT, "fx": FX})
    assert any("does not know" in p for p in problems)
    unknown = iway_transfers_recipe("Hotel Ritz Lisbon", "Hotel Tivoli Lisbon", DAY, "10:00", 2)      # places iWay's table does not know: no ids in the recipe, the name decides
    faro = json.loads(run_script(page(from_name="Faro Airport"), unknown, url="https://iway.io/booking?from=ChIJanything&to=ChIJother"))
    _, _, problems, _, _ = convert_all([{"site": "iway_transfers", "result": json.dumps(faro), "url": unknown["url"], "wishes": {"expect": unknown["expect"], "fx": FX}}], {"expect": unknown["expect"], "fx": FX})
    assert any("searched from 'Faro Airport', not 'Hotel Ritz Lisbon'" in p for p in problems)
    renamed = json.loads(run_script(page(from_name="Humberto Delgado Airport", to_name="Praca do Comercio")))      # the id is the known one: another way of writing the name is fine
    _, _, problems, _, _ = convert_all([{"site": "iway_transfers", "result": json.dumps(renamed), "url": RECIPE["url"], "wishes": {"expect": EXPECT, "fx": FX}}], {"expect": EXPECT, "fx": FX})
    assert problems == []
