"""Failure handling: every outside failure becomes a clear message, and nothing crashes the server."""

import asyncio
from datetime import date, timedelta

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.cache import TTLCache
from myt_mcp.config import ConfigError, Settings
from myt_mcp.myt.client import MYTClient, MYTError
from myt_mcp.ofran.client import OfranClient
from myt_mcp.ofran.transport import BLOCKED, HttpTransport, OfranError, parse_response
from myt_mcp.ratelimit import RateLimitError, SiteLimiter
from myt_mcp.services import Services
from tests.test_ofran import RAW_LOCATIONS, RESULT

pytestmark = pytest.mark.anyio


def http(handler):
    return httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(handler))


# --- Ofran transport -----------------------------------------------------------------------

@pytest.mark.parametrize("status,body,expected", [
    (403, "<h1>Ofran - Access Denied</h1>", BLOCKED),
    (200, "<html>Access Denied</html>", BLOCKED),
    (429, "", "limiting requests"),
    (502, "", "having problems"),
    (404, "", "returned 404"),
    (200, "<html>not json</html>", "a page instead of data"),
])
async def test_ofran_http_status_mapping(status, body, expected):
    t = HttpTransport(client=http(lambda r: httpx.Response(status, text=body)))
    with pytest.raises(OfranError, match=expected[:20]):
        await t.request("GET", "/api/locations")


async def test_ofran_http_timeout_and_network_error():
    def timeout(_):
        raise httpx.ReadTimeout("slow")

    def down(_):
        raise httpx.ConnectError("no route")

    with pytest.raises(OfranError, match="did not answer in time"):
        await HttpTransport(client=http(timeout)).request("GET", "/x")
    with pytest.raises(OfranError, match="Could not reach Ofran"):
        await HttpTransport(client=http(down)).request("GET", "/x")


# --- MYT client ------------------------------------------------------------------------------

async def test_myt_errors_are_readable():
    def respond(req):
        if "GetTripByTripNumber" in req.url.path:
            return httpx.Response(200, content=b"")
        if "v3" in req.url.path:
            return httpx.Response(503)
        return httpx.Response(200, text="<html>")

    myt = MYTClient("key", http=http(respond))
    with pytest.raises(MYTError, match="no trip number 1"):
        await myt.get_trip_by_number(1)
    with pytest.raises(MYTError, match="having problems"):
        await myt.get_trip_v3(5)
    with pytest.raises(MYTError, match="not JSON"):
        await myt.get_participants(5)
    with pytest.raises(MYTError, match="MYT_API_KEY is not configured"):
        MYTClient("")


# --- cache -----------------------------------------------------------------------------------

async def test_cache_shares_one_load_between_concurrent_callers():
    calls = 0

    async def load():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "value"

    cache = TTLCache(60)
    assert await asyncio.gather(*(cache.get_or_load("k", load) for _ in range(5))) == ["value"] * 5
    assert calls == 1


async def test_cache_does_not_keep_failures():
    cache, attempts = TTLCache(60), []

    async def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("first try fails")
        return "ok"

    with pytest.raises(RuntimeError):
        await cache.get_or_load("k", flaky)
    assert await cache.get_or_load("k", flaky) == "ok"


# --- config ----------------------------------------------------------------------------------

def test_config_errors_are_explained():
    with pytest.raises(ConfigError, match="ALLOWED_TRIP_IDS"):
        Settings.from_env({"ALLOWED_TRIP_IDS": "abc"})
    with pytest.raises(ConfigError, match="MCP_SECRET"):
        Settings().require_secret()
    assert Settings.from_env({"ALLOWED_TRIP_IDS": "276310, 5"}).allowed_trip_ids == {276310, 5}


# --- tools through the MCP layer -------------------------------------------------------------

class FakeOfranTransport:
    def __init__(self, result=RESULT, locations=RAW_LOCATIONS):
        self.result, self.locations, self.searches = result, locations, 0

    async def request(self, method, path, body=None):
        if path == "/api/locations":
            return self.locations
        self.searches += 1
        if isinstance(self.result, Exception):
            raise self.result
        return {"result": self.result, "errors": None}

    async def aclose(self):
        pass


class ExplodingMYT:
    def __getattr__(self, name):
        raise AssertionError(f"MYT was called ({name}) for a blocked trip")


def fast_limiter(max_per_hour=1000):
    return SiteLimiter("Ofran", min_interval=0, max_per_hour=max_per_hour)


def server(transport=None, allowed=frozenset({276310}), myt=None, limiter=None, settings=None):
    settings = settings or Settings(allowed_trip_ids=allowed)
    ofran = OfranClient(transport or FakeOfranTransport(), limiter=limiter or fast_limiter())
    return create_server(settings, Services(settings, myt=myt or ExplodingMYT(), ofran=ofran))


async def call(srv, tool, args):
    async with Client(srv) as c:
        return await c.call_tool(tool, args)


SOON = date.today() + timedelta(days=30)


@pytest.mark.parametrize("args,expected", [
    ({"pickup_date": (date.today() - timedelta(days=1)).isoformat()}, "in the past"),
    ({"dropoff_date": SOON.isoformat()}, "must be after"),
    ({"pickup_time": "25:00"}, "HH:MM"),
    ({"driver_age": 12}, "between 18 and 99"),
    ({"max_results": 0}, "between 1 and 50"),
    ({"location": "Atlantis"}, "No Ofran location matches"),
    ({"location": "   "}, "is empty"),
])
async def test_ofran_tool_input_validation(args, expected):
    base = {"location": "Lisbon Airport", "pickup_date": SOON.isoformat(), "dropoff_date": (SOON + timedelta(days=5)).isoformat()}
    r = await call(server(), "ofran_car_prices", {**base, **args})
    assert r.is_error and expected in r.content[0].text


async def test_ofran_tool_answer_with_alternatives_and_empty_result():
    args = {"location": "Lisbon", "pickup_date": SOON.isoformat(), "dropoff_date": (SOON + timedelta(days=5)).isoformat()}
    ok = (await call(server(), "ofran_car_prices", args)).structured_content
    assert ok["pickup"]["code"] == "LIS" and ok["offers_found"] == 3 and ok["rental_days"] == 5
    assert ok["other_matching_locations"] == ["Lisbon City Center"]
    empty = (await call(server(FakeOfranTransport(result=[])), "ofran_car_prices", args)).structured_content
    assert empty["offers_found"] == 0 and "no cars" in empty["note"]


async def test_ofran_failure_reaches_the_model_as_a_message():
    srv = server(FakeOfranTransport(result=OfranError(BLOCKED)))
    args = {"location": "LIS", "pickup_date": SOON.isoformat(), "dropoff_date": (SOON + timedelta(days=2)).isoformat()}
    r = await call(srv, "ofran_car_prices", args)
    assert r.is_error and "403" in r.content[0].text


async def test_unexpected_bug_gives_a_safe_message():
    srv = server(FakeOfranTransport(result=ZeroDivisionError("boom")))
    args = {"location": "LIS", "pickup_date": SOON.isoformat(), "dropoff_date": (SOON + timedelta(days=2)).isoformat()}
    r = await call(srv, "ofran_car_prices", args)
    assert r.is_error and "failed unexpectedly (ZeroDivisionError)" in r.content[0].text and "boom" not in r.content[0].text


@pytest.mark.parametrize("tool", ["get_trip", "get_quotation", "get_trip_participants"])
async def test_blocked_trip_never_reaches_myt(tool):
    r = await call(server(), tool, {"trip_id": 269362})
    assert r.is_error and "outside the allowed test trips" in r.content[0].text and "find_trip" in r.content[0].text


async def test_missing_myt_key_is_explained():
    settings = Settings()
    srv = create_server(settings, Services(settings))
    r = await call(srv, "get_trip", {"trip_id": 1})
    assert r.is_error and "MYT_API_KEY is not configured" in r.content[0].text


async def test_locations_loaded_once_for_many_searches():
    transport = FakeOfranTransport()
    calls = {"locations": 0}
    original = transport.request

    async def counting(method, path, body=None):
        if path == "/api/locations":
            calls["locations"] += 1
        return await original(method, path, body)

    transport.request = counting
    srv = server(transport)
    for days in (2, 3, 4):  # three different searches
        args = {"location": "LIS", "pickup_date": SOON.isoformat(), "dropoff_date": (SOON + timedelta(days=days)).isoformat()}
        await call(srv, "ofran_car_prices", args)
    assert calls["locations"] == 1 and transport.searches == 3


# --- scraping rules ------------------------------------------------------------------------

async def test_same_search_is_answered_from_cache():
    transport = FakeOfranTransport()
    srv = server(transport)
    args = {"location": "LIS", "pickup_date": SOON.isoformat(), "dropoff_date": (SOON + timedelta(days=2)).isoformat()}
    for _ in range(3):
        assert not (await call(srv, "ofran_car_prices", args)).is_error
    assert transport.searches == 1


async def test_hourly_cap_stops_further_searches():
    srv = server(limiter=fast_limiter(max_per_hour=2))  # 1 request for locations + 1 search
    base = {"location": "LIS", "pickup_date": SOON.isoformat()}
    ok = await call(srv, "ofran_car_prices", {**base, "dropoff_date": (SOON + timedelta(days=2)).isoformat()})
    capped = await call(srv, "ofran_car_prices", {**base, "dropoff_date": (SOON + timedelta(days=3)).isoformat()})
    assert not ok.is_error
    assert capped.is_error and "searches per hour" in capped.content[0].text


async def test_limiter_spaces_requests():
    now, waits = [0.0], []

    async def fake_sleep(s):
        waits.append(round(s, 2))
        now[0] += s

    lim = SiteLimiter("X", min_interval=5, max_per_hour=10, clock=lambda: now[0], sleep=fake_sleep)
    await lim.acquire()
    await lim.acquire()
    assert waits == [5.0]


async def test_kill_switch_turns_ofran_off():
    srv = server(settings=Settings(allowed_trip_ids=frozenset({276310}), ofran_enabled=False))
    args = {"location": "LIS", "pickup_date": SOON.isoformat(), "dropoff_date": (SOON + timedelta(days=2)).isoformat()}
    r = await call(srv, "ofran_car_prices", args)
    assert r.is_error and "switched off" in r.content[0].text


def test_captcha_page_stops_immediately():
    with pytest.raises(OfranError, match="human check"):
        parse_response(200, "<html><title>Just a moment...</title>challenge-platform</html>", "/api/x")
    assert parse_response(200, '{"note": "captcha in json is fine"}', "/api/x") == {"note": "captcha in json is fine"}


def test_scraping_settings_are_validated():
    with pytest.raises(ConfigError, match="SCRAPE_MIN_INTERVAL"):
        Settings(scrape_min_interval_seconds=0)
    assert Settings.from_env({"OFRAN_ENABLED": "false"}).ofran_enabled is False


async def test_trip_pauses_a_site_for_thirty_minutes_and_then_lets_calls_through():
    now = [1000.0]

    async def fake_sleep(s):
        now[0] += s

    lim = SiteLimiter("Mozio", min_interval=0, max_per_hour=10, clock=lambda: now[0], sleep=fake_sleep)
    await lim.acquire()
    lim.trip()
    with pytest.raises(RateLimitError, match="paused for about 30 more minutes"):
        await lim.acquire()
    now[0] += 29 * 60
    with pytest.raises(RateLimitError, match="paused"):
        await lim.acquire()
    now[0] += 2 * 60
    await lim.acquire()                                                # the pause is over
