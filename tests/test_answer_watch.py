"""answer_watch: counts (in the log) the answers composed and never checked; it refuses and changes nothing."""

import asyncio
import logging

import pytest
from mcp import Client

from myt_mcp import answer_watch
from myt_mcp.app import create_server
from myt_mcp.config import Settings


def test_an_unchecked_answer_is_reported_once_and_a_checked_one_is_not(caplog):
    caplog.set_level(logging.INFO, logger="myt_mcp")
    answer_watch.composed("flights")
    stamp = answer_watch._PENDING["flights"]
    assert answer_watch.report("flights", stamp) is True and "check_answer was not called" in caplog.text and "kind=flights" in caplog.text
    assert answer_watch.report("flights", stamp) is False                      # once only
    answer_watch.composed("hotels")
    stamp = answer_watch._PENDING["hotels"]
    answer_watch.checked()
    assert answer_watch.report("hotels", stamp) is False


def test_a_later_answer_of_the_same_kind_is_not_reported_by_the_timer_of_an_earlier_one():
    answer_watch.composed("cars")
    first = answer_watch._PENDING["cars"]
    answer_watch._PENDING["cars"] = first + 1          # a newer compose_answer of the same kind
    assert answer_watch.report("cars", first) is False


def test_the_timer_writes_the_line_by_itself_after_the_wait(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="myt_mcp")
    monkeypatch.setattr(answer_watch, "WAIT_SECONDS", 0.02)

    async def go():
        answer_watch.composed("transfers")
        await asyncio.sleep(0.1)
    asyncio.run(go())
    assert "kind=transfers" in caplog.text and answer_watch._PENDING == {}


def test_a_check_before_the_timer_keeps_the_log_quiet(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="myt_mcp")
    monkeypatch.setattr(answer_watch, "WAIT_SECONDS", 0.05)

    async def go():
        answer_watch.composed("trains")
        answer_watch.checked()
        await asyncio.sleep(0.15)
    asyncio.run(go())
    assert "check_answer was not called" not in caplog.text


@pytest.mark.anyio
async def test_compose_answer_starts_the_count_and_check_answer_clears_it():
    import json
    from tests.test_booking_flights import RECIPE, answer
    async with Client(create_server(Settings())) as c:
        item = {"site": "booking_flights", "result": answer(), "url": RECIPE["url"]}
        done = (await c.call_tool("compose_answer", {"kind": "flights", "site_results": [item], "wishes": {"expect": RECIPE["expect"]}, "filters_used": ["Connections allowed (operator)", "Best and Cheapest sorts read together (agency rule)"], "not_checked": [{"name": "TAP", "reason": "operator asked for Booking.com only"}], "myt_supplier": {"SKY express": "not checked: test"}})).structured_content
        assert done["ok"] is True, done
        assert "flights" in answer_watch._PENDING
        await c.call_tool("check_answer", {"draft": done["answer"], "kind": "flights"})
        assert answer_watch._PENDING == {}


def test_a_filter_line_that_asks_for_refundable_fares_is_read_as_the_wish():
    from myt_mcp.tools.compose_answer import asks_refundable
    assert asks_refundable(["Economy cabin (operator)", "Refundable fares only (operator)"]) is True
    assert asks_refundable(["Refundable fares not required (operator)", "No preference on refunds"]) is False
    assert asks_refundable(["Connections allowed (operator)"]) is False and asks_refundable(None) is False


@pytest.mark.anyio
async def test_compose_answer_checks_refund_terms_when_only_the_filter_line_says_refundable(monkeypatch):
    """28 Oct 2026: the sources read had been given no refundable wish (only TAP and SATA, both not read, had), so a fare with no refund terms was the Best fit of a 'refundable only' answer."""
    from tests.test_booking_flights import RECIPE, answer
    import myt_mcp.tools.compose_answer as ca
    monkeypatch.setattr(ca, "refund_unconfirmed", lambda offers: "REFUND TERMS WERE NOT CONFIRMED")
    async with Client(create_server(Settings())) as c:
        item = {"site": "booking_flights", "result": answer(), "url": RECIPE["url"]}
        args = {"kind": "flights", "site_results": [item], "wishes": {"expect": RECIPE["expect"]}, "not_checked": [{"name": "TAP", "reason": "operator asked for Booking.com only"}], "myt_supplier": {"SKY express": "not checked: test"}}
        on = (await c.call_tool("compose_answer", {**args, "filters_used": ["Connections allowed (operator)", "Refundable fares only (operator)"]})).structured_content
        off = (await c.call_tool("compose_answer", {**args, "filters_used": ["Connections allowed (operator)", "Best and Cheapest sorts read together (agency rule)"]})).structured_content
        assert on["ok"] is True and "REFUND TERMS WERE NOT CONFIRMED" in on["answer"], on
        assert off["ok"] is True and "REFUND TERMS WERE NOT CONFIRMED" not in off["answer"]


@pytest.mark.anyio
async def test_the_nothing_found_answer_goes_through_the_tool_and_check_answer_passes_it():
    """28 Oct 2026, trains: the tool refused ('sources_read is empty'), the chat wrote the section itself."""
    async with Client(create_server(Settings())) as c:
        done = (await c.call_tool("compose_answer", {"kind": "trains", "filters_used": ["2nd class (operator)", "Changes allowed (operator)"],
                                                     "not_checked": [{"name": "CP", "reason": "not available: CP has no trains on sale for this date"}, {"name": "RateHawk Train tickets", "reason": "route not served: no Lisboa station"}]})).structured_content
        assert done["ok"] is True, done
        assert done["answer"].startswith("Sources checked: none returned an option")
        checked = (await c.call_tool("check_answer", {"draft": done["answer"], "kind": "trains"})).structured_content
        assert checked["ok"] is True, checked
