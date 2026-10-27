"""Booking.com attractions, ONE activity, integration: the REAL script runs in a real browser (Playwright's Chromium) on a page built like the real one (27 Oct 2026): the dates row (the chosen one has
aria-pressed="true"), "Select time" radios with a "Show more" button that doubles them, "Ticket / Non-refundable", one stepper per kind of ticket (a label, the price, an <input type=range> with a hidden
decorative button) and the page's own "Total ... Includes taxes and charges" that follows the counts. Nothing leaves the machine."""

import json
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.booking_attraction import booking_attraction_recipe
from tests.test_booking_attraction import DAY, SLUG, URL

KINDS = [("Adult (age 13-64)", 29.90), ("Child (age 3-12)", 17.70), ("Senior (age 65+)", 19.90), ("Infant (age 0-2)", 0.0)]


def page(kinds=KINDS, unavailable=False, chosen="Sun 7 Mar", ticket="Non-refundable", sym="€", box=True, first_change_sticks_at_one=False) -> str:
    cfg = {"kinds": [[k, p] for k, p in kinds], "sym": sym, "clamp": first_change_sticks_at_one}
    steppers = "".join(f'<div data-testid="ticket-selector-stepper"><label for="k{i}">{k}</label><div>{sym}&nbsp;{p:.2f}</div><button aria-hidden="true" disabled></button>'
                       f'<input id="k{i}" type="range" min="0" max="100" step="1" value="0"><button aria-hidden="true"></button></div>' for i, (k, p) in enumerate(kinds))
    slots = "".join(f'<div><input type="radio" name="slot" id="s{i}" data-testid="timeslot-option" {"checked" if i == 0 else ""}><label for="s{i}">{10 + i // 2}:{"00" if i % 2 == 0 else "30"}</label></div>' for i in range(9))
    days = "".join(f'<button data-testid="datepicker-item" aria-pressed="{"true" if d == chosen else "false"}">{d}</button>' for d in dict.fromkeys(("Sat 6 Mar", "Sun 7 Mar", "Mon 8 Mar", chosen)) if d)
    body = ("<p>Your selected date is unavailable, please choose another one</p>" if unavailable else
            f'<div>Select time</div><div id="slots">{slots}</div><button data-testid="timeslots-show-more-cta">Show more</button><div>Ticket</div><div>{ticket}</div><div>How many tickets?</div>{steppers}'
            f'<div data-testid="ticket-selector-total">Total<br>{sym} 0<br>Includes taxes and charges</div><button data-testid="select-ticket">Next</button>')
    if not box:
        return "<html><head><meta charset='utf-8'></head><body><h1>Loading</h1></body></html>"
    return f"""<html><head><meta charset='utf-8'></head><body><h1>Tickets into The Lisbon Oceanarium</h1>
<div data-testid="inline-ticket-config"><h3>Tickets and prices</h3><div>Search ticket availability by date</div>{days}{body}</div>
<section><h2>What's included</h2><div>Admission</div></section><section><h2>Additional information</h2><div>Please bring your ticket with you to the attraction.</div></section><p>Operated by Musement</p>
<script>
const CFG = {json.dumps(cfg)};
const more = document.querySelector('[data-testid="timeslots-show-more-cta"]');
if (more) more.addEventListener('click', () => {{ document.getElementById('slots').insertAdjacentHTML('beforeend', Array.from({{ length: 9 }}, (_, i) => '<div><input type="radio" name="slot" id="t' + i + '" data-testid="timeslot-option"><label for="t' + i + '">' + (14 + Math.floor(i / 2)) + ':' + (i % 2 ? '30' : '00') + '</label></div>').join('')); more.remove(); }});
function update() {{
  let sum = 0; document.querySelectorAll('input[type=range]').forEach((r, i) => {{ sum += Number(r.value) * CFG.kinds[i][1]; }});
  const el = document.querySelector('[data-testid="ticket-selector-total"]'); if (el) el.innerHTML = 'Total<br>' + CFG.sym + ' ' + sum.toFixed(2) + '<br>Includes taxes and charges';
}}
document.querySelectorAll('input[type=range]').forEach((r) => {{ let first = true; r.addEventListener('input', () => setTimeout(() => {{ if (CFG.clamp && first && Number(r.value) > 1) r.value = '1'; first = false; update(); }}, 200)); }});
</script></body></html>"""


def run_script(page_html: str, recipe: dict | None = None, url: str | None = None, tries: int | None = None) -> str:
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = recipe or booking_attraction_recipe(URL, DAY, 2, [], "Oceanarium")
    script = "async () => { const LOCAL_RETURN = true; " + (f"const BOX_TRIES = {tries}; " if tries else "") + recipe["script"].replace("await (async", "return (async", 1) + " }"

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
            page_.goto(url or recipe["url"].replace(f"{SLUG}.html", f"{SLUG}.en-gb.html"))      # the site's own redirect keeps the values and changes the path
            page_.wait_for_load_state("domcontentloaded")
            out = page_.evaluate(script)
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out


def convert_one(data: dict, recipe: dict):
    return convert_all([{"site": "booking_attraction", "result": json.dumps(data), "url": recipe["url"], "wishes": {"expect": recipe["expect"]}}], {"expect": recipe["expect"]})


def test_the_real_script_sets_two_adults_reads_the_pages_own_total_the_times_and_the_ticket_wording():
    rec = booking_attraction_recipe(URL, DAY, 2, [], "Oceanarium")
    data = json.loads(run_script(page(), rec))
    assert data["ok"] is True and data["title"] == "Tickets into The Lisbon Oceanarium" and data["chosen_day"] == "Sun 7 Mar" and data["operated_by"] == "Musement" and data["includes"] == "Admission" and data["unavailable"] is None
    assert data["form"] == {"slug": SLUG, "date": "2027-03-07", "currency": "EUR"} and data["steppers"] == 4
    r = data["rows"][0]
    assert r["ticket"] == "Non-refundable" and len(r["times"]) == 18 and r["times"][0] == "10:00" and r["times"][-1] == "18:00" and r["time_chosen"] == "10:00"
    assert [(k["label"], k["count"], k["wanted"]) for k in r["kinds"]] == [("Adult (age 13-64)", 2, 2), ("Child (age 3-12)", 0, 0), ("Senior (age 65+)", 0, 0), ("Infant (age 0-2)", 0, 0)]
    assert r["total"] == 59.8 and r["symbol"] == "€" and r["taxes"] is True and r["computed"] == pytest.approx(59.8)
    offers, _, problems, _, _ = convert_one(data, rec)
    assert problems == [] and offers[0].price_total == 59.8 and "2 x Adult (age 13-64) at 29.90" in offers[0].price_basis


def test_a_child_is_put_in_the_ticket_kind_whose_age_range_holds_the_age_and_the_total_follows():
    rec = booking_attraction_recipe(URL, DAY, 2, [8, 1], "Oceanarium")
    data = json.loads(run_script(page(), rec))
    assert [(k["label"], k["count"]) for k in data["rows"][0]["kinds"]] == [("Adult (age 13-64)", 2), ("Child (age 3-12)", 1), ("Senior (age 65+)", 0), ("Infant (age 0-2)", 1)]
    assert data["rows"][0]["total"] == pytest.approx(77.5)
    offers, _, problems, _, _ = convert_one(data, rec)
    assert problems == [] and "4 travellers" in offers[0].price_basis


def test_a_date_the_page_says_is_unavailable_is_returned_as_it_is():
    rec = booking_attraction_recipe(URL, DAY, 2, [], "Oceanarium")
    data = json.loads(run_script(page(unavailable=True, chosen=""), rec))
    assert data["ok"] is True and data["rows"] == [] and data["unavailable"].startswith("Your selected date is unavailable")
    offers, _, problems, _, notes = convert_one(data, rec)
    assert offers == [] and problems == [] and any("never 'sold out'" in n for n in notes)


def test_the_real_script_stops_on_another_activity_or_another_date_or_a_child_no_kind_holds_or_a_page_without_the_box_or_a_human_check():
    rec = booking_attraction_recipe(URL, DAY, 2, [], "Oceanarium")
    other = json.loads(run_script(page(), rec, url=f"https://www.booking.com/attractions/pt/pr999-other.en-gb.html?date=2027-03-07&selected_currency=EUR"))
    assert other["ok"] is False and "this is the page of \"pr999-other\"" in other["error"]
    wrong = json.loads(run_script(page(chosen="Tue 10 Nov"), rec))
    assert wrong["ok"] is False and "shows Tue 10 Nov, not Sun 7 Mar" in wrong["error"]
    kid = json.loads(run_script(page(kinds=[("Adult (age 13-64)", 29.90)]), booking_attraction_recipe(URL, DAY, 2, [8], "Oceanarium")))
    assert kid["ok"] is False and "no ticket kind on the page holds a traveller of age 8" in kid["error"]
    nobox = json.loads(run_script(page(box=False), rec, tries=2))
    assert nobox["ok"] is False and "ticket box is not on the page" in nobox["error"]
    check = json.loads(run_script("<html><body>Please verify you are human</body></html>", rec))
    assert check["ok"] is False and "human check" in check["error"] and "do not work around" in check["error"]


def test_a_total_in_another_currency_reaches_the_converter_and_is_refused_there():
    rec = booking_attraction_recipe(URL, DAY, 2, [], "Oceanarium")
    data = json.loads(run_script(page(sym="$"), rec))
    offers, _, problems, _, _ = convert_one(data, rec)
    assert offers == [] and any("not euro" in p for p in problems)


def test_a_page_that_keeps_the_first_change_at_one_ticket_is_set_again_until_it_holds_the_count():
    rec = booking_attraction_recipe(URL, DAY, 2, [], "Oceanarium")
    data = json.loads(run_script(page(first_change_sticks_at_one=True), rec))
    assert [(k["label"], k["count"], k["wanted"]) for k in data["rows"][0]["kinds"]][0] == ("Adult (age 13-64)", 2, 2) and data["rows"][0]["total"] == pytest.approx(59.8)
    _, _, problems, _, _ = convert_one(data, rec)
    assert problems == []
