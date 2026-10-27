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
