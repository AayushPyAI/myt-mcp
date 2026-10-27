"""Booking.com attractions, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page that behaves like the real one (27 Oct 2026): activity cards with the site's own data-testid parts
(card-title, review-score, price), 15 cards first and 15 more each time the page is scrolled to the bottom, the sort box (radios "Our top picks" / "Lowest price" / "Best reviewed" whose ids end in -trending,
-lowest_price, -highest_weighted_rating), the filter boxes that are ticked from the address (filter_by_label[]=free_cancellation ...), and an address the site redirects to <city>.en-gb.html. Nothing leaves the machine."""

import json
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.booking_attractions import booking_attractions_recipe
from tests.test_booking_attractions import DAY, EXPECT, RECIPE


def page(total=60, sym="€", price_html=None, radios=("trending", "lowest_price", "highest_weighted_rating")) -> str:
    cfg = {"total": total, "sym": sym, "price_html": price_html}
    sort_radios = "".join(f'<label><input type="radio" name="sort" id=":R1:-{k}" {"checked" if k == "trending" else ""}>{k}</label>' for k in radios)
    filters = ("".join(f'<label><input type="checkbox" name="filter_by_label" value="{v}">{v}</label>' for v in ("free_cancellation", "skip_the_line"))
               + "".join(f'<label><input type="checkbox" name="filter_by_min_rating" value="{v}">{v} up</label>' for v in ("4.5", "4.0")))
    return f"""<html><head><meta charset='utf-8'></head><body><h1>Lisbon experiences</h1><div>{sort_radios}</div><div>{filters}</div><div id="list"></div><div style="height:3000px"></div>
<script>
const CFG = {json.dumps(cfg)}; const q = new URLSearchParams(location.search); const state = {{ sort: q.get('sort_by') || 'trending', shown: 15 }};
document.querySelectorAll('input[type=checkbox]').forEach((b) => {{ b.checked = q.getAll(b.name + '[]').includes(b.value); }});
function card(i) {{
  const shared = i === 0;      // the same activity is first in every sort
  const title = shared ? 'Shared tour' : state.sort + ' tour ' + i;
  const price = shared ? 26 : (state.sort === 'trending' ? 30 : 40) + i;
  const priceBlock = CFG.price_html !== null ? CFG.price_html : (i % 2 === 0 ? 'From<br>' + CFG.sym + ' ' + (price + 5) + '<br>' + CFG.sym + ' ' + price + '.05<br>Original price from ' + CFG.sym + ' ' + (price + 5) + '. Current price from ' + CFG.sym + ' ' + price + '.05'
    : 'From<br>' + CFG.sym + ' ' + price + '<br>Current price from ' + CFG.sym + ' ' + price);
  return '<div data-testid="card"><a href="/attractions/pt/pr' + i + '-' + state.sort + '.html?aid=1#srj">go</a><div>#' + (i + 1) + ' Best seller</div><div data-testid="card-title">' + title + '</div>'
    + '<div>' + (i % 3 === 0 ? 'Duration: 2 hours 30 minutes' : '') + '</div><div data-testid="review-score">User reviews, Fabulous, 9.' + (i % 10) + ' out of 10 from ' + (1000 + i) + ' reviews</div>'
    + '<div>' + (i % 2 === 0 ? 'Free cancellation available' : '') + '</div><div data-testid="price">' + priceBlock + '</div><div>See availability</div></div>';
}}
function render() {{ document.getElementById('list').innerHTML = Array.from({{ length: state.shown }}, (_, i) => card(i)).join(''); }}
document.querySelectorAll('input[name="sort"]').forEach((r) => {{
  r.checked = r.id.endsWith('-' + state.sort);
  r.addEventListener('click', () => setTimeout(() => {{ state.sort = r.id.replace(/^.*-/, ''); state.shown = 15; document.querySelectorAll('input[name="sort"]').forEach((x) => {{ x.checked = x === r; }}); render(); window.scrollTo(0, 0); }}, 300));
}});
window.addEventListener('scroll', () => {{ if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 5 && state.shown < CFG.total) {{ state.shown = Math.min(CFG.total, state.shown + 15); render(); }} }});
render();
</script></body></html>"""


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
            page_.goto(url or recipe["url"].replace("lisbon.html", "lisbon.en-gb.html"))      # the site's own redirect keeps the values and changes the path
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
    return convert_all([{"site": "booking_attractions", "result": json.dumps(data), "url": rec["url"], "wishes": {"expect": rec["expect"]}}], {"expect": rec["expect"]})


def test_the_real_script_reads_thirty_cards_of_top_picks_then_picks_best_reviewed_and_reads_thirty_of_that():
    data = json.loads(run_script(page(), booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 30)))
    assert data["ok"] is True and len(data["rows"]) == 60 and data["heading"] == "Lisbon experiences" and data["filters_on"] == [] and data["filters_on_end"] == []
    assert data["form"] == {"place": "pt/lisbon", "day": "2027-03-07", "day_to": "2027-03-07", "adults": 2, "currency": "EUR", "sort": None, "labels": [], "min_rating": [], "language": [], "time_of_day": []}
    assert [(x["sort"], x["shown_as"], x["read"]) for x in data["sorts"]] == [("Our top picks", "trending", 30), ("Best reviewed", "highest_weighted_rating", 30)] and all(x["cards_on_page"] >= 30 for x in data["sorts"])
    top, best = data["rows"][:30], data["rows"][30:]
    assert {r["sort"] for r in top} == {"Our top picks"} and {r["sort"] for r in best} == {"Best reviewed"}
    assert top[1]["title"] == "trending tour 1" and top[1]["from"] == 31.0 and best[1]["title"] == "highest_weighted_rating tour 1"
    r0 = top[0]
    assert r0 == {"sort": "Our top picks", "title": "Shared tour", "cur": "€", "from": 26.05, "was": 31.0, "rating": 9.0, "reviews": 1000, "duration": "2 hours 30 minutes", "free_cancel": True, "best_seller": "1", "available_from": None, "path": "/attractions/pt/pr0-trending.html"}
    offers, sources, problems, _, notes = convert_one(data)
    assert problems == [] and len(offers) == 59 and sources[0].read == 59 and any("Our top picks: 30 cards, Best reviewed: 30 cards" in n for n in notes)       # the shared activity is one row
    assert [o.details["from_tab"] for o in offers if o.name == "Shared tour"] == ["Top picks and Best reviewed"]


def test_the_sites_own_filters_in_the_address_are_ticked_on_the_page_read_and_kept_after_the_sort_changed():
    rec = booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 15, None, True, None, 9.0, True)
    data = json.loads(run_script(page(), rec, url=rec["url"].replace("lisbon.html", "lisbon.en-gb.html")))
    want = ["filter_by_label=free_cancellation", "filter_by_label=skip_the_line", "filter_by_min_rating=4.5"]
    assert data["ok"] is True and data["form"]["labels"] == ["free_cancellation", "skip_the_line"] and data["form"]["min_rating"] == ["4.5"] and data["filters_on"] == want and data["filters_on_end"] == want
    _, _, problems, _, notes = convert_one(data, rec)
    assert problems == [] and any("filter_by_label=free_cancellation" in n for n in notes)


def test_a_page_with_filters_the_trip_did_not_ask_for_is_stopped_by_the_script_and_the_converter():
    url = RECIPE["url"].replace("lisbon.html", "lisbon.en-gb.html") + "&filter_by_label[]=free_cancellation"
    data = json.loads(run_script(page(), url=url))
    assert data["ok"] is False and 'labels ["free_cancellation"] instead of []' in data["error"]


def test_the_real_script_reads_only_the_first_cards_of_each_sort_when_the_window_is_small():
    data = json.loads(run_script(page(), booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 10)))
    assert data["ok"] is True and len(data["rows"]) == 20 and [s["read"] for s in data["sorts"]] == [10, 10] and data["sorts"][0]["cards_on_page"] == 15


def test_the_real_script_stops_when_the_address_is_not_the_one_asked():
    url = "https://www.booking.com/attractions/searchresults/pt/porto.en-gb.html?date_from=2027-03-08&date_to=2027-03-08&adults=3&selected_currency=INR&sort_by=lowest_price"
    data = json.loads(run_script(page(), url=url))
    assert data["ok"] is False and "place \"pt/porto\" instead of \"pt/lisbon\"" in data["error"] and "day \"2027-03-08\" instead of \"2027-03-07\"" in data["error"] and "currency \"INR\" instead of \"EUR\"" in data["error"] and "sort \"lowest_price\" instead of null" in data["error"]


def test_the_real_script_says_it_could_not_read_a_page_with_no_cards_or_a_human_check_or_no_best_reviewed_choice_or_a_card_it_does_not_know():
    silent = json.loads(run_script("<html><body><h1>Loading</h1></body></html>", tries=2))
    assert silent["ok"] is False and "never say there are none" in silent["error"]
    check = json.loads(run_script("<html><body>Please verify you are human</body></html>"))
    assert check["ok"] is False and "human check" in check["error"] and "do not work around" in check["error"]
    nobox = json.loads(run_script(page(radios=("trending", "lowest_price"))))
    assert nobox["ok"] is False and 'no "Best reviewed" choice' in nobox["error"]
    odd = json.loads(run_script(page(total=15, price_html="Sold out"), booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 1)))
    assert odd["ok"] is True and odd["rows"] == [] and len(odd["unparsed"]) == 2


def test_a_price_in_another_currency_reaches_the_converter_and_is_refused_there():
    usd = json.loads(run_script(page(total=15, sym="$"), booking_attractions_recipe("pt/lisbon", "Lisbon", DAY, 2, 2)))
    off, _, problems, _, _ = convert_one(usd)
    assert off == [] and any("not euro" in p for p in problems)
