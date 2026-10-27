"""Booking.com flights, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page that behaves like the real one (27 Oct 2026): flight cards with the site's own data-testid parts,
"We found N flight options", a Sort button with a menu (Best / Cheapest / Fastest) that changes the list inside the page, page numbers under the list (an <ol> of buttons, aria-current on the open one,
15 flights a page), the stops radio, the airlines and flight-times filter boxes. Every change of the list comes after a short delay, like the site's. Nothing leaves the machine."""

import json
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.booking_flights import booking_flights_recipe
from tests.test_booking_flights import DAY, EXPECT, RECIPE


def page(total_pages=9, found=133, no_direct=False, airlines_off=0, times_on=0, stops_radio="-1", sym="€", legs=1, cards_per_page=15) -> str:
    cfg = {"pages": total_pages, "found": found, "sym": sym, "legs": legs, "per": cards_per_page}
    banner = "<p>There are no direct flights for your search. Here are other options you might like.</p>" if no_direct else ""
    airlines = "".join(f'<label><input type="checkbox" {"" if i < airlines_off else "checked"}>Airline {i}</label>' for i in range(5))
    times = "".join(f'<label><input type="checkbox" {"checked" if i < times_on else ""}>{h}</label>' for i, h in enumerate(["00:00-05:59", "06:00-11:59"]))
    radios = "".join(f'<label><input type="radio" name="filters-stops-option" value="{v}" {"checked" if v == stops_radio else ""}>{t}</label>' for v, t in (("-1", "Any"), ("0", "Direct only"), ("1", "1 stop max")))
    return f"""<html><head><meta charset='utf-8'></head><body>
<div data-testid="airlines_filter">{airlines}</div><div data-testid="flight_times_filter">{times}</div><div>{radios}</div>
<p>We found {found} flight options</p>{banner}<button id="sortbtn">Sort by: Best</button><div id="menu"></div><div id="list"></div><ol id="pager"></ol>
<script>
const CFG = {json.dumps(cfg)}; const state = {{ sort: 'Best', page: 1 }};
const sortbtn = document.getElementById('sortbtn');
function card(i) {{
  const shared = i === 0 && state.page === 1;      // the same flight is first in the Best list and in the Cheapest list
  const name = shared ? 'Shared Air' : state.sort + ' ' + state.page + '-' + i;
  const price = shared ? 313 : (state.sort === 'Cheapest' ? 320 : 400) + state.page * 10 + i;
  let segs = '';
  for (let k = 0; k < CFG.legs; k++) segs += '<div data-testid="flight_card_segment_departure_time_' + k + '">23:30</div><div data-testid="flight_card_segment_departure_airport_' + k + '">TLV</div><div data-testid="flight_card_segment_departure_date_' + k + '">6 Mar</div>'
    + '<div data-testid="flight_card_segment_stops_' + k + '">1 stop</div><div data-testid="flight_card_segment_duration_' + k + '">25h</div><div data-testid="flight_card_segment_destination_time_' + k + '">22:30</div>'
    + '<div data-testid="flight_card_segment_destination_airport_' + k + '">LIS</div><div data-testid="flight_card_segment_destination_date_' + k + '">7 Mar</div>';
  return '<div data-testid="searchresults_card"><span>Flight option ' + (i + 1) + ' of ' + CFG.per + '</span><div>Flexible ticket upgrade available</div>' + segs + '<div data-testid="flight_card_carriers">' + name + '</div>'
    + '<div data-testid="upt_price">' + CFG.sym + Math.round(price / 2) + '</div><div data-testid="flight_card_price_total_price">' + CFG.sym + price + ' total</div><button>View details</button></div>';
}}
function render() {{
  document.getElementById('list').innerHTML = Array.from({{ length: CFG.per }}, (_, i) => card(i)).join('');
  document.getElementById('pager').innerHTML = Array.from({{ length: CFG.pages }}, (_, i) => '<li><button' + (i + 1 === state.page ? ' aria-current="page"' : '') + '>' + (i + 1) + '</button></li>').join('');
  document.querySelectorAll('#pager button').forEach((b) => b.addEventListener('click', () => setTimeout(() => {{ state.page = parseInt(b.innerText, 10); render(); }}, 300)));
  sortbtn.innerText = 'Sort by: ' + state.sort;
}}
sortbtn.addEventListener('click', () => {{
  document.getElementById('menu').innerHTML = ['Best We look at the price, travel time, number of stops and baggage allowance', 'Cheapest', 'Fastest'].map((t) => '<button role="menuitem">' + t + '</button>').join('');
  document.querySelectorAll('#menu button').forEach((b) => b.addEventListener('click', () => setTimeout(() => {{ state.sort = b.innerText.split(' ')[0]; state.page = 1; document.getElementById('menu').innerHTML = ''; render(); }}, 300)));
}});
render();
</script></body></html>"""


def run_script(page_html: str, recipe: dict | None = None, url: str | None = None, tries: int | None = None) -> str:
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = recipe or RECIPE
    script = "async () => { const LOCAL_RETURN = true; " + (f"const CARD_TRIES = {tries}; " if tries else "") + recipe["script"].replace("await (async", "return (async", 1) + " }"

    def serve(route):
        if urlparse(route.request.url).path.startswith("/flights/"):
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


def convert_one(data: dict, recipe: dict | None = None):
    rec = recipe or RECIPE
    return convert_all([{"site": "booking_flights", "result": json.dumps(data), "url": rec["url"], "wishes": {"expect": rec["expect"]}}], {"expect": rec["expect"]})


def test_the_real_script_reads_two_pages_of_best_then_picks_cheapest_in_the_menu_and_reads_two_pages_of_that():
    data = json.loads(run_script(page()))
    assert data["ok"] is True and len(data["rows"]) == 60 and data["results_total"] == 133 and data["per_page"] == 15
    assert data["form"] == {"type": "ONEWAY", "origin": "TLV", "destination": "LIS", "day": "2027-03-06", "adults": 2, "children": 0, "cabin": "ECONOMY", "currency": "EUR", "sort": "BEST", "stops": None}
    assert data["filters"] == {"stops": "-1", "airlines_off": 0, "times_on": 0} and data["no_direct_notice"] is False
    assert data["sorts"] == [{"sort": "Best", "shown_as": "Best", "pages_read": 2, "pages_seen": 9}, {"sort": "Cheapest", "shown_as": "Cheapest", "pages_read": 2, "pages_seen": 9}]
    by = [(r["sort"], r["page"]) for r in data["rows"]]
    assert by[:2] == [("Best", 1), ("Best", 1)] and by.count(("Best", 1)) == 15 and by.count(("Best", 2)) == 15 and by.count(("Cheapest", 1)) == 15 and by.count(("Cheapest", 2)) == 15
    assert data["rows"][1]["carriers"] == "Best 1-1" and data["rows"][16]["carriers"] == "Best 2-1" and data["rows"][31]["carriers"] == "Cheapest 1-1" and data["rows"][1]["total"] == 411
    offers, sources, problems, by_price, notes = convert_one(data)
    assert problems == [] and len(offers) == 59 and sources[0].read == 59 and sources[0].of == 133 and by_price is True        # the shared flight is one row
    assert [o.details["from_tab"] for o in offers if o.name.startswith("Shared Air")] == ["Best and Cheapest"]


def test_the_real_script_reads_only_the_first_page_of_each_sort_when_one_page_is_asked():
    rec = booking_flights_recipe("TLV", "LIS", DAY, 2, False, "economy", 1)
    data = json.loads(run_script(page(), rec))
    assert data["ok"] is True and len(data["rows"]) == 30 and {s["pages_read"] for s in data["sorts"]} == {1}


def test_the_real_script_reads_fewer_pages_than_asked_when_the_list_has_fewer_and_says_how_many_it_saw():
    rec = booking_flights_recipe("TLV", "LIS", DAY, 2, False, "economy", 3)
    data = json.loads(run_script(page(total_pages=1, found=15), rec))
    assert data["ok"] is True and len(data["rows"]) == 30 and all(s["pages_read"] == 1 and s["pages_seen"] == 1 for s in data["sorts"])


def test_direct_only_reads_the_stops_radio_and_a_route_without_direct_flights_is_told_by_the_page_banner():
    rec = booking_flights_recipe("TLV", "ATH", DAY, 2, True)
    ok = json.loads(run_script(page(stops_radio="0"), rec, url=rec["url"]))
    assert ok["ok"] is True and ok["filters"]["stops"] == "0" and ok["form"]["stops"] == "0"
    offers, _, problems, _, notes = convert_one(ok, rec)
    assert problems == [] and any("direct-only filter was set in the address" in n for n in notes)
    none = json.loads(run_script(page(stops_radio="-1", no_direct=True), rec, url=rec["url"]))
    assert none["no_direct_notice"] is True and none["filters"]["stops"] == "-1"
    offers, _, problems, _, notes = convert_one(none, rec)
    assert problems == [] and all(o.fits is False for o in offers) and any("no direct flights for this search" in n for n in notes)


def test_a_changed_airline_or_flight_times_filter_or_a_stops_radio_that_was_not_asked_is_read_and_refused_by_the_converter():
    off = json.loads(run_script(page(airlines_off=2, times_on=1, stops_radio="1"), booking_flights_recipe("TLV", "LIS", DAY, 2, False, "economy", 1)))
    assert off["filters"] == {"stops": "1", "airlines_off": 2, "times_on": 1}
    _, _, problems, _, _ = convert_one(off, booking_flights_recipe("TLV", "LIS", DAY, 2, False, "economy", 1))
    assert any("stops filter 1 instead of -1" in p and "2 airline box(es) switched off" in p and "1 flight-time box(es) ticked" in p for p in problems)


def test_the_real_script_stops_when_the_address_is_not_the_one_asked():
    url = RECIPE["url"].replace("depart=2027-03-06", "depart=2027-03-07").replace("currency=EUR", "currency=USD").replace("ECONOMY", "BUSINESS") + "&stops=0"
    data = json.loads(run_script(page(), url=url))
    assert data["ok"] is False and "day 2027-03-07 instead of 2027-03-06" in data["error"] and "currency USD instead of EUR" in data["error"] and "cabin BUSINESS instead of ECONOMY" in data["error"] and "stops 0 instead of null" in data["error"]


def test_the_real_script_says_it_could_not_read_a_page_with_no_cards_or_a_human_check():
    silent = json.loads(run_script("<html><body><h1>Searching</h1></body></html>", tries=2))
    assert silent["ok"] is False and "never say there are none" in silent["error"]
    check = json.loads(run_script("<html><body>Please verify you are human</body></html>"))
    assert check["ok"] is False and "human check" in check["error"] and "do not work around" in check["error"]


def test_a_card_with_two_legs_or_another_currency_reaches_the_converter_and_is_refused_there():
    rec = booking_flights_recipe("TLV", "LIS", DAY, 2, False, "economy", 1)
    two = json.loads(run_script(page(legs=2), rec))
    off, _, problems, _, _ = convert_one(two, rec)
    assert off == [] and any("2 legs, not one" in p for p in problems)
    usd = json.loads(run_script(page(sym="$"), rec))
    off, _, problems, _, _ = convert_one(usd, rec)
    assert off == [] and any("not euro" in p for p in problems)
