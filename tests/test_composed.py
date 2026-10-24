"""check_answer compares the draft's price rows with what compose_answer built (a retyped or changed row is reported)."""

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.composed import COMPOSED, ComposedStore, row_problems
from myt_mcp.config import Settings
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

ANSWER = ("| Source | Option | Capacity | Price | Basis |\n|---|---|---|---|---|\n"
          "| RateHawk Transfers | Business Minivan: Mercedes-Benz V-Class or a similar one | up to 7 people / 7 bags | 40.00 EUR | per vehicle, one way |\n"
          "| Kiwitaxi | Comfort (Sedan comfort for 4 passengers) | 3 / 4 | 40.00 EUR | per vehicle |\n")


def store_with(text: str, kind: str = "transfers") -> ComposedStore:
    store = ComposedStore()
    store.remember(kind, text)
    return store


def test_the_servers_own_rows_pass_even_when_the_table_is_pasted_with_tabs_or_bold():
    assert row_problems(ANSWER, "transfers", store_with(ANSWER)) == []
    tabs = "RateHawk Transfers\tBusiness Minivan: Mercedes-Benz V-Class or a similar one\tup to 7 people / 7 bags\t40.00 EUR\tper vehicle, one way"
    assert row_problems(tabs, "transfers", store_with(ANSWER)) == []
    assert row_problems(ANSWER.replace("Kiwitaxi", "**Kiwitaxi**"), "transfers", store_with(ANSWER)) == []


def test_a_retyped_vehicle_name_is_named_and_the_answer_is_sent_back():
    changed = ANSWER.replace("Mercedes-Benz V-Class", "Toyota Alphard")
    problems = row_problems(changed, "transfers", store_with(ANSWER))
    assert len(problems) == 1 and "typed or changed by hand" in problems[0] and "toyota alphard" in problems[0] and "exactly as written" in problems[0]


def test_price_rows_with_no_composed_answer_on_the_server_are_refused_but_text_without_rows_is_not():
    assert "no compose_answer result" in row_problems(ANSWER, "transfers", ComposedStore())[0]
    assert row_problems("I found nothing: Aspire has no lounge here.", "lounges", ComposedStore()) == []
    assert row_problems(ANSWER, "cars", store_with(ANSWER, "transfers"))[0].startswith("the draft has price rows but no compose_answer")


def test_an_old_answer_is_forgotten_after_three_hours(monkeypatch):
    import myt_mcp.composed as composed
    store = store_with(ANSWER)
    now = composed.time.time()
    monkeypatch.setattr(composed.time, "time", lambda: now + 3 * 3600 + 1)
    assert store.recent("transfers") == []


async def test_compose_answer_remembers_its_answer_and_check_answer_catches_a_changed_row():
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        row = {"group": "LIS lounges", "source": "LoungePair", "name": "ANA Lounge, Terminal 1", "price_total": 19.0, "currency": "EUR", "price_basis": "'from' price PER PERSON", "quotable": False,
               "details": {"terminal": "Terminal 1"}, "link": "https://www.loungepair.com/at/LIS/x/"}
        composed = (await c.call_tool("compose_answer", {"kind": "lounges", "offers": [row], "filters_used": ["Airport LIS (operator)"],
                                                          "sources_read": [{"name": "LoungePair", "read": 1, "of": 1, "link": row["link"]}]})).structured_content
        assert composed["ok"] and COMPOSED.recent("lounges")
        ok = (await c.call_tool("check_answer", {"draft": composed["answer"], "kind": "lounges"})).structured_content
        assert not any("typed or changed" in m for m in ok["missing"])
        retyped = composed["answer"].replace("19.00 EUR", "38.00 EUR")
        bad = (await c.call_tool("check_answer", {"draft": retyped, "kind": "lounges"})).structured_content
    assert bad["ok"] is False and any("typed or changed by hand" in m and "38.00 eur" in m for m in bad["missing"])
