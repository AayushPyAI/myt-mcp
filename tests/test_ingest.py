"""Script answers that go from the page straight to the server (myt_mcp/ingest.py)."""

from __future__ import annotations

import json
import re

import pytest
from mcp import Client
from starlette.testclient import TestClient

from myt_mcp.app import create_http_app, create_server
from myt_mcp.config import Settings
from myt_mcp.ingest import MAX_BODY, MAX_POSTS, STORE, IngestStore
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio
BASE = "https://example-tunnel.trycloudflare.com"


def _row(fare, total, bag, ref, fi):
    return {"fi": fi, "flights": "TP1865", "op": None, "from": "LIS", "to": "PDL", "dep": "2027-03-08 22:10", "arr": "2027-03-08 23:45", "stops": 0, "mins": 95, "via": "", "fare": fare, "cabin": "Economy",
            "total": total, "adt": total / 3, "chd": total / 3, "inf": None, "bag": bag, "ref": ref, "seats": 9}


def _answer(rows):
    return {"ok": True, "currency": "EUR", "pax": {"ADT": 2, "CHD": 1}, "not_available": False, "flights_total": 1, "offset": 0, "flights_in_part": 1, "page_direct": 1, "page_connecting": 0,
            "run": "abc", "rows_read": len(rows), "page_url": "https://booking.flytap.com/booking/flights", "rows": rows}


def test_the_store_accepts_one_run_once_known_and_refuses_the_rest():
    store = IngestStore()
    token = store.new_run("tap", {"expect": {}}, ["Direct flights only (operator)"])
    assert store.accept("nope", b"{}")[0] == 404
    assert store.accept(token, b"not json")[0] == 400 and store.accept(token, b"[1]")[0] == 400
    assert store.accept(token, b"x" * (MAX_BODY + 1))[0] == 413
    assert store.accept(token, json.dumps(_answer([_row("A", 1, 1, 1, 0)])).encode()) == (200, {"ok": True, "rows": 1, "chars": len(json.dumps(_answer([_row("A", 1, 1, 1, 0)])))})
    for _ in range(MAX_POSTS):
        status, _ = store.accept(token, b"{}")
    assert status == 429


def test_a_run_without_an_answer_is_reported_not_guessed():
    store = IngestStore()
    token = store.new_run("sata", {})
    items, problems = store.items([token, "unknown-token"])
    assert items == [] and len(problems) == 2 and "no answer arrived" in problems[0] and "unknown or expired" in problems[1]


async def test_a_recipe_answer_carries_the_ingest_address_and_compose_answer_reads_the_posted_rows(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    settings = Settings(mcp_secret="s" * 24)
    server = create_server(settings, Services(settings))
    async with Client(server) as c:
        r = await c.call_tool("tap_recipe", {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "direct_only": True, "checked_bag": True, "refundable": True})
        out = json.loads(r.content[0].text)
        token = out["ingest"]
        m = re.search(r"const INGEST = (\{.*?\});", out["script"])
        assert m and json.loads(m.group(1)) == {"url": f"{BASE}/ingest/{token}", "token": token} and "WISHES" not in out["script"].split("const INGEST")[0]
        assert "runs" in out["finish"] and "typeof INGEST" in out["script"]
        # the page posts its whole answer (the script's emit does this); here the test client plays the page
        web = TestClient(create_http_app(settings, server))
        rows = [_row("DISCNEW", 209.04, 0, 0, 0), _row("PLUSNEW", 374.04, 1, 1, 1)]
        resp = web.post(f"/ingest/{token}", content=json.dumps(_answer(rows)), headers={"Content-Type": "text/plain"})
        assert resp.status_code == 200 and resp.json()["rows"] == 2 and resp.headers["access-control-allow-origin"] == "*"
        assert web.options(f"/ingest/{token}").status_code == 200
        # compose_answer is given ONLY the run id: no rows, no wishes; the server judges the fares by the wishes it issued itself
        composed = await c.call_tool("compose_answer", {"kind": "flights", "runs": [token]})
        d = composed.structured_content
        assert d["ok"] is True, d
        text = d["answer"]
        assert "Direct flights only (operator)" in text and "PLUSNEW" in text
        best = next(line for line in text.splitlines() if line.startswith("| Best fit"))
        assert "PLUSNEW" in best and "DISCNEW" not in best                # the fare with no bag and no refund is not the best fit


async def test_compose_answer_refuses_a_run_that_never_arrived(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("sata_recipe", {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "direct_only": True, "checked_bag": True, "refundable": True})).content[0].text)
        r = await c.call_tool("compose_answer", {"kind": "flights", "runs": [out["ingest"]]})
        d = r.structured_content
        assert d["ok"] is False and "no answer arrived" in d["problems"][0] and "Do not type any row" in d["next"]


async def test_without_a_public_address_the_old_way_is_kept(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("ALLOWED_HOSTS", "127.0.0.1:*,localhost:*")
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("tap_recipe", {"origin": "LIS", "destination": "OPO", "day": "2027-03-08", "adults": 2, "direct_only": True, "checked_bag": False, "refundable": False})).content[0].text)
    assert "ingest" not in out and "const WISHES" in out["script"] and "no public address" in out["warning"]


def test_the_script_posts_to_the_server_and_hands_the_model_only_a_receipt():
    from pathlib import Path
    js = (Path(__file__).parent.parent / "myt_mcp" / "sites" / "emit.js").read_text(encoding="utf-8")
    assert "INGEST.url" in js and "mode: 'no-cors'" in js and "do not read or type any row" in js and "received === false" in js


def test_the_public_address_comes_from_the_tunnel_host_when_it_is_not_set_explicitly(monkeypatch):
    from myt_mcp.sites import public_base
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("ALLOWED_HOSTS", "127.0.0.1:*,localhost:*,father-post.trycloudflare.com")
    assert public_base() == "https://father-post.trycloudflare.com"
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://other.example.com/")
    assert public_base() == "https://other.example.com"
    monkeypatch.delenv("PUBLIC_BASE_URL"); monkeypatch.setenv("ALLOWED_HOSTS", "127.0.0.1:*,localhost:*")
    assert public_base() == ""


async def test_sata_is_read_by_the_server_in_its_own_browser_and_stored_as_a_run(monkeypatch):
    import myt_mcp.sites as sites

    answer = {"ok": True, "currency": "EUR", "searched": {"from": "LIS", "to": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "infants": 0, "directions": 1}, "no_flight_found": False,
              "flights_total": 1, "offset": 0, "flights_in_part": 1, "run": "r", "rows_read": 1, "page_url": "https://book.azoresairlines.pt/booking/flights",
              "rows": [{"fi": 0, "flights": "S4121", "from": "LIS", "to": "PDL", "dep": "2027-03-08 06:00", "arr": "2027-03-08 07:30", "mins": 150, "stops": 0, "tech": 0, "via": "", "fare": "FLX_DOMESTIC_BF", "cabin": "ECONOMY",
                        "total": 283.04, "adt": 195.36, "chd": 87.68, "inf": None, "nadt": 2, "nchd": 1, "ninf": 0, "carry": "8 kg", "bag": "1 x 23 kg", "change": "Penalty €25", "refund": "Penalty €65"}]}
    seen = {}

    class FakeBrowser:
        async def run(self, origin, url, action):
            seen["origin"], seen["url"] = origin, url

            class Page:
                async def goto(self, *a, **k): seen["goto"] = True
                async def wait_for_url(self, *a, **k): seen["waited"] = True
                async def evaluate(self, js): seen["js"] = js; return json.dumps(answer)
            return await action(Page())

    monkeypatch.setattr(sites, "_SERVER_BROWSER", FakeBrowser())
    monkeypatch.setattr(sites, "MIN_SECONDS_BETWEEN_READS", 0)
    monkeypatch.setenv("BROWSER_CDP_URL", "http://127.0.0.1:9333")
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("sata_recipe", {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "direct_only": True, "checked_bag": True, "refundable": True})).content[0].text)
        assert out["ok"] is True and out["received"] is True and out["rows_read"] == 1 and "script" not in out
        assert "const LOCAL_RETURN = true;" in seen["js"] and seen["origin"] == "https://book.azoresairlines.pt" and seen["waited"]
        d = (await c.call_tool("compose_answer", {"kind": "flights", "runs": [out["ingest"]]})).structured_content
        assert d["ok"] is True, d
        assert "FLX_DOMESTIC_BF" in d["answer"] and "supplier id 46627" in d["answer"]


async def test_a_page_the_server_cannot_read_is_reported_not_typed(monkeypatch):
    import myt_mcp.sites as sites

    class FakeBrowser:
        async def run(self, origin, url, action):
            class Page:
                async def goto(self, *a, **k): pass
                async def wait_for_url(self, *a, **k): pass
                async def evaluate(self, js): return json.dumps({"ok": False, "error": "SATA shows a human check or refuses the page."})
            return await action(Page())

    monkeypatch.setattr(sites, "_SERVER_BROWSER", FakeBrowser())
    monkeypatch.setattr(sites, "MIN_SECONDS_BETWEEN_READS", 0)
    monkeypatch.setenv("BROWSER_CDP_URL", "http://127.0.0.1:9333")
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("sata_recipe", {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "direct_only": True, "checked_bag": False, "refundable": False})).content[0].text)
    assert out["ok"] is False and "human check" in out["error"] and "not_checked" in out["next"] and "ingest" not in out


def test_a_narrow_window_is_named_instead_of_a_confusing_filter_error():
    from myt_mcp.sites import convert_all
    rows = [{"sort": "Best", "per": 64.0, "total": 192.0, "airlines": "TAP Air Portugal", "from": "LIS", "to": "PDL", "dep": "06:40", "arr": "08:20", "later": None, "direct": True, "duration": "1h 40", "via": None}]
    answer = {"ok": True, "route": ["LIS", "PDL"], "date": "Mon, 8 Mar", "travellers": 3, "cabin": "Economy", "direct_only": False, "filters": {"stops": [], "ticked_extras": [], "unticked_defaults": 0},
              "viewport": 620, "run": "r", "rows_read": 1, "rows": rows}
    problems = convert_all([{"site": "skyscanner", "result": json.dumps(answer), "url": "u"}], {})[2]
    assert len(problems) == 1 and "only 620 px wide" in problems[0] and "zoom the page out" in problems[0]
    wide = dict(answer, viewport=1400)
    assert not any("px wide" in p for p in convert_all([{"site": "skyscanner", "result": json.dumps(wide), "url": "u"}], {})[2])
    tap = {"ok": True, "viewport": 400, "run": "r", "rows_read": 0, "rows": [], "currency": "EUR", "pax": {}, "flights_total": 0}
    assert not any("px wide" in p for p in convert_all([{"site": "tap", "result": json.dumps(tap), "url": "u"}], {})[2])       # TAP does not care about the width


def test_the_honest_reason_a_script_could_not_read_a_page_is_allowed():
    from myt_mcp.compose import NotChecked, validate
    problems = validate("flights", ["Direct flights only (operator)"], [], [NotChecked(name="RateHawk", reason="could not be read: no flight cards (window too narrow)")], [], {}, None)
    assert not any("RateHawk" in p and "allowed reason" in p for p in problems) and not any("RateHawk: the reason" in p for p in problems)


async def test_a_recipe_for_the_operators_chrome_says_to_widen_the_window(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("ratehawk_air_recipe", {"origin": "LIS", "destination": "PDL", "day": "2027-03-08", "adults": 2, "children": 1, "stops": "direct", "checked_bag": True, "cabin": "economy"})).content[0].text)
    assert "1200 px" in out["before_you_run"] and "zoom the page out" in out["before_you_run"] and "innerWidth < 1000" in out["script"]


# ---------- fixes after the all-categories run (23 Oct 2026) ----------

def test_a_long_flights_table_keeps_every_source_and_the_picks_but_not_all_rows():
    from myt_mcp.compose import MAX_ROWS_BY_KIND, Offer, compose
    rows = [Offer(group="LIS to PDL", source=src, name=f"{src} flight {i}", price_total=200 + i * 3 + k * 40, currency="EUR", price_basis="whole group", fits=True, quotable=src != "Skyscanner")
            for k, src in enumerate(["TAP", "SATA", "RateHawk Air", "Skyscanner"]) for i in range(30)]
    from myt_mcp.compose import SourceRead
    reads = [SourceRead(name=n, read=30, of=30, link="https://example.com/" + n.replace(" ", "")) for n in ("TAP", "SATA", "RateHawk Air", "Skyscanner")]
    out = compose("flights", ["Direct flights only (operator)"], reads, [], rows, {}, None, True, "", max_rows=MAX_ROWS_BY_KIND["flights"])
    assert out.get("ok"), out.get("problems")
    text = out["answer"]
    table_rows = [line for line in text.splitlines() if line.startswith("| TAP |") or line.startswith("| SATA |") or line.startswith("| RateHawk Air |") or line.startswith("| Skyscanner |")]
    assert len(table_rows) < 40 and "Showing" in text and "The picks are chosen from all 120" in text
    assert all(any(line.startswith(f"| {s} |") for line in table_rows) for s in ("TAP", "SATA", "RateHawk Air", "Skyscanner"))       # no source drops out of the table


def test_generic_group_rows_join_the_only_named_group():
    from myt_mcp.compose import Offer
    from myt_mcp.tools.compose_answer import merge_default_group
    named = Offer(group="LIS airport -> central Lisbon, 01 Mar 2027", source="Mozio", name="Sedan", price_total=24.79, currency="EUR")
    generic = Offer(group="Transfers", source="RateHawk Transfers", name="Economy", price_total=19.0, currency="EUR")
    merge_default_group([named, generic], [])
    assert generic.group == named.group
    other = Offer(group="LIS airport -> central Lisbon, 05 Mar 2027", source="Kiwitaxi", name="Comfort", price_total=40.0, currency="EUR")
    again = Offer(group="Transfers", source="RateHawk Transfers", name="Economy", price_total=19.0, currency="EUR")
    merge_default_group([named, other, again], [])
    assert again.group == "Transfers"                      # two named groups: nothing is guessed


def test_the_lounge_exit_at_the_flight_time_gets_a_boarding_note():
    from myt_mcp.lounges.parse import summarize_rates
    answer = {"data": {"isAvailable": True, "flightDateTime": "2027-03-01T13:40:00", "loungeEntryDateTime": "2027-03-01T11:40:00", "loungeExitDateTime": "2027-03-01T13:40:00",
                       "tickets": [{"type": "Adult", "price": {"unit": 80, "originalValue": 80, "discount": 0}, "currency": "EUR", "maxQuantity": 9}]}}
    r = summarize_rates(answer, {"adults": 1})
    assert "45 minutes before departure" in r["boarding_note"]
    answer["data"]["loungeExitDateTime"] = "2027-03-01T12:30:00"
    assert "boarding_note" not in summarize_rates(answer, {"adults": 1})


def test_a_car_with_fewer_large_bags_than_asked_does_not_fit():
    from myt_mcp.sites.ratehawk_cars import convert
    row = {"score": "6.8", "company": "sixt", "company_from": "logo file name", "seats": "5", "large_bags": "2", "small_bags": "1", "gearbox": "Automatic", "car": "Renault Clio", "code_class": "EDAR • Economy",
           "pickup_place": "Meeting with an agent", "deposit": 500, "excess": 0, "insurance": "Zero excess", "mileage_fuel": "Unlimited mileage • Fuel policy: Full to full", "extras": [], "price": 224.62, "currency": "EUR",
           "cancellation": "Free cancellation up to 48 hours before pick-up"}
    result = json.dumps({"ok": True, "form": {"pickup": "Joao Paulo II Airport", "dropoff": "Joao Paulo II Airport", "times": ["08:10", "10:00"], "dates": ["5 Mar, Fri", "9 Mar, Tue"], "age_residency": ["26 - 69 years", "Israel"]},
                         "filters_ticked": ["Automatic"], "rows_read": 1, "reached_cap": False, "price_order": "ascending", "rows": [row]})
    offers = convert(result, {"min_seats": 5, "min_large_bags": 3, "automatic": True, "zero_excess": True}, "Cars").offers
    assert offers and offers[0].fits is False
    offers = convert(result, {"min_seats": 5, "min_large_bags": 2, "automatic": True, "zero_excess": True}, "Cars").offers
    assert offers and offers[0].fits is not False


def test_arbitrip_takes_children_in_the_address_and_in_the_room_check():
    from datetime import date
    from urllib.parse import parse_qs, urlparse
    from myt_mcp.sites.arbitrip_hotels import results_url
    url, keys = results_url("PLACE", "CONTRACT", date(2027, 3, 1), date(2027, 3, 5), 2, [8, 5], 4, True, None, None)
    q = parse_qs(urlparse(url).query)
    assert q["guests"] == ["2"] and q["children"] == ["2"] and q["children_ages"] == ["8,5"] and "children_ages" in keys     # found on the real page: ages comma-separated, guests = the adults
    plain, plain_keys = results_url("PLACE", "CONTRACT", date(2027, 3, 1), date(2027, 3, 5), 2, None, 4, True, None, None)
    assert "children" not in parse_qs(urlparse(plain).query) and "children" not in plain_keys


def test_arbitrip_hotels_recipe_no_longer_refuses_children(monkeypatch):
    from datetime import date
    from myt_mcp.sites.arbitrip_hotels import arbitrip_hotels_recipe
    from myt_mcp.sites.arbitrip_rooms import arbitrip_rooms_recipe
    monkeypatch.setenv("ARBITRIP_CONTRACT_ID", "C123")
    out = arbitrip_hotels_recipe("lisbon", date(2027, 3, 1), date(2027, 3, 5), 2, [8], 4, True)
    assert "children_ages=8" in out["url"] and "children_ages" in out["filters_in_url"]
    room = arbitrip_rooms_recipe("lisbon", date(2027, 3, 1), date(2027, 3, 5), 2, None, [8])
    assert room["expect"]["children"] == "1" and room["expect"]["children_ages"] == "8" and "children_ages=8" in room["link_query"]


async def test_ofran_recipe_tells_the_model_to_check_the_agency_login_first(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("ofran_recipe", {"pickup": "Ponta Delgada Airport", "pickup_date": "2027-03-05", "pickup_time": "08:10", "dropoff_date": "2027-03-09", "dropoff_time": "10:00",
                                                              "gearbox": "automatic", "min_seats": 5, "zero_excess": True, "max_total": 500})).content[0].text)
    assert "BEFORE you fill the form" in out["login_check"]["run_first"] and "not_checked" in out["login_check"]["if_false"]


def test_a_cheaper_airline_only_a_comparison_source_lists_is_named_in_the_picks_notes():
    from myt_mcp.compose import Offer, cheaper_unconnected_notes
    rows = [Offer(group="TLV to LIS", source="RateHawk Air", name="El Al 13:40-17:50 LY-375", price_total=1283.42, currency="EUR", fits=True, quotable=True),
            Offer(group="TLV to LIS", source="TAP Air Portugal", name="TP8920 13:40-17:50 operated by El Al", price_total=1372.83, currency="EUR", fits=True, quotable=True),
            Offer(group="TLV to LIS", source="Skyscanner", name="arkia 17:15-21:00 (5 hours 45 minutes)", price_total=531.0, currency="EUR", quotable=False),
            Offer(group="TLV to LIS", source="Skyscanner", name="EL AL Israel Airlines 13:40-17:50 (6 hours 10 minutes)", price_total=1113.0, currency="EUR", quotable=False)]
    notes = cheaper_unconnected_notes("flights", rows)
    assert len(notes) == 1 and "arkia" in notes[0] and "531.00 EUR" in notes[0] and "1,283.42 EUR" in notes[0] and "own website" in notes[0]       # El Al is sold by a connected source: no note for it
    assert cheaper_unconnected_notes("hotels", rows) == []


async def _fake_server_browser(monkeypatch, answer):
    import myt_mcp.sites as sites
    seen = {}

    class FakeBrowser:
        async def run(self, origin, url, action):
            seen["origin"], seen["url"] = origin, url

            class Page:
                async def goto(self, *a, **k): pass
                async def wait_for_url(self, *a, **k): pass
                async def evaluate(self, js): seen["js"] = js; return json.dumps(answer)
            return await action(Page())

    monkeypatch.setattr(sites, "_SERVER_BROWSER", FakeBrowser())
    monkeypatch.setattr(sites, "MIN_SECONDS_BETWEEN_READS", 0)
    monkeypatch.setenv("BROWSER_CDP_URL", "http://127.0.0.1:9333")
    return seen


async def test_cp_and_the_gyg_list_are_read_by_the_server_because_their_pages_refuse_the_post(monkeypatch):
    cp_answer = {"ok": True, "route": "Lisboa Oriente › Coimbra-B", "date_text": "November 3, 2026", "class_text": "2nd Class / Tourist", "no_results": False, "cards_total": 0, "viewport": 1200,
                 "run": "r", "rows_read": 0, "page_url": "https://www.cp.pt/en/resultado-pesquisa", "rows": []}
    seen = await _fake_server_browser(monkeypatch, cp_answer)
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("cp_trains_recipe", {"origin": "Lisboa Oriente", "destination": "Coimbra-B", "day": "2026-11-03", "passengers": 3, "first_class": False, "earliest": "07:00", "refundable": False, "direct_only": False})).content[0].text)
        assert out["ok"] is True and out["ingest"] and "script" not in out and seen["origin"] == "https://www.cp.pt" and "const LOCAL_RETURN = true;" in seen["js"]
        gyg = {"ok": True, "results_total": "144", "query_text": "whale watching ponta delgada", "date_chip": "Mar 7", "header_currency": None, "cards_on_page": 0, "offset": 0, "run": "g", "rows_read": 0,
               "page_url": "https://www.getyourguide.com/s/", "rows": []}
        seen = await _fake_server_browser(monkeypatch, gyg)
        out = json.loads((await c.call_tool("getyourguide_find_recipe", {"query": "whale watching ponta delgada", "day": "2027-03-07", "free_cancellation": False, "max_price": 200, "max_hours": 6})).content[0].text)
        assert out["ok"] is True and out["ingest"] and seen["origin"] == "https://www.getyourguide.com" and "offset=48" in out["more"]


async def test_ratehawk_hotels_are_read_by_the_server_only_when_the_switch_is_on(monkeypatch):
    answer = {"ok": True, "header": "Lisbon: 443 accommodation options available", "sort": "Price (low to high)", "start_page": 1, "pages_read": 1, "price_order": "ascending", "stopped": None,
              "run": "h", "rows_read": 0, "page_url": "https://www.ratehawk.com/hotel/portugal/lisbon/", "rows": []}
    args = {"country": "Portugal", "city": "Lisbon", "check_in": "2027-03-01", "check_out": "2027-03-05", "adults": 2, "children_ages": [8], "breakfast": True, "stars": 4, "budget_per_night": 200,
            "max_distance_km": 1, "free_cancellation": False, "operator_answered": True}
    seen = await _fake_server_browser(monkeypatch, answer)
    monkeypatch.delenv("RATEHAWK_HOTELS_READ_IN_SERVER", raising=False)
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("ratehawk_hotels_recipe", args)).content[0].text)
        assert "script" in out and "origin" not in seen                                   # default: the operator's Chrome (the agency's own login account is not used by the server)
        monkeypatch.setenv("RATEHAWK_HOTELS_READ_IN_SERVER", "1")
        out = json.loads((await c.call_tool("ratehawk_hotels_recipe", args)).content[0].text)
        assert out["ok"] is True and out["ingest"] and seen["origin"] == "https://www.ratehawk.com"      # switched on: the server reads it


async def test_a_source_that_went_through_the_assistant_in_parts_is_named_in_the_answer():
    from tests.test_compose import _part
    settings = Settings(mcp_secret="s" * 24)
    rows = [["Hotel Alfa", "EUR 480", "mid1/alfa/"], ["Hotel Beta", "EUR 520", "mid2/beta/"], ["Hotel Gama", "EUR 560", "mid3/gama/"]]
    async with Client(create_server(settings, Services(settings))) as c:
        r = await c.call_tool("compose_answer", {"kind": "hotels", "site_results": [{"site": "ratehawk_hotels", "result": _part("r1", 1, 1, rows, read=3), "url": "https://www.ratehawk.com/hotel/portugal/lisbon/"}],
                                                 "wishes": {"breakfast": True, "stars_min": 4}, "filters_used": ["Breakfast included (operator)"],
                                                 "not_checked": [{"name": "Arbitrip", "reason": "no browser tool in this chat"}]})
    d = r.structured_content
    assert d["ok"] is True, d
    assert "Passed through the assistant in parts" in d["answer"] and "ratehawk_hotels" in d["answer"]


# ---------- safeguards of the server-side reads ----------

def _answer_ok(rows=()):
    return json.dumps({"ok": True, "run": "r", "rows_read": len(rows), "page_url": "https://example.com/x", "rows": list(rows)})


def _fake(monkeypatch, raws):
    import myt_mcp.sites as sites
    calls = []

    class FakeBrowser:
        async def run(self, origin, url, action):
            class Page:
                async def goto(self, *a, **k): pass
                async def wait_for_url(self, *a, **k): pass
                async def evaluate(self, js):
                    if "Ray ID" in js:
                        return False                    # the block-page check before the script
                    calls.append(url)
                    r = raws.pop(0)
                    if isinstance(r, Exception):
                        raise r
                    return r
            return await action(Page())
    monkeypatch.setattr(sites, "_SERVER_BROWSER", FakeBrowser())
    monkeypatch.setattr(sites, "MIN_SECONDS_BETWEEN_READS", 0)
    return calls


async def test_the_same_page_is_served_from_the_cache_for_ten_minutes(monkeypatch):
    from myt_mcp.sites import read_in_server_browser
    calls = _fake(monkeypatch, [_answer_ok()])
    out = {"script": "await (async () => {\n})()", "wishes": {"expect": {}}, "filters_used": []}
    first = await read_in_server_browser("cp_trains", "https://www.cp.pt", "https://www.cp.pt/a", out)
    second = await read_in_server_browser("cp_trains", "https://www.cp.pt", "https://www.cp.pt/a", out)
    assert first["ok"] and second["ok"] and len(calls) == 1 and "a few minutes ago" in second["how"] and first["ingest"] != second["ingest"]


async def test_a_site_that_shows_a_human_check_is_paused_and_never_worked_around(monkeypatch):
    from myt_mcp.sites import read_in_server_browser
    calls = _fake(monkeypatch, [json.dumps({"ok": False, "error": "CP shows a human check or refuses the page."}), _answer_ok()])
    out = {"script": "await (async () => {\n})()", "wishes": {}, "filters_used": []}
    first = await read_in_server_browser("cp_trains", "https://www.cp.pt", "https://www.cp.pt/a", out)
    again = await read_in_server_browser("cp_trains", "https://www.cp.pt", "https://www.cp.pt/b", out)
    assert first["ok"] is False and again["ok"] is False and "paused" in again["error"] and "block" in again["next"] and len(calls) == 1


async def test_the_hourly_limit_and_a_browser_that_is_not_running_are_reported_not_raised(monkeypatch):
    import myt_mcp.sites as sites
    from myt_mcp.errors import IntegrationError
    out = {"script": "await (async () => {\n})()", "wishes": {}, "filters_used": []}
    _fake(monkeypatch, [IntegrationError("No browser is listening")])
    down = await sites.read_in_server_browser("sata", "https://book.azoresairlines.pt", "https://x/a", out)
    assert down["ok"] is False and "No browser" in down["error"] and "not_checked" in down["next"]
    monkeypatch.setattr(sites, "MAX_READS_PER_HOUR", 2)
    calls = _fake(monkeypatch, [_answer_ok(), _answer_ok()])
    await sites.read_in_server_browser("tapx", "https://x", "https://x/1", out)
    await sites.read_in_server_browser("tapx", "https://x", "https://x/2", out)
    limited = await sites.read_in_server_browser("tapx", "https://x", "https://x/3", out)
    assert limited["ok"] is False and "limit" in limited["error"] and len(calls) == 2


def test_arbitrip_never_reports_more_rows_read_than_the_pages_estimate():
    from myt_mcp.sites import convert_all
    from tests.test_compose import _arb
    rows = [[f"Hotel {i}", "8.6", "Very Good", "824", "Near Liberdade", "(0.9 km from center)", 400 + i * 10, 100 + i] for i in range(15)]
    _, sources, problems, _, notes = convert_all([{"site": "arbitrip_hotels", "result": _arb(rows, approx_total=14, rows_read=15), "url": "u"}], {})
    assert sources[0].read == 15 and sources[0].of == 15 and any("header says about 14" in n for n in notes)


def test_padding_rows_of_an_activity_list_are_left_out_so_a_kayak_is_never_the_cheapest_whale_watching():
    from myt_mcp.sites import convert_all
    from tests.test_compose import _gyf, _gr
    rows = [_gr(1, "Sete Cidades Lake: 2-Seat Kayak Rental", "/ponta-delgada-l1/kayak-t1/", "2 hours", 4.9, 300, 20, []),
            _gr(2, "Whale and Dolphin Watching Trip from Ponta Delgada", "/ponta-delgada-l1/whale-t2/", "3 hours", 4.8, 100, 55, [])]
    exp = {"query": "whale watching ponta delgada", "day": None, "group": "whale", "title_contains": ["whale", "watching", "ponta", "delgada"], "free_cancellation": False, "max_price": 60, "min_rating": None, "max_hours": 3}
    offers, _, problems, _, notes = convert_all([{"site": "getyourguide_find", "result": _gyf(rows), "url": "u"}], {"expect": exp})
    assert [o.name for o in offers] == ["Whale and Dolphin Watching Trip from Ponta Delgada"] and any("left out of the table and the picks" in n for n in notes)


async def test_the_viator_list_is_read_by_the_server_slowly(monkeypatch):
    import myt_mcp.sites as sites
    monkeypatch.setattr(sites, "SITE_MIN_SECONDS", {})
    answer = {"ok": True, "query_text": "whale watching ponta delgada", "results_total": "150", "page": 1, "shown_range": "1-24", "sort": "Featured", "run": "v", "rows_read": 0, "page_url": "https://www.viator.com/searchResults/all", "rows": []}
    seen = await _fake_server_browser(monkeypatch, answer)
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("viator_find_recipe", {"query": "whale watching ponta delgada", "day_label": "7 Mar 2027", "free_cancellation": False, "max_price": 60, "max_hours": 3})).content[0].text)
    assert out["ok"] is True and out["ingest"] and seen["origin"] == "https://www.viator.com" and "page=2" in out["more"]
    assert sites.SITE_MIN_SECONDS == {} and "viator_find" in __import__("importlib").reload(sites).SITE_MIN_SECONDS      # the real setting is 15 s apart for Viator


async def test_a_block_page_pauses_the_site_for_every_process_and_for_a_restart(monkeypatch):
    import myt_mcp.sites as sites
    calls = []

    class FakeBrowser:
        async def run(self, origin, url, action):
            class Page:
                async def goto(self, *a, **k): pass
                async def wait_for_url(self, *a, **k): pass
                async def evaluate(self, js):
                    calls.append(js[:20])
                    return True if "Ray ID" in js else _answer_ok()       # the first evaluate is the block-page check: it says yes
            return await action(Page())
    monkeypatch.setattr(sites, "_SERVER_BROWSER", FakeBrowser())
    monkeypatch.setattr(sites, "MIN_SECONDS_BETWEEN_READS", 0)
    out = {"script": "await (async () => {\n})()", "wishes": {}, "filters_used": []}
    first = await sites.read_in_server_browser("getyourguide_find", "https://www.getyourguide.com", "https://www.getyourguide.com/s/?q=a", out)
    assert first["ok"] is False and "block page" in first["error"] and sites.PAUSE_FILE.exists()
    sites._PAUSED_UNTIL.clear()                                                    # a restart of the server forgets its memory, not the file
    again = await sites.read_in_server_browser("getyourguide_find", "https://www.getyourguide.com", "https://www.getyourguide.com/s/?q=b", out)
    assert again["ok"] is False and "paused" in again["error"] and sites.paused_minutes("getyourguide_find") > 0 and len(calls) == 1
    other = await sites.read_in_server_browser("cp_trains", "https://www.cp.pt", "https://www.cp.pt/x", {**out})
    assert "paused" not in str(other.get("error", ""))                              # the pause is per site


def test_a_page_that_blocks_posts_gets_a_script_with_no_post_address_but_the_recipe_is_still_tracked(monkeypatch):
    import myt_mcp.sites as sites
    from myt_mcp.ingest import STORE
    monkeypatch.setattr(sites, "public_base", lambda: "https://example.trycloudflare.com")
    head = "await (async () => {\n"
    for site in ("getyourguide_find", "viator_activity", "ratehawk_hotels"):
        out = sites.embed_wishes({"script": head + "return 1;", "wishes": {"free_cancellation": True}, "filters_used": ["x"]}, site)
        assert "INGEST" not in out["script"] and "trycloudflare" not in out["script"] and "const WISHES" in out["script"] and "ingest" not in out and "parts" in out["how_the_answer_comes_back"]
    assert {r.site for r in STORE.issued(0)} == {"getyourguide_find", "viator_activity", "ratehawk_hotels"}
    posting = sites.embed_wishes({"script": head + "return 1;", "wishes": {}}, "arbitrip_hotels")
    assert "const INGEST" in posting["script"] and posting["ingest"]
