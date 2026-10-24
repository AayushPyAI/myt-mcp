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


def test_a_sources_line_with_links_that_hold_dates_is_not_a_table_row():
    line = ("Sources: TAP (TLV-LIS): https://booking.flytap.com/booking/flights?depDate=10.12.2026&x=1 | TAP (LIS-TLV): https://booking.flytap.com/booking/flights?depDate=17.12.2026 | "
            "RateHawk Air (TLV-LIS): https://www.ratehawk.com/air/?route=LISa17122026TLVa | RateHawk Air (LIS-TLV): https://www.ratehawk.com/air/?route=x")
    assert row_problems(line, "flights", ComposedStore()) == []
    row = "| TAP | TP8920 13:40-17:50 | direct | 794.50 EUR | whole group |"
    assert "no compose_answer result" in row_problems(row, "flights", ComposedStore())[0]


def test_a_checked_bag_the_row_cannot_show_is_not_a_pick_and_the_note_names_the_cheapest_of_them():
    from myt_mcp.compose import Offer, bag_unconfirmed
    mk = lambda src, price, bag: Offer(group="g", source=src, name="x", price_total=price, currency="EUR", price_basis="b", fits=True, details={"checked_bag": bag})
    rows = [mk("TAP Air Portugal", 980.42, "yes"), mk("El Al", 846.0, "not shown on the list (fare rules on elal.com)"), mk("El Al", 900.0, "not shown on the list")]
    note = bag_unconfirmed(rows)
    assert [o.fits for o in rows] == [True, False, False] and "El Al 846.00 EUR" in note and "not picks" in note
    assert bag_unconfirmed([mk("TAP Air Portugal", 1.0, "yes"), mk("RateHawk", 2.0, "no")]) is None


def test_both_legs_of_a_source_keep_their_own_link_in_the_sources_line():
    from datetime import date
    from myt_mcp.sites import convert_all
    from myt_mcp.sites.tap import tap_recipe
    from tests.test_compose import TAP_REAL, _tap
    out = tap_recipe("FLR", "LIS", date(2027, 3, 6), 2, 1)["expect"]
    back = dict(out, leg="LIS to FLR, 13 Mar 2027")
    item = lambda e, url: {"site": "tap", "result": _tap(TAP_REAL), "url": url, "wishes": {"expect": e}}
    one = convert_all([item(out, "https://t/out")], {})[1][0]
    two = convert_all([item(out, "https://t/out"), item(back, "https://t/back")], {})[1][0]
    assert one.link == "https://t/out" and two.link == f"{out['leg']}: https://t/out; LIS to FLR, 13 Mar 2027: https://t/back"


def test_a_source_with_one_link_per_leg_passes_compose_and_a_home_page_link_does_not():
    from myt_mcp.compose import Offer, SourceRead, compose
    offer = Offer(group="TLV to LIS", source="TAP", name="TP8920", price_total=794.5, currency="EUR", price_basis="whole group", fits=True, details={"checked_bag": "yes"})
    legs = "TLV to LIS, 10 Dec 2026: https://booking.flytap.com/booking/flights?depDate=10.12.2026; LIS to TLV, 17 Dec 2026: https://booking.flytap.com/booking/flights?depDate=17.12.2026"
    run = lambda link: compose("flights", ["Direct (operator)"], [SourceRead(name="TAP", read=1, of=1, link=link)], [], [offer], {}, None, True, "")
    assert run(legs)["ok"] is True and run("https://booking.flytap.com/booking/flights?depDate=10.12.2026")["ok"] is True
    for bad in ("https://www.flytap.com/", "TLV to LIS: https://www.flytap.com/; LIS to TLV: https://booking.flytap.com/x?a=1", "no link at all", None):
        assert any("not a home page" in p for p in run(bad)["problems"]), bad
