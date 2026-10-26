"""CP (Comboios de Portugal) trains: ask-first, the address, the converter (real cards read on 23 Oct 2026)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.sites import convert_all
from myt_mcp.sites.cp_trains import cp_trains_recipe

pytestmark = pytest.mark.anyio


def _answer(rows, **head):
    base = {"ok": True, "route": "Lisboa Oriente › Coimbra-B", "date_text": "November 3, 2026", "class_text": "2nd Class / Tourist", "no_results": False, "cards_total": len(rows), "viewport": 1200,
            "run": "r", "rows_read": len(rows), "page_url": "https://www.cp.pt/en/resultado-pesquisa", "rows": rows}
    base.update(head)
    return json.dumps(base)


IC = {"pax": "3", "dur": "01h52", "cls": "2nd Class / Tourist", "dep": "06:39", "arr": "08:31", "service": "Intercidades", "code": "IC", "price": 40.5, "promo": True, "was": 66.6, "note": "Promo ticket: Non refundable", "changes": None}
AP = {"pax": "3", "dur": "01h36", "cls": "2nd Class / Tourist", "dep": "07:09", "arr": "08:45", "service": "Alfa Pendular", "code": "AP", "price": 81.3, "promo": False, "was": None, "note": None, "changes": None}


def _expect(**kw):
    return {"expect": {"origin": "Lisboa Oriente", "destination": "Coimbra-B", "day": "2026-11-03", "passengers": 3, "class": "2nd", "earliest": None, "refundable": False, "leg": "Lisboa Oriente to Coimbra-B, 03 Nov 2026", **kw}}


def test_the_address_carries_stations_date_passengers_and_class():
    r = cp_trains_recipe("Lisboa Oriente", "Coimbra-B", date(2026, 11, 3), 3)
    assert r["url"] == "https://www.cp.pt/en/resultado-pesquisa?passageiros=3&selectedClass=2&startDate=2026-11-03&departureStation=94-31039&arrivalStation=94-36004"
    assert "cp.pt" in r["script"] and "Select departure" in r["script"]
    unknown = cp_trains_recipe("Faro", "Coimbra-B", date(2026, 11, 3), 3)
    assert unknown["needs_station_ids"] == ["Faro"] and "departureStation" in " ".join(unknown["steps"])
    with pytest.raises(ValueError):
        cp_trains_recipe("Lisboa Oriente", "Coimbra-B", date(2026, 11, 3), 0)
    # 26 Oct 2026: Lisboa Santa Apolonia was missing, and an id given as the station was refused
    sa = cp_trains_recipe("Lisboa Santa Apolónia", "Porto Campanhã", date(2026, 11, 20), 2)
    assert sa["url"].endswith("startDate=2026-11-20&departureStation=94-30007&arrivalStation=94-2006")
    by_id = cp_trains_recipe("94-30007", "94-2006", date(2026, 11, 20), 2)
    assert by_id["url"] == sa["url"] and "needs_station_ids" not in by_id
    assert "94-30007" in " ".join(cp_trains_recipe("Faro", "Porto", date(2026, 11, 20))["steps"]) or "id" in " ".join(cp_trains_recipe("Faro", "Porto", date(2026, 11, 20))["steps"])


def test_group_prices_promo_and_non_refundable_are_read_from_the_cards():
    offers, sources, problems, _, notes = convert_all([{"site": "cp_trains", "result": _answer([IC, AP]), "url": "u"}], _expect())
    assert not problems and [o.price_total for o in offers] == [40.5, 81.3]
    assert offers[0].flexible is False and "without promotion 66.6" in offers[0].price_basis and offers[1].flexible is None
    assert "whole group (3 passengers)" in offers[1].price_basis and any("children" in n for n in notes)


def test_earliest_departure_and_refundable_only_mark_rows_as_not_fitting():
    offers = convert_all([{"site": "cp_trains", "result": _answer([IC, AP]), "url": "u"}], _expect(earliest="07:00", refundable=True))[0]
    assert [o.fits for o in offers] == [False, True]          # the promo is before 07:00 and non-refundable


def test_a_wrong_day_or_passenger_count_is_refused_and_a_far_date_is_told_plainly():
    wrong_day = convert_all([{"site": "cp_trains", "result": _answer([AP], date_text="November 4, 2026"), "url": "u"}], _expect())[2]
    assert any("not November 3, 2026" in p for p in wrong_day)
    two = dict(AP, pax="2")
    assert any("priced for 2 passenger" in p for p in convert_all([{"site": "cp_trains", "result": _answer([two]), "url": "u"}], _expect())[2])
    far = convert_all([{"site": "cp_trains", "result": _answer([], no_results=True, date_text="March 3, 2027"), "url": "u"}], _expect(day="2027-03-03"))[2]
    assert len(far) == 1 and "not_checked" in far[0] and "not available" in far[0]


def test_direct_only_marks_a_much_slower_train_as_probably_a_change_and_says_it_is_a_guess():
    slow = dict(IC, dur="04h10", dep="09:39", arr="13:49", price=20.0)
    offers, _, _, _, notes = convert_all([{"site": "cp_trains", "result": _answer([IC, AP, slow]), "url": "u"}], _expect(direct_only=True))
    assert [o.fits for o in offers] == [True, True, False] and "probably a change" in offers[2].details["changes"] and "looks like a direct" in offers[0].details["changes"]
    assert any("does not say which trains change" in n for n in notes)
    assert all(o.fits for o in convert_all([{"site": "cp_trains", "result": _answer([IC, AP, slow]), "url": "u"}], _expect())[0])


async def test_the_tool_asks_first_then_returns_the_address(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example-tunnel.trycloudflare.com")
    settings = Settings(mcp_secret="s" * 24)
    async with Client(create_server(settings, Services(settings))) as c:
        first = json.loads((await c.call_tool("cp_trains_recipe", {"origin": "Lisboa Oriente", "destination": "Coimbra-B", "day": "2026-11-03", "passengers": 3})).content[0].text)
        assert first["ok"] is False and len(first["ask_operator"]) == 4 and first["searched"] is False
        out = json.loads((await c.call_tool("cp_trains_recipe", {"origin": "Lisboa Oriente", "destination": "Coimbra-B", "day": "2026-11-03", "passengers": 3, "first_class": False, "earliest": "07:00", "refundable": False, "direct_only": False})).content[0].text)
    assert out["url"].startswith("https://www.cp.pt/en/resultado-pesquisa?passageiros=3") and out["ingest"] and "Departing after 07:00 (operator)" in out["filters_used"]


def test_a_station_given_as_cps_own_id_is_checked_by_the_address_not_by_name():
    route = "Lisboa Santa Apolónia › Porto Campanhã"
    by_id = convert_all([{"site": "cp_trains", "result": _answer([AP], route=route), "url": "u"}], _expect(origin="94-30007", destination="94-2006"))
    assert not by_id[2]
    wrong = convert_all([{"site": "cp_trains", "result": _answer([AP], route=route), "url": "u"}], _expect(origin="Faro", destination="Coimbra-B"))[2]
    assert any("not Faro to Coimbra-B" in p for p in wrong)          # a station given by name is still compared with the page
