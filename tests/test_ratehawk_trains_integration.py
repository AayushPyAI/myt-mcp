"""RateHawk trains recipe, read from the page's own data.

The REAL script runs in a real browser (Playwright's Chromium) on a ratehawk.com/railway results page that serves what the real site served on 7 Nov 2026: the first offers inside an inline
self.__next_f.push("...") string ({"defaultValue": {"offers": {"one_way": [...]}, "search_id", "next_pagination_token"}}, so the quotes are escaped as on the real page) and a "Load more" button whose
own click asks the page's server action (header next-action, body [{direction, pagination_token, search_id}]) for the next batch and a new token. The script must read the embedded offers, press the page's
own button, take the offers from the page's own answers (it never calls an action itself) and apply the changes and class filters on the loaded offers. Nothing leaves the machine."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import pytest

from myt_mcp.sites import convert_all
from myt_mcp.sites.ratehawk_trains import ratehawk_trains_recipe

DAY = "2026-11-23"


def train(i, legs=1, classes=("standard", "comfort", "premier")):
    h = 6 + i % 14
    route = [{"departure": {"station": "Firenze S.M. Novella" if k == 0 else "Bologna Centrale", "datetime": f"{DAY}T{h:02d}:{k * 20:02d}:00"}, "arrival": {"station": "Roma Termini" if k == legs - 1 else "Bologna Centrale", "datetime": f"{DAY}T{h + 1 + k:02d}:{k * 20 + 10:02d}:00"},
              "train_number": str(9000 + i * 10 + k), "carrier": {"name": "TRENITALIA", "operating_company": "Trenitalia", "brand": "TRENITALIA", "marketing_information": "TRENITALIA_FRECCIAROSSA"}} for k in range(legs)]
    return {"id": f"id-{i}", "supplier": "rail_europe", "departure_city": "Florence", "arrival_city": "Rome", "duration": 95 + 20 * (legs - 1), "full_route": route,
            "prices": {"currency_code": "EUR", "comfort_categories": [{"id": c, "min_price": 40.0 + i + n, "max_price": 100.0 + n} for n, c in enumerate(classes)], "min_price": 40.0 + i, "max_price": 200.0},
            "services": ["wifi", "air_conditioning"], "seat_reservation": False}


# 33 trains: 15 embedded, 13 on the first "Load more", 5 on the second; every 4th has a change, every 3rd has no Premier fare
TRAINS = [train(i, legs=2 if i % 4 == 3 else 1, classes=("standard", "comfort") if i % 3 == 2 else ("standard", "comfort", "premier")) for i in range(33)]
BATCHES = {"tok1": (TRAINS[15:28], "tok2"), "tok2": (TRAINS[28:33], None)}


def page_html(embedded=True, button=True, text="Search for train tickets"):
    dv = {"offers": {"one_way": TRAINS[:15], "return": []}, "search_id": "sid-1", "next_pagination_token": "tok1", "session_id": "sess-1"}
    line = "5bd:" + json.dumps([["$", "$L5c2", None, {"sessionId": "sess-1", "defaultValue": dv}]]) + "\n"
    push = f"self.__next_f = self.__next_f || []; self.__next_f.push([1,{json.dumps(line)}]);" if embedded else ""
    more = """<button id="lm">Load more</button><script>
      let token = 'tok1';
      document.getElementById('lm').addEventListener('click', async () => {
        const r = await fetch(location.pathname + location.search, {method: 'POST', headers: {'accept': 'text/x-component', 'next-action': '56f253f81a96'}, body: JSON.stringify([{direction: 'outbound', pagination_token: token, search_id: 'sid-1'}])});
        const tx = await r.text(); const j = JSON.parse(tx.split('\\n').find((l) => l.startsWith('1:')).slice(2)); token = j.next_pagination_token || null; if (!token) document.getElementById('lm').remove();
      });</script>""" if button else ""
    return f"<html><head><title>Trains</title></head><body><h1>{text}</h1><script>{push}</script>{more}</body></html>"


def run_script(seen=None, html=None, changes="any", train_class=None, offset=0, limit=30, patch_wait=True, status=200):
    sync_api = pytest.importorskip("playwright.sync_api")
    recipe = ratehawk_trains_recipe("Firenze Santa Maria Novella", "Roma Termini", __import__("datetime").date.fromisoformat(DAY), "08:00", 2, changes, train_class, None, None, offset, limit)
    script = "async () => { const LOCAL_RETURN = true; " + recipe["script"].replace("await (async", "return (async", 1) + " }"
    if patch_wait:
        script = script.replace("i < 40 && !dv", "i < 2 && !dv")       # the real wait is 20 s for the page's own data
    state = {}

    def serve(route):
        r = route.request
        u = urlparse(r.url)
        if u.hostname != "www.ratehawk.com" or not u.path.startswith("/railway"):
            route.abort()
        elif r.method == "POST":
            body = json.loads(r.post_data or "[]")[0]
            if seen is not None:
                seen.append({"headers": r.headers, "body": body})
            if status != 200:
                route.fulfill(status=status, content_type="text/plain", body="denied")
                return
            batch, nxt = BATCHES[body["pagination_token"]]
            route.fulfill(status=200, content_type="text/x-component", body='0:["$@1",["x",null]]\n1:' + json.dumps({"offers": {"one_way": batch, "return": []}, "search_id": "sid-1", "next_pagination_token": nxt}) + "\n")
        else:
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html or page_html())
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.route("**/*", serve)
            page.goto(recipe["url"])
            out = page.evaluate(script)
            state["fetch_restored"] = page.evaluate("window.fetch.toString().includes('[native code]')")
            browser.close()
    except Exception as e:      # no browser installed on this machine: not a failure of the recipe
        if "Executable doesn't exist" in str(e) or "playwright install" in str(e):
            pytest.skip(f"Playwright's Chromium is not installed: {e}")
        raise
    return out, recipe, state


def read(out):
    return json.loads(out)


def test_the_script_reads_the_embedded_offers_and_presses_the_pages_own_load_more_only_when_needed():
    seen: list = []
    out, recipe, state = run_script(seen=seen, limit=10)
    data = read(out)
    assert data["ok"] is True and len(data["rows"]) == 10 and seen == [] and data["loaded"] == 15 and data["all_loaded"] is False and state["fetch_restored"] is True      # 15 embedded are enough: no click
    assert data["search"] == {"from": "8306421", "to": "8308409", "date": DAY, "time": "08:00", "adt": "2"} and data["filters"] == {"changes": None, "class": None}
    row = data["rows"][0]
    assert row["id"] == "id-0" and row["legs"][0]["train"] == "9000" and row["legs"][0]["from"] == "Firenze S.M. Novella" and row["legs"][0]["brand"] == "TRENITALIA_FRECCIAROSSA" and row["minutes"] == 95 and row["changes"] == 0
    assert row["classes"][0] == {"id": "standard", "from": 40.0, "to": 100.0} and row["cur"] == "EUR" and row["services"] == ["wifi", "air_conditioning"] and row["rank"] == 1
    seen2: list = []
    data2 = read(run_script(seen=seen2, limit=30)[0])
    assert [s["body"]["pagination_token"] for s in seen2] == ["tok1", "tok2"] and data2["loaded"] == 33 and len(data2["rows"]) == 30 and data2["all_loaded"] is True and data2["matching"] == 33
    assert all(s["headers"]["next-action"] == "56f253f81a96" for s in seen2)                  # the calls are the page's own (its button), with its own action id
    ids = [r["id"] for r in data2["rows"]]
    assert ids == [f"id-{i}" for i in range(30)] and len(set(ids)) == 30                     # embedded first, then each batch in order, no duplicates


def test_the_changes_and_class_filters_are_applied_on_the_loaded_offers_like_the_pages_own_boxes():
    direct = read(run_script(changes="direct", limit=30)[0])
    assert direct["filters"] == {"changes": "Direct route", "class": None} and all(r["changes"] == 0 for r in direct["rows"]) and direct["matching"] == sum(1 for t in TRAINS if len(t["full_route"]) == 1)
    one = read(run_script(changes="one_change", limit=40)[0])
    assert one["matching"] == 33 and any(r["changes"] == 1 for r in one["rows"]) and one["filters"]["changes"] == "Up to 1 change of train"
    premier = read(run_script(train_class="premier", limit=40)[0])
    assert premier["filters"]["class"] == "Premier" and all(any(c["id"] == "premier" for c in r["classes"]) for r in premier["rows"]) and premier["matching"] == sum(1 for t in TRAINS if any(c["id"] == "premier" for c in t["prices"]["comfort_categories"]))


def test_the_window_is_taken_from_the_filtered_list():
    data = read(run_script(offset=15, limit=10)[0])
    assert [r["rank"] for r in data["rows"]] == list(range(16, 26)) and data["offset"] == 15 and [r["id"] for r in data["rows"]] == [f"id-{i}" for i in range(15, 25)]


def test_a_page_without_its_data_and_a_refused_load_more_are_said_not_guessed():
    none = read(run_script(html=page_html(embedded=False))[0])
    assert none["ok"] is False and "has not shown its trains" in none["error"]
    login = read(run_script(html=page_html(text="Log in to RateHawk"))[0])
    assert login["ok"] is False and "never type a password" in login["error"]
    refused = read(run_script(status=403, limit=30)[0])                          # the page's own click got no answer it could use: what was loaded is returned, flagged as not all loaded
    assert refused["ok"] is True and refused["loaded"] == 15 and refused["all_loaded"] is False


def test_the_answer_converts_to_offers_and_a_wrong_search_is_refused():
    out, recipe, _ = run_script(changes="direct", train_class="comfort", limit=10)
    wishes = {"expect": recipe["expect"], "max_total": 60}
    offers, sources, problems, _, notes = convert_all([{"site": "ratehawk_trains", "result": out, "url": recipe["url"]}], wishes)
    assert not problems and len(offers) == 10 and all(o.details["class_fare"].startswith("Comfort") and o.details["changes"] == "Direct" for o in offers) and sources[0].read == 10
    assert offers[0].price_total == 41.0 and offers[0].fits is True and any("loaded" in n for n in notes)
    wrong = dict(recipe["expect"], to_id="1")
    _, _, problems, _, _ = convert_all([{"site": "ratehawk_trains", "result": out, "url": "u"}], {"expect": wrong})
    assert any("to '8308409', not '1'" in p for p in problems)
