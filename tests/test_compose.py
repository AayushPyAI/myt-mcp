"""compose_answer: the answer, the picks and the checks are built by code, from the rows Claude collected."""

import pytest

from myt_mcp.compose import NotChecked, Offer, SourceRead, compose, picks

pytestmark = pytest.mark.anyio

SRC = [SourceRead(name="TAP", read=7, of=7, link="https://booking.flytap.com/booking/flights/deeplink?x=1"),
       SourceRead(name="Skyscanner", read=11, of=108, link="https://www.skyscanner.net/transport/flights/flr/lis/270306/")]


def offers():
    return [Offer(group="FLR -> LIS", source="TAP", name="DISCNEW", price_total=462.9, currency="EUR", fits=False, details={"stops": 0, "checked_bag": False}, supplier="TAP AIR PORTUGAL"),
            Offer(group="FLR -> LIS", source="TAP", name="CLANEW", price_total=567.9, currency="EUR", fits=True, details={"stops": 0, "checked_bag": True}, supplier="TAP AIR PORTUGAL",
                  preferred_reason="departs 12:20, the trip plans 12:10"),
            Offer(group="FLR -> LIS", source="TAP", name="PLUSNEW", price_total=702.9, currency="EUR", fits=True, flexible=True, details={"refund_change": "refundable"}),
            Offer(group="FLR -> LIS", source="Skyscanner", name="Vueling via BCN", price_total=187, currency="GBP", quotable=False, connecting=True)]


def run(**kw):
    args = dict(kind="flights", filters_used=["direct (trip default)", "checked bag (operator)"], sources_read=SRC,
                not_checked=[NotChecked(name="Israir", reason="route not served by the source")], offers=offers(),
                myt_supplier={"TAP AIR PORTUGAL": "yes"}, pickup_time=None, sorted_by_price=True, notes="")
    args.update(kw)
    return compose(**args)


def test_picks_never_recommend_an_option_that_misses_a_wish_and_use_one_currency():
    rows, notes = picks("flights", offers(), True)
    d = {a: (b, c) for a, b, c in rows}
    assert "DISCNEW" in d["Cheapest"][0] and "does NOT meet every wish" in d["Cheapest"][1]
    assert "CLANEW" in d["Best fit"][0] and d["Best fit"][1] == "departs 12:20, the trip plans 12:10"
    assert "PLUSNEW" in d["Most flexible"][0]
    assert "CLANEW" in d["Recommended"][0]                      # not the bag-less DISCNEW
    assert any("GBP" in n for n in notes)                       # the GBP row is shown but not compared


def test_the_answer_has_every_required_line_and_not_shown_for_gaps():
    r = run()
    assert r["ok"] is True
    text = r["answer"]
    assert text.startswith("Sources checked: TAP (7 of 7 read); Skyscanner (11 of 108 read) | Not checked: Israir (route not served by the source)")
    for need in ("Filters used: direct (trip default); checked bag (operator)", "| Cheapest |", "| Best fit |", "| Most flexible |", "| Recommended |",
                 "In MYT supplier? TAP AIR PORTUGAL: yes", "Not shown by the sources:", "Sources: TAP: https://booking.flytap.com", "comparison only"):
        assert need in text, need
    assert "not shown" in text


@pytest.mark.parametrize("change, expected", [
    ({"sources_read": [SourceRead(name="TAP", read=7, of=7, link="https://www.flytap.com/")]}, "not a home page"),
    ({"sources_read": [SourceRead(name="TAP", read=7, link="https://booking.flytap.com/a?b=1")]}, "N of M"),
    ({"not_checked": [NotChecked(name="El Al", reason="skipped for time")]}, "not an allowed reason"),
    ({"not_checked": [NotChecked(name="El Al", reason="you didn't ask")]}, "not an allowed reason"),
    ({"not_checked": [NotChecked(name="El Al", reason="whatever")]}, "must be one of"),
    ({"filters_used": ["direct only"]}, "where it comes from"),
    ({"filters_used": []}, "filters_used is empty"),
    ({"kind": "cars"}, "pickup_time is required"),
])
def test_bad_inputs_are_refused_with_the_exact_fix(change, expected):
    r = run(**change)
    assert r["ok"] is False and any(expected in p for p in r["problems"]), r


def test_an_offer_from_a_source_not_listed_or_without_a_currency_is_refused():
    bad = offers() + [Offer(source="El Al", name="LY385", price_total=300, currency=None)]
    r = run(offers=bad)
    assert r["ok"] is False and any("not in sources_read" in p for p in r["problems"]) and any("without a currency" in p for p in r["problems"])


def test_a_hotel_cheapest_from_a_rating_sorted_list_says_it_is_not_the_cheapest_overall():
    hotels = [Offer(group="Lisbon", source="RateHawk", name="Hostel", price_total=318, currency="EUR"), Offer(group="Lisbon", source="RateHawk", name="Hotel", price_total=538, currency="EUR")]
    rows, _ = picks("hotels", hotels, sorted_by_price=False)
    assert "NOT read" in rows[0][2] and "not the cheapest overall" in rows[0][2]
    assert "NOT read" not in picks("hotels", hotels, sorted_by_price=True)[0][0][2]


async def test_compose_answer_tool_is_registered_and_read_only():
    from mcp import Client

    from myt_mcp.app import create_server
    from myt_mcp.config import Settings

    async with Client(create_server(Settings())) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert "compose_answer" in tools and tools["compose_answer"].annotations.read_only_hint
        r = await c.call_tool("compose_answer", {"kind": "lounges", "filters_used": [], "sources_read": [{"name": "Aspire", "read": 1, "of": 1, "link": "https://www.aspirelounges.com/airports/tlv/"}],
                                                 "not_checked": [], "offers": [{"source": "Aspire", "name": "TLV lounge", "price_total": 160, "currency": "EUR"}]})
        assert not r.is_error and r.structured_content["ok"] is True and "Aspire (1 of 1 read)" in r.structured_content["answer"]
