"""CP (Comboios de Portugal) trains: ask-first, the address, the station list and the converter, on the shape of CP's own journeys answer (read live 5 Nov 2026)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.sites import convert_all
from myt_mcp.sites.cp_trains import cp_trains_recipe, station_id, station_list, station_matches, train_codes

pytestmark = pytest.mark.anyio


def _answer(rows, **head):
    base = {"ok": True, "origin": {"code": "94-31039", "name": "Lisboa Oriente"}, "destination": {"code": "94-36004", "name": "Coimbra-B"}, "day": "2026-11-03", "passengers": 3, "cls": 2, "no_results": False,
            "trips_total": len(rows), "ms": 800, "notices": [], "viewport": 1200, "run": "r", "rows_read": len(rows), "page_url": "https://www.cp.pt/en", "rows": rows}
    base.update(head)
    return json.dumps(base)


def _trip(dep="06:39", arr="08:31", dur="01h52", services=("Intercidades",), n=0, normal=66.6, promo=40.5, promo_limits=("NON_REFUNDABLE",), saleable=True, **kw):
    row = {"dep": dep, "arr": arr, "dur": dur, "changes_n": n, "services": list(services), "codes": ["IC"], "trains": [521], "cls": 2, "price_normal": normal, "price_promo": promo, "pp_normal": round(normal / 3, 2) if normal else None,
           "pp_promo": round(promo / 3, 2) if promo else None, "promo_limits": list(promo_limits) if promo is not None else [], "normal_limits": [], "price_types": [1, 4, 100, 104], "saleable": saleable, "bike": 1}
    row.update(kw)
    return row


IC = _trip()
AP = _trip("07:09", "08:45", "01h36", ("Alfa Pendular",), normal=81.3, promo=None)


def _expect(**kw):
    return {"expect": {"origin": "Lisboa Oriente", "destination": "Coimbra-B", "origin_code": "94-31039", "destination_code": "94-36004", "day": "2026-11-03", "passengers": 3, "class": "2nd", "earliest": None,
                       "refundable": False, "leg": "Lisboa Oriente to Coimbra-B, 03 Nov 2026", **kw}}


def test_the_address_carries_stations_date_passengers_and_class_and_the_script_carries_the_request():
    r = cp_trains_recipe("Lisboa Oriente", "Coimbra-B", date(2026, 11, 3), 3)
    assert r["url"] == "https://www.cp.pt/en/resultado-pesquisa?passageiros=3&selectedClass=2&startDate=2026-11-03&departureStation=94-31039&arrivalStation=94-36004"
    assert "__REQUEST__" not in r["script"] and '"origin_code": "94-31039"' in r["script"] and '"passengers": 3' in r["script"] and "/fe-config.json" in r["script"] and "journeys" in r["script"]
    assert r["expect"]["origin_code"] == "94-31039" and r["expect"]["destination_code"] == "94-36004"
    with pytest.raises(ValueError):
        cp_trains_recipe("Lisboa Oriente", "Coimbra-B", date(2026, 11, 3), 0)
    # 26 Oct 2026: Lisboa Santa Apolonia was missing, and an id given as the station was refused
    sa = cp_trains_recipe("Lisboa Santa Apolónia", "Porto Campanhã", date(2026, 11, 20), 2)
    assert sa["url"].endswith("startDate=2026-11-20&departureStation=94-30007&arrivalStation=94-2006")
    by_id = cp_trains_recipe("94-30007", "94-2006", date(2026, 11, 20), 2)
    assert by_id["url"] == sa["url"] and "needs_station_ids" not in by_id
    first = cp_trains_recipe("Lisboa Oriente", "Porto Campanha", date(2026, 11, 20), 2, first_class=True)
    assert "selectedClass=1" in first["url"] and '"first_class": true' in first["script"]


def test_every_cp_station_is_known_by_name_alias_or_id_and_an_unclear_name_returns_its_candidates():
    assert len(station_list()) == 460 and ("94-31039", "Lisboa Oriente") in station_list() and ("71-37606", "Badajoz") in station_list()
    assert station_id("Faro") == "94-73007" and station_id("braga") == "94-29157" and station_id("Évora") == "94-80006" or station_id("Evora") is not None
    assert station_id("Lisbon") == "94-31039" and station_id("Porto") == "94-2006" and station_id("Santa Apolónia") == "94-30007" and station_id("Coimbra") == "94-36004"
    assert station_id("94-30007") == "94-30007" and station_id("71-37606") == "71-37606" and station_id("Atlantis") is None
    assert len(station_matches("Santa")) > 3 and station_id("Santa") is None                              # several stations: never a guess
    unclear = cp_trains_recipe("Santa", "Faro", date(2026, 11, 3))
    assert unclear["needs_station_ids"] == ["Santa"] and any("Santa Cita (94-" in c for c in unclear["station_candidates"]["Santa"]) and "url" not in unclear
    none = cp_trains_recipe("Atlantis", "Faro", date(2026, 11, 3))
    assert none["needs_station_ids"] == ["Atlantis"] and none["station_candidates"]["Atlantis"] == []


def test_group_prices_promo_and_non_refundable_are_read_from_the_service():
    offers, sources, problems, _, notes = convert_all([{"site": "cp_trains", "result": _answer([IC, AP]), "url": "u"}], _expect())
    assert not problems and [o.price_total for o in offers] == [40.5, 81.3]
    assert offers[0].flexible is False and "without promotion 66.6" in offers[0].price_basis and offers[1].flexible is None
    assert "whole group (3 adults)" in offers[1].price_basis and any("children" in n for n in notes)
    assert offers[0].details["conditions"].startswith("promo ticket: non refundable") and offers[0].details["per_person"] == 13.5 and offers[1].details["conditions"].startswith("full fare")
    assert offers[0].name == "Intercidades 06:39-08:31 (01h 52)" and offers[0].details["changes"] == "direct (CP lists no change)" and offers[0].details["trains"] == "521"


def test_earliest_departure_is_judged_and_refundable_only_switches_a_promo_to_the_full_fare_and_never_makes_it_a_pick():
    early = convert_all([{"site": "cp_trains", "result": _answer([IC, AP]), "url": "u"}], _expect(earliest="07:00"))[0]
    assert [o.fits for o in early] == [False, True]
    refundable = convert_all([{"site": "cp_trains", "result": _answer([IC, AP]), "url": "u"}], _expect(refundable=True))[0]
    assert [o.price_total for o in refundable] == [66.6, 81.3] and [o.fits for o in refundable] == [None, True]      # the full fare is shown, but its refund terms are unconfirmed: never "meets every wish"
    assert "full fare (the promo fare is 40.5 EUR, non refundable)" in refundable[0].price_basis and refundable[0].flexible is None
    assert refundable[0].unconfirmed == ["refund terms"] and refundable[1].unconfirmed == []
    only_promo = convert_all([{"site": "cp_trains", "result": _answer([_trip(normal=None)]), "url": "u"}], _expect(refundable=True))[0]
    assert only_promo[0].fits is False and only_promo[0].price_total == 40.5          # no full fare listed: the promo cannot meet it


def test_a_wrong_day_station_class_or_passenger_count_is_refused_and_a_far_date_is_told_plainly():
    problems = lambda **h: convert_all([{"site": "cp_trains", "result": _answer([AP], **h), "url": "u"}], _expect())[2]
    assert any("for 2026-11-04, not 2026-11-03" in p for p in problems(day="2026-11-04"))
    assert any("'94-2006', not '94-36004'" in p for p in problems(destination={"code": "94-2006", "name": "Porto Campanha"}))
    assert any("2 passenger(s), not 3" in p for p in problems(passengers=2)) and any("class 1, not the 2nd class" in p for p in problems(cls=1))
    far = convert_all([{"site": "cp_trains", "result": _answer([], no_results=True, day="2027-03-03", calendar_limit_days=60), "url": "u"}], _expect(day="2027-03-03"))[2]
    assert len(far) == 1 and "not_checked" in far[0] and "not available" in far[0] and "sells tickets 60 days ahead (its own rule) and this date is" in far[0]
    near = convert_all([{"site": "cp_trains", "result": _answer([], no_results=True, day=date.today().isoformat(), calendar_limit_days=60), "url": "u"}], _expect(day=date.today().isoformat()))[2]
    assert len(near) == 1 and "only some weeks ahead (or the stations have no train that day)" in near[0] and "60 days ahead" not in near[0]
    assert "script reported: CP" in convert_all([{"site": "cp_trains", "result": json.dumps({"ok": False, "error": "CP's journeys service answered 401"}), "url": "u"}], _expect())[2][0]
    assert any("row count does not match" in p for p in problems(trips_total=5))


def test_direct_only_uses_the_changes_cp_lists_and_never_assumes_a_train_is_direct():
    """26 Oct 2026: a Regional + Alfa Pendular train of 3h03 looked direct by its journey time; CP's own answer lists its changes (transferCount), so nothing is guessed."""
    direct = _trip("07:09", "08:45", "01h36", ("Alfa Pendular",), normal=81.3, promo=None)
    change = _trip("09:45", "12:48", "03h03", ("Regional", "Alfa Pendular"), n=1, normal=60.0, promo=None)
    unknown = _trip("10:45", "12:48", "02h03", ("Alfa Pendular",), n=None, normal=70.0, promo=None)
    offers, _, problems, _, notes = convert_all([{"site": "cp_trains", "result": _answer([direct, change, unknown]), "url": "u"}], _expect(direct_only=True))
    assert not problems and [o.fits for o in offers] == [True, False, False]
    assert offers[0].details["changes"] == "direct (CP lists no change)" and offers[1].details["changes"] == "1 change: Regional + Alfa Pendular" and offers[1].name.startswith("Regional + Alfa Pendular 09:45-12:48")
    assert offers[2].details["changes"].startswith("not shown") and not any("only LOOK direct" in n for n in notes)
    anything = convert_all([{"site": "cp_trains", "result": _answer([change]), "url": "u"}], _expect())[0]
    assert anything[0].fits is True          # changes are fine when direct was not asked


def test_a_train_cp_does_not_sell_online_and_its_notices_are_said():
    offers, _, _, _, notes = convert_all([{"site": "cp_trains", "result": _answer([_trip(saleable=False)], notices=["Oeste line: replacement bus service on some trains"]), "url": "u"}], _expect())
    assert "NOT sold online (CP's own flag): ask CP" in offers[0].details["conditions"] and any("Oeste line" in n for n in notes)


def test_a_latest_departure_keeps_only_the_morning_trains_and_a_missing_time_cannot_fit():
    morning, evening, night = _trip("07:09"), _trip("15:30", "18:00"), _trip("22:30", "01:43")
    offers = convert_all([{"site": "cp_trains", "result": _answer([morning, evening, night]), "url": "u"}], _expect(latest="12:00"))[0]
    assert [o.fits for o in offers] == [True, False, False]
    nodep = convert_all([{"site": "cp_trains", "result": _answer([_trip(dep=None)]), "url": "u"}], _expect(latest="12:00"))[0]
    assert nodep[0].fits is False
    window = convert_all([{"site": "cp_trains", "result": _answer([_trip("06:00"), morning]), "url": "u"}], _expect(earliest="07:00", latest="12:00"))[0]
    assert [o.fits for o in window] == [False, True]
    with pytest.raises(ValueError, match="latest"):
        cp_trains_recipe("Lisboa Oriente", "Coimbra-B", date(2026, 11, 3), 3, latest="noon")


async def test_the_tool_asks_first_then_returns_the_address(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example-tunnel.trycloudflare.com")
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        first = json.loads((await c.call_tool("cp_trains_recipe", {"origin": "Lisboa Oriente", "destination": "Coimbra-B", "day": "2026-11-03", "passengers": 3})).content[0].text)
        assert first["ok"] is False and len(first["ask_operator"]) == 4 and first["searched"] is False
        out = json.loads((await c.call_tool("cp_trains_recipe", {"origin": "Lisboa Oriente", "destination": "Coimbra-B", "day": "2026-11-03", "passengers": 3, "first_class": False, "earliest": "07:00", "refundable": False, "direct_only": False})).content[0].text)
        unclear = json.loads((await c.call_tool("cp_trains_recipe", {"origin": "Santa", "destination": "Faro", "day": "2026-11-03", "passengers": 2, "first_class": False, "refundable": False, "direct_only": False, "operator_answered": True})).content[0].text)
    assert out["url"].startswith("https://www.cp.pt/en/resultado-pesquisa?passageiros=3") and "window.__mytParts" in out["how_the_answer_comes_back"] and "Departing after 07:00 (operator)" in out["filters_used"]      # cp.pt does not let its page post to this server: the Chrome fallback returns its rows in parts
    assert unclear["needs_station_ids"] == ["Santa"] and unclear["station_candidates"]["Santa"]


def test_children_cannot_be_priced_so_the_answer_says_every_passenger_is_an_adult_fare_and_the_rules_and_the_time_filter_are_said():
    offers, _, _, _, notes = convert_all([{"site": "cp_trains", "result": _answer([IC, AP], calendar_limit_days=60, window_sent={"startTime": "08:00", "endTime": "14:00", "limitType": 2}, window_extra=1), "url": "u"}], _expect())
    text = " ".join(notes)
    assert "prices every passenger at the ADULT fare" in text and "children's and other discounts cannot be shown" in text and "sells tickets 60 days ahead" in text
    assert "time filter was also asked (departures 08:00-14:00): it added 1 train(s)" in text and "still judges every departure time itself" in text


def test_a_time_wish_is_sent_to_the_script_as_a_window_and_no_wish_sends_none():
    r = cp_trains_recipe("Lisboa Oriente", "Coimbra-B", date(2026, 11, 3), 3, earliest="08:00", latest="12:00")
    assert '"window": {"earliest": "08:00", "latest": "12:00"}' in r["script"]
    assert '"window": null' in cp_trains_recipe("Lisboa Oriente", "Coimbra-B", date(2026, 11, 3), 3)["script"]
    assert '"window": {"earliest": null, "latest": "12:00"}' in cp_trains_recipe("Lisboa Oriente", "Coimbra-B", date(2026, 11, 3), 3, latest="12:00")["script"]


def test_the_names_an_operator_uses_for_train_types_become_cps_codes_and_an_unknown_one_is_refused():
    assert train_codes(["Alfa Pendular", "intercity", "Regional", "urban", "International", "ic", "INT", "Internacionais"]) == ["AP", "IC", "R", "U", "IN"] and train_codes(None) == [] and train_codes([]) == []
    with pytest.raises(ValueError, match="train type 'steam'"):
        train_codes(["steam"])
    r = cp_trains_recipe("Lisboa Oriente", "Porto Campanha", date(2026, 11, 25), 2, train_types=["alfa pendular", "international"])
    assert '"services": ["AP", "IN"]' in r["script"] and r["expect"]["train_types"] == ["AP", "IN"]          # CP's code for International is IN (INT is unknown to it and ignored)


def test_a_return_day_is_in_the_script_the_expectation_and_the_legs_groups_and_a_return_before_the_outward_is_refused():
    r = cp_trains_recipe("Lisboa Oriente", "Porto Campanha", date(2026, 11, 25), 2, return_day=date(2026, 11, 27), back_earliest="10:00")
    assert '"return_day": "2026-11-27"' in r["script"] and '"back_window": {"earliest": "10:00", "latest": null}' in r["script"]
    assert r["expect"]["return_day"] == "2026-11-27" and r["expect"]["back_leg"] == "Porto Campanha to Lisboa Oriente, 27 Nov 2026" and r["expect"]["leg"] == "Lisboa Oriente to Porto Campanha, 25 Nov 2026"
    assert '"return_day": null' in cp_trains_recipe("Lisboa Oriente", "Porto Campanha", date(2026, 11, 25), 2)["script"]
    with pytest.raises(ValueError, match="return day"):
        cp_trains_recipe("Lisboa Oriente", "Porto Campanha", date(2026, 11, 25), 2, return_day=date(2026, 11, 24))
    with pytest.raises(ValueError, match="need a return day"):
        cp_trains_recipe("Lisboa Oriente", "Porto Campanha", date(2026, 11, 25), 2, back_latest="12:00")
    with pytest.raises(ValueError, match="back_earliest"):
        cp_trains_recipe("Lisboa Oriente", "Porto Campanha", date(2026, 11, 25), 2, return_day=date(2026, 11, 27), back_earliest="soon")


def test_the_returned_legs_are_judged_with_their_own_times_and_a_wrong_return_day_is_refused():
    out_leg, back_leg = _trip("07:09"), _trip("15:30", "18:00")
    back_leg["leg"] = "back"
    out_leg["leg"] = "out"
    exp = _expect(earliest="07:00")["expect"] | {"return_day": "2026-11-05", "back_leg": "Coimbra-B to Lisboa Oriente, 05 Nov 2026", "back_latest": "12:00"}
    result = _answer([out_leg, back_leg], return_day="2026-11-05", out_total=1, back_total=1)
    offers, _, problems, _, _ = convert_all([{"site": "cp_trains", "result": result, "url": "u"}], {"expect": exp})
    assert not problems and [o.group for o in offers] == [exp["leg"], exp["back_leg"]] and [o.fits for o in offers] == [True, False]          # the return leaves at 15:30: after the return's own latest 12:00
    wrong = convert_all([{"site": "cp_trains", "result": _answer([out_leg], return_day="2026-11-06"), "url": "u"}], {"expect": exp})[2]
    assert any("return day 2026-11-06, not 2026-11-05" in p for p in wrong)


def test_a_train_type_wish_keeps_only_trains_made_of_those_types_and_says_so():
    ic, ap = _trip(services=("Intercidades",), codes=["IC"]), _trip("07:09", "08:45", "01h36", ("Alfa Pendular",), codes=["AP"], normal=81.3, promo=None)
    mixed = _trip("09:45", "12:48", "03h03", ("Intercidades", "Regional"), n=1, codes=["IC", "R"], normal=60.0, promo=None)
    exp = _expect()["expect"] | {"train_types": ["AP", "IC"]}
    offers, _, _, _, notes = convert_all([{"site": "cp_trains", "result": _answer([ic, ap, mixed], services_sent=["IC", "AP"]), "url": "u"}], {"expect": exp})
    assert [o.fits for o in offers] == [True, True, False]
    text = " ".join(notes)
    assert "Train types asked: Alfa Pendular, Intercidades. CP's own filter was used (it keeps only trains made of those types alone" in text and "a connection with another type is not listed" in text and "A train of another type does not fit." in text
    intl = convert_all([{"site": "cp_trains", "result": _answer([ic]), "url": "u"}], {"expect": _expect()["expect"] | {"train_types": ["IN"]}})
    assert [o.fits for o in intl[0]] == [False] and "Train types asked: International" in " ".join(intl[4])


def _leg_trip(leg, dep, arr, **kw):
    row = _trip(dep, arr, "01h30", **kw)
    row["leg"] = leg
    return row


def test_a_same_day_return_is_paired_a_return_train_that_leaves_before_you_can_be_back_does_not_fit():
    outs = [_leg_trip("out", "06:00", "08:00"), _leg_trip("out", "09:00", "11:00")]
    backs = [_leg_trip("back", "08:10", "10:00"), _leg_trip("back", "11:10", "13:00"), _leg_trip("back", "11:20", "13:00")]
    exp = _expect(earliest="08:30")["expect"] | {"return_day": "2026-11-03", "back_leg": "Coimbra-B to Lisboa Oriente, 03 Nov 2026"}
    result = _answer(outs + backs, return_day="2026-11-03", min_wait_minutes=15, out_total=2, back_total=3)
    offers = convert_all([{"site": "cp_trains", "result": result, "url": "u"}], {"expect": exp})[0]
    assert [o.fits for o in offers[:2]] == [False, True]          # the 06:00 outward misses the 08:30 earliest
    assert [o.fits for o in offers[2:]] == [False, False, True]          # earliest fitting outward arrives 11:00: a return leaving at 11:10 is 10 minutes after, 11:20 is 20
    assert "NOT a fit for a same-day return: it leaves before you can be back: the earliest outward train arrives 11:00 and CP's rule is 15 minutes" in offers[2].details["conditions"]
    none_fit = convert_all([{"site": "cp_trains", "result": result, "url": "u"}], {"expect": exp | {"earliest": "23:00"}})[0]
    assert all(o.fits is False for o in none_fit[2:]) and "no outward train that meets the wishes arrives early enough" in none_fit[2].details["conditions"]
    other_day = convert_all([{"site": "cp_trains", "result": _answer(outs + backs, return_day="2026-11-04", min_wait_minutes=15), "url": "u"}], {"expect": exp | {"return_day": "2026-11-04"}})[0]
    assert [o.fits for o in other_day[2:]] == [True, True, True]          # another day: no pairing


def test_the_bicycle_and_wheelchair_flags_and_a_changed_station_count_are_said():
    offers, _, _, _, notes = convert_all([{"site": "cp_trains", "result": _answer([_trip(bike=1, mobility=0)], stations_total=470), "url": "u"}], _expect())
    assert offers[0].details["bicycle_wheelchair"] == "bicycle yes, wheelchair no" and any("CP now lists 470 stations and the server knows 460" in n for n in notes)
    quiet = convert_all([{"site": "cp_trains", "result": _answer([_trip()], stations_total=460), "url": "u"}], _expect())[4]
    assert not any("CP now lists" in n for n in quiet)


@pytest.mark.anyio
async def test_a_station_name_nothing_matches_makes_the_server_read_cps_list_once_and_use_it(monkeypatch):
    import myt_mcp.sites.cp_trains as cp
    live = [(c, n) for c, n in cp.station_list()] + [("94-99999", "Nova Estacao")]
    calls = []

    async def fake_eval(origin, url, js):
        calls.append(url)
        return json.dumps([[c, n] for c, n in live])
    monkeypatch.setattr("myt_mcp.sites.server_eval", fake_eval)
    monkeypatch.setattr(cp, "_LIVE", None)
    monkeypatch.setattr(cp, "_LAST_REFRESH", 0.0)
    settings = Settings(mcp_secret="s" * 24)
    args = {"origin": "Nova Estacao", "destination": "Faro", "day": "2026-11-25", "passengers": 2, "first_class": False, "refundable": False, "direct_only": False, "operator_answered": True}
    async with Client(create_server(settings, Services(settings))) as c:
        out = json.loads((await c.call_tool("cp_trains_recipe", args)).content[0].text)
        again = json.loads((await c.call_tool("cp_trains_recipe", {**args, "origin": "Atlantis"})).content[0].text)
    assert "departureStation=94-99999" in json.dumps(out) and len(calls) == 1          # found after one read of CP's own list
    assert again["needs_station_ids"] == ["Atlantis"] and len(calls) == 1          # an unknown name does not read it again within the hour
    monkeypatch.setattr(cp, "_LIVE", None)
    assert cp.station_id("Nova Estacao") is None
    short = json.dumps([["94-1", "x"]])

    async def bad_eval(origin, url, js):
        return short
    monkeypatch.setattr("myt_mcp.sites.server_eval", bad_eval)
    monkeypatch.setattr(cp, "_LAST_REFRESH", 0.0)
    assert await cp.refresh_stations() is False and cp._LIVE is None          # a list that looks wrong (fewer than 300 stations) is never used


def test_a_train_cp_lists_with_no_price_is_shown_without_one_and_is_never_a_pick():
    """5 Nov 2026: the Celta trains Porto Campanha - Vigo-Guixar come with no basePrices and saleableOnline false; they were dropped and the answer said 'none returned an option'."""
    celta = _trip("08:10", "11:44", "03h34", ("Internacionais",), codes=["IN"], normal=None, promo=None, saleable=False, price_normal=None, price_promo=None)
    exp = _expect()["expect"] | {"train_types": ["IN"]}
    offers, sources, problems, _, notes = convert_all([{"site": "cp_trains", "result": _answer([celta]), "url": "u"}], {"expect": exp})
    assert not problems and len(offers) == 1 and offers[0].price_total is None and offers[0].quotable is False and offers[0].unconfirmed == ["price"]
    assert offers[0].price_basis == "no price in CP's search: not sold online" and "ask CP" in offers[0].details["conditions"] and offers[0].fits is None
    assert any("1 train(s) with no price" in n and "Celta" in n for n in notes) and sources[0].read == 1


@pytest.mark.anyio
async def test_server_eval_opens_the_page_in_the_servers_browser_and_returns_the_scripts_text(monkeypatch):
    """5 Nov 2026: the first version of the helper used BrowserSession without importing it; only a run that does not mock the browser class shows it."""
    import myt_mcp.browser as browser
    import myt_mcp.sites as sites

    class Page:
        async def goto(self, url, wait_until=None, timeout=None):
            self.url = url

        async def evaluate(self, js):
            return json.dumps([[js, self.url]])

    class FakeSession:
        def __init__(self, url):
            self.url = url

        async def run(self, origin, url, action):
            return await action(Page())
    monkeypatch.setattr(browser, "BrowserSession", FakeSession)
    monkeypatch.setattr(sites, "_SERVER_BROWSER", None)
    monkeypatch.setenv("BROWSER_CDP_URL", "http://127.0.0.1:9333")
    assert json.loads(await sites.server_eval("https://www.cp.pt", "https://www.cp.pt/en", "() => 1")) == [["() => 1", "https://www.cp.pt/en"]]
    monkeypatch.setenv("BROWSER_CDP_URL", "")
    monkeypatch.setattr(sites, "_SERVER_BROWSER", None)
    assert await sites.server_eval("https://www.cp.pt", "https://www.cp.pt/en", "() => 1") is None          # no server browser: nothing is tried
