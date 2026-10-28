"""Server first, Claude in Chrome second (27 Oct 2026): Bensaude, Europcar, Rentalcars.com and Booking.com (flights, activities list, one activity) are read by the server's own automation Chrome when it can; when it
cannot (no browser, a block or human check, a timeout, a script error) the same recipe comes back for the operator's Claude in Chrome with the reason. A blocked site is paused (Rentalcars: 6 hours)."""

import json
import os

import pytest
from mcp import Client

import myt_mcp.sites as sites
from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.services import Services
from myt_mcp.sites import clock24, day_month, paused_minutes, pause_site, server_first

pytestmark = pytest.mark.anyio

RECEIPT = {"ok": True, "received": True, "how": "read by the server itself in its own automation Chrome", "ingest": "tok123", "rows_read": 7, "next": 'STOP: Call compose_answer with runs=["tok123"]'}
ARGS = {
    "bensaude_hotels_recipe": {"hotel": "Terra Nostra Garden Hotel", "check_in": "2027-03-06", "check_out": "2027-03-08"},
    "europcar_cars_recipe": {"pickup": "Lisbon Airport", "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00", "gearbox": "automatic", "min_seats": 5, "zero_excess": False, "max_total": 300},
    "rentalcars_cars_recipe": {"pickup": "Lisbon Airport", "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00", "gearbox": "automatic", "min_seats": 5, "zero_excess": False, "max_total": 300},
    "booking_flights_recipe": {"origin": "TLV", "destination": "LIS", "day": "2027-03-06", "direct_only": False, "cabin": "economy"},
    "booking_attractions_recipe": {"place": "Lisbon", "day": "2027-03-07"},
    "skyscanner_recipe": {"origin": "tlv", "destination": "lis", "day": "2027-03-06", "direct_only": False, "cabin": "economy"},
    "tap_recipe": {"origin": "TLV", "destination": "LIS", "day": "2027-03-06", "direct_only": False, "checked_bag": False, "refundable": False},
    "booking_attraction_recipe": {"url": "https://www.booking.com/attractions/pt/pr4z1zrjq9hl-skip-the-queue-tickets-into-the-lisbon-oceanarium.html", "day": "2026-11-10", "adults": 2, "children_ages": []},
}
SITE_OF = {"bensaude_hotels_recipe": "bensaude_hotels", "europcar_cars_recipe": "europcar_cars", "rentalcars_cars_recipe": "rentalcars_cars", "booking_flights_recipe": "booking_flights",
           "booking_attractions_recipe": "booking_attractions", "booking_attraction_recipe": "booking_attraction", "skyscanner_recipe": "skyscanner", "tap_recipe": "tap"}


def switch(flag, default=True):
    """What the real server_reads does with its default and the environment, without a browser address."""
    value = os.environ.get(flag)
    return default if value is None else value.strip().lower() not in ("0", "false", "no", "")


@pytest.fixture(autouse=True)
def no_exchange_feeds(monkeypatch):
    async def none():
        return None
    for m in ("europcar_cars", "rentalcars_cars"):
        monkeypatch.setattr(f"myt_mcp.sites.{m}.eur_factors", none)


def test_the_clock_and_the_date_order_are_the_same_whichever_chrome_read_them():
    assert [clock24(x) for x in ("5:30 AM", "12:15 AM", "12:00 PM", "1:00 PM", "11:59 PM", "23:30", "10:00", None, "")] == ["05:30", "00:15", "12:00", "13:00", "23:59", "23:30", "10:00", None, None]
    assert [day_month(x) for x in ("Mar 7", "7 Mar", "Sun 7 Mar", None)] == ["7 Mar", "7 Mar", "Sun 7 Mar", None]


async def test_without_a_server_browser_the_recipe_is_returned_unchanged(monkeypatch):
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    out = {"url": "https://x.test/", "script": "await (async () => {\n})()"}
    assert await server_first("booking_flights", "BOOKING_FLIGHTS_READ_IN_SERVER", "https://flights.booking.com", dict(out)) == out


async def test_a_page_the_server_could_read_comes_back_as_the_receipt_and_one_it_could_not_as_the_recipe_with_the_reason(monkeypatch):
    monkeypatch.setattr(sites, "server_reads", lambda flag, default=True: True)
    seen = {}

    async def good(site, origin, url, out, ready_path=None):
        seen.update(site=site, origin=origin, url=url)
        return dict(RECEIPT)
    monkeypatch.setattr(sites, "read_in_server_browser", good)
    out = {"url": "https://flights.booking.com/x", "script": "S"}
    assert await server_first("booking_flights", "F", "https://flights.booking.com", out) == RECEIPT and seen == {"site": "booking_flights", "origin": "https://flights.booking.com", "url": "https://flights.booking.com/x"}

    async def blocked(*a, **k):
        return {"ok": False, "error": "rentalcars_cars is paused for 300 more minutes after it showed a human check"}
    monkeypatch.setattr(sites, "read_in_server_browser", blocked)
    back = await server_first("rentalcars_cars", "F", "https://www.rentalcars.com", {"url": "https://u", "script": "S"})
    assert back["script"] == "S" and back["url"] == "https://u" and back["server_read"] == {"tried": True, "ok": False, "why": "rentalcars_cars is paused for 300 more minutes after it showed a human check"}
    assert "Claude in Chrome" in back["how_to_read"] and "never type a row" in back["how_to_read"]

    async def boom(*a, **k):
        raise RuntimeError("secret detail that must not travel")
    monkeypatch.setattr(sites, "read_in_server_browser", boom)
    back = await server_first("bensaude_hotels", "F", "https://b", {"url": "https://u", "script": "S"})
    assert back["server_read"]["why"] == "the server's browser failed (RuntimeError)" and "secret" not in json.dumps(back)


async def test_a_human_verification_page_pauses_rentalcars_for_six_hours_and_other_sites_for_one(monkeypatch):
    monkeypatch.setattr(sites, "server_reads", lambda flag, default=True: True)

    class Browser:
        async def run(self, origin, url, action):
            return json.dumps({"ok": False, "error": "rentalcars_cars shows a block page (it refuses the server's browser). Stop: do not retry and do not work around it."})
    monkeypatch.setattr(sites, "_SERVER_BROWSER", Browser())
    monkeypatch.setattr(sites, "MIN_SECONDS_BETWEEN_READS", 0.0)
    first = await server_first("rentalcars_cars", "F", "https://www.rentalcars.com", {"url": "https://www.rentalcars.com/search-results?x=1", "script": "await (async () => {\nreturn 1;\n})()"})
    assert first["server_read"]["ok"] is False and 300 < paused_minutes("rentalcars_cars") <= 361
    again = await server_first("rentalcars_cars", "F", "https://www.rentalcars.com", {"url": "https://www.rentalcars.com/search-results?x=2", "script": "S"})
    assert "paused for" in again["server_read"]["why"] and "human check" in again["server_read"]["why"]       # not even tried: the operator's Chrome reads it
    pause_site("bensaude_hotels")
    assert 55 < paused_minutes("bensaude_hotels") <= 61
    assert sites.BLOCK_WORDS.search("Let's confirm you are human") and sites.BLOCK_WORDS.search("Human Verification")


@pytest.mark.parametrize("tool", sorted(ARGS))
async def test_every_one_of_the_six_tools_gives_the_receipt_when_the_server_read_and_the_recipe_with_the_reason_when_not(tool, monkeypatch):
    monkeypatch.setattr(sites, "server_reads", switch)
    monkeypatch.setenv("RENTALCARS_READ_IN_SERVER", "1")      # Rentalcars is off by default; the switch turns it on
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://mcp.example.test")
    calls = []

    async def good(site, origin, url, out, ready_path=None):
        calls.append((site, origin))
        return dict(RECEIPT)
    monkeypatch.setattr(sites, "read_in_server_browser", good)
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        got = (await c.call_tool(tool, ARGS[tool])).structured_content
        assert got["ingest"] == "tok123" and "script" not in got and calls[0][0] == SITE_OF[tool], got

        async def refused(site, origin, url, out, ready_path=None):
            return {"ok": False, "error": f"{site} shows a block page (it refuses the server's browser)."}
        monkeypatch.setattr(sites, "read_in_server_browser", refused)
        back = (await c.call_tool(tool, ARGS[tool])).structured_content
        assert back["script"] and back["url"].startswith("https://") and back["server_read"]["ok"] is False and "block page" in back["server_read"]["why"]
        assert back.get("ingest") and "compose_answer" in back["finish"]       # the recipe for Claude in Chrome still carries its own ingest receipt address


async def test_the_tools_ask_first_gates_still_come_before_any_server_read(monkeypatch):
    monkeypatch.setattr(sites, "server_reads", lambda flag, default=True: True)
    called = []

    async def spy(*a, **k):
        called.append(1)
        return dict(RECEIPT)
    monkeypatch.setattr(sites, "read_in_server_browser", spy)
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        asked = (await c.call_tool("europcar_cars_recipe", {"pickup": "Lisbon Airport", "pickup_date": "2027-03-06", "pickup_time": "10:00", "dropoff_date": "2027-03-08", "dropoff_time": "10:00"})).structured_content
        flights = (await c.call_tool("booking_flights_recipe", {"origin": "TLV", "destination": "LIS", "day": "2027-03-06"})).structured_content
    assert asked["ok"] is False and flights["ok"] is False and called == []      # nothing is read before the operator answered


def test_a_flight_read_by_the_servers_us_english_chrome_reads_like_one_read_by_the_operators_chrome():
    from tests.test_booking_flights import EXPECT, answer, row
    from myt_mcp.sites.booking_flights import convert
    us = row("Best", carriers="Iberia", dep="5:30 AM", arr="11:50 AM", dep_date="Mar 6", arr_date="Mar 6", duration="8h 20m", total=370.0, per=185.0)
    eu = row("Cheapest", carriers="Iberia", dep="05:30", arr="11:50", dep_date="6 Mar", arr_date="6 Mar", duration="8h 20m", total=370.0, per=185.0)
    rows = convert(answer([us, eu, row("Best", dep="11:30 PM", arr="10:30 PM", dep_date="Mar 6", arr_date="Mar 7")]), {"expect": EXPECT}, "Flights")
    assert [o.name for o in rows.offers] == ["Iberia 05:30-11:50 (8h 20m)", "SKY express 23:30-22:30 (arrives 7 Mar) (25h)"] and rows.offers[0].details["from_tab"] == "Best and Cheapest"


def test_the_start_times_of_an_activity_read_by_the_server_have_the_24_hour_clock():
    from tests.test_booking_attraction import EXPECT, answer, row
    from myt_mcp.sites.booking_attraction import convert
    o = convert(answer([row(times=["10:00 AM", "01:30 PM", "06:00 PM"], time_chosen="10:00 AM")]), {"expect": EXPECT}, "Activities").offers[0]
    assert o.details["start_times"].startswith("3 start time(s): 10:00, 13:30, 18:00 (first chosen: 10:00;")


async def test_the_server_reads_at_most_the_set_number_of_pages_at_once_and_the_rest_wait_in_line(monkeypatch):
    import asyncio
    monkeypatch.setattr(sites, "server_reads", lambda flag, default=True: True)
    monkeypatch.setattr(sites, "MIN_SECONDS_BETWEEN_READS", 0.0)
    sites._SLOTS.clear()

    async def run_with(limit):
        monkeypatch.setenv("SERVER_READS_AT_ONCE", str(limit))
        sites._SLOTS.clear()
        now = {"n": 0, "max": 0}

        class Browser:
            async def run(self, origin, url, action):
                now["n"] += 1; now["max"] = max(now["max"], now["n"])
                await asyncio.sleep(0.05)
                now["n"] -= 1
                return json.dumps({"ok": False, "error": "no rows (test)"})
        monkeypatch.setattr(sites, "_SERVER_BROWSER", Browser())
        sites_list = ["bensaude_hotels", "europcar_cars", "booking_flights", "booking_attractions", "booking_attraction", "rentalcars_cars"]
        await asyncio.gather(*[server_first(n, "F", f"https://{n}.test", {"url": f"https://{n}.test/x", "script": "await (async () => {\n})()"}) for n in sites_list])
        return now["max"]
    assert await run_with(2) == 2
    assert await run_with(1) == 1       # strictly one after another
    assert await run_with(0) == 1       # a nonsense value never blocks everything: at least one at a time
    monkeypatch.setenv("SERVER_READS_AT_ONCE", "many")
    sites._SLOTS.clear()
    assert sites.read_slots()._value == 2       # an unreadable value falls back to two


async def test_rentalcars_is_read_in_the_operators_chrome_only_unless_its_switch_is_set(monkeypatch):
    monkeypatch.setattr(sites, "server_reads", switch)
    monkeypatch.delenv("RENTALCARS_READ_IN_SERVER", raising=False)
    called = []

    async def spy(*a, **k):
        called.append(1)
        return dict(RECEIPT)
    monkeypatch.setattr(sites, "read_in_server_browser", spy)
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        got = (await c.call_tool("rentalcars_cars_recipe", ARGS["rentalcars_cars_recipe"])).structured_content
        tool = next(t for t in (await c.list_tools()).tools if t.name == "rentalcars_cars_recipe")
    assert called == [] and got["script"] and "server_read" not in got
    assert "OPERATOR'S CHROME ONLY" in tool.description and "SERVER FIRST" not in tool.description
