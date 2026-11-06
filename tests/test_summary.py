"""compose_summary (2 Nov 2026): the final message of a multi-kind answer is built by the server from the answers it composed; the assistant writes nothing of it."""

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.compose import NotChecked, Offer, SourceRead, compose, needs_you
from myt_mcp.composed import COMPOSED, SUMMARIES
from myt_mcp.config import Settings
from myt_mcp.summary import build_summary

pytestmark = pytest.mark.anyio

HOTEL = dict(stars="4", score="7.6", reviews="966", distance_from_centre="1.8 km", meal="Breakfast incl.", cancellation="Free cancellation", room_bed="Standard double room")


def _hotels(extra_not_checked=None, notes=""):
    offers = [Offer(group="Lisbon, 7-12 Mar 2027", source="RateHawk", name="Czar Lisbon Hotel", price_total=365, currency="EUR", quotable=True, fits=True, details=dict(HOTEL), link="https://x/czar"),
              Offer(group="Lisbon, 7-12 Mar 2027", source="RateHawk", name="Neya Lisboa", price_total=453, currency="EUR", quotable=True, fits=True, details={**HOTEL, "score": "8.2", "reviews": "2,010"}, link="https://x/neya")]
    return compose("hotels", ["4+ stars (operator)", "at most 1000 EUR in all (assumed by the assistant)"], [SourceRead(name="RateHawk", read=2, of=2, link="https://www.ratehawk.com/hotel/?q=lisbon"),
                                                                                                     SourceRead(name="Arbitrip", read=1, of=1, link="https://arbitrip.test/lisbon")],
                   extra_not_checked or [], offers, {"RateHawk": "yes"}, None, True, notes)


def test_compose_keeps_a_structured_summary_and_never_returns_it_to_the_chat_text():
    out = _hotels(notes="Source narrowed by a filter the operator did not ask for: RateHawk (at most 1000 EUR in all). Rows outside it were never listed. A long unrelated sentence about the layout of the table.")
    assert out["ok"] and out["summary"]["groups"][0]["picks"] and out["summary"]["sources"].startswith("Sources checked: RateHawk (2 of 2 read)") and "summary" not in out["answer"]


def test_the_summary_copies_picks_filters_labels_and_cautions_and_names_what_was_not_searched():
    SUMMARIES.clear()
    SUMMARIES.remember("hotels", "5 nights in Lisbon, central, around 4 stars", _hotels(notes="Source narrowed by a filter the operator did not ask for: RateHawk (at most 1000 EUR in all). Rows outside it were never listed. Unrelated layout remark.")["summary"])
    out = build_summary(SUMMARIES.recent(), "5 nights in Lisbon, central, around 4 stars", ["hotels", "cars"])
    text = out["answer"]
    assert out["ok"] and out["kinds"] == ["hotels"] and out["not_searched"] == ["cars"]
    assert "## Hotels" in text and "Sources checked: RateHawk (2 of 2 read)" in text and "| Cheapest | RateHawk: Czar Lisbon Hotel - 365.00 EUR" in text
    assert "at most 1000 EUR in all (assumed by the assistant)" in text and "4+ stars (operator)" in text and "Source narrowed by a filter the operator did not ask for" in text and "Unrelated layout remark" not in text
    assert "What the operator asked (their own words): 5 nights in Lisbon, central, around 4 stars" in text and "Not searched in this conversation: Cars" in text
    assert text.index("Sources: RateHawk: https://www.ratehawk.com") > text.index("## Hotels")
    SUMMARIES.clear()
    assert build_summary(SUMMARIES.recent())["ok"] is False


def test_a_login_or_block_is_the_first_line_of_the_answer_and_of_the_summary():
    block = [NotChecked(name="Ofran", reason="login: the agency is not logged in to Ofran"), NotChecked(name="El Al", reason="Access denied in the operator's Chrome"), NotChecked(name="Booking", reason="route not served")]
    assert len(needs_you(block)) == 2 and needs_you(block)[0].startswith("Needs you: Ofran (login")
    out = _hotels(extra_not_checked=block)
    assert out["answer"].splitlines()[0].startswith("Needs you: Ofran") and out["answer"].splitlines()[1].startswith("Needs you: El Al") and "Sources checked:" in out["answer"].splitlines()[2]
    SUMMARIES.clear()
    SUMMARIES.remember("hotels", None, out["summary"])
    assert build_summary(SUMMARIES.recent())["answer"].splitlines()[0].startswith("Needs you: Ofran")
    SUMMARIES.clear()


async def test_the_tool_builds_the_summary_from_compose_answers_and_the_text_passes_check_answer(monkeypatch):
    SUMMARIES.clear()
    COMPOSED.clear()
    async with Client(create_server(Settings())) as c:
        empty = (await c.call_tool("compose_summary", {})).structured_content
        assert empty["ok"] is False and "compose_answer" in empty["problems"][0]
        offers = [{"group": "Lisbon, 7-12 Mar 2027", "source": "MyHotels", "name": "Czar Lisbon Hotel", "price_total": 365, "currency": "EUR", "quotable": True, "fits": True, "details": dict(HOTEL), "link": "https://x/czar"}]
        done = (await c.call_tool("compose_answer", {"kind": "hotels", "offers": offers, "filters_used": ["4+ stars (operator)"], "myt_supplier": {"MyHotels": "yes"},
                                                      "sources_read": [{"name": "MyHotels", "read": 1, "of": 1, "link": "https://myhotels.test/lisbon?q=1"}], "not_checked": [{"name": "Arbitrip", "reason": "operator asked for MyHotels only"}],
                                                      "request": "5 nights in Lisbon, around 4 stars"})).structured_content
        assert done["ok"] is True and "summary" not in done, done.get("problems")
        out = (await c.call_tool("compose_summary", {"request": "5 nights in Lisbon, around 4 stars", "asked": ["hotels", "flights"]})).structured_content
        assert out["ok"] is True and out["kinds"] == ["hotels"] and out["not_searched"] == ["flights"] and "| Cheapest | MyHotels: Czar Lisbon Hotel" in out["answer"]
        checked = (await c.call_tool("check_answer", {"draft": out["answer"], "kind": "general"})).structured_content
        assert not any("typed or changed by hand" in m for m in checked.get("missing", [])), checked
    SUMMARIES.clear()


async def test_the_rentalcars_description_no_longer_tells_the_chat_to_skip_a_young_driver(monkeypatch):
    async with Client(create_server(Settings())) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    d = tools["rentalcars_cars_recipe"].description
    assert "The driver is 30-65" not in d and "under 30 is searched at 30" not in d and "searched as given" in d and "never skip this source for age" in d
