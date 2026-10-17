"""MYTClient against a fake MYT server: the write calls (Create, Update) and the v3 cache invalidation that makes a
read-back right after a write return fresh data instead of the pre-write cache (a real bug found 17 Oct 2026: the second
read after an Update returned the OLD price because GetTrip/v3 is cached for 60 seconds)."""

from __future__ import annotations

import json

import httpx
import pytest

from myt_mcp.myt.client import MYTClient, MYTError

pytestmark = pytest.mark.anyio


def client_for(handler) -> MYTClient:
    return MYTClient("test-key", http=httpx.AsyncClient(base_url="https://www.manageyourtrip.com/api",
                                                         headers={"x-api-key": "test-key"}, params={"key": "test-key"},
                                                         transport=httpx.MockTransport(handler)))


async def test_create_reservation_sends_the_documented_body_and_returns_the_order_ids():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/api/reservations/Create"
        body = json.loads(request.content)
        assert body == {"tripId": 189423, "externalId": "claude-abc", "comments": "note",
                        "products": [{"SupplierId": 1, "StartDate": "2027-03-01", "Name": "Test", "PricingTypeId": 1, "TypeId": 1,
                                     "Price": 5.0, "CurrencyCodeId": 3, "Quantity": 1, "Nights": 1, "ArrivalTime": "10:00", "Comments": ""}]}
        return httpx.Response(200, json=[2347217])

    order_ids = await client_for(handler).create_reservation(
        189423, [{"SupplierId": 1, "StartDate": "2027-03-01", "Name": "Test", "PricingTypeId": 1, "TypeId": 1,
                 "Price": 5.0, "CurrencyCodeId": 3, "Quantity": 1, "Nights": 1, "ArrivalTime": "10:00", "Comments": ""}],
        external_id="claude-abc", comments="note")
    assert order_ids == [2347217] and len(calls) == 1


async def test_create_reservation_invalidates_the_v3_cache_for_that_trip():
    reads = {"n": 0}

    def handler(request):
        if request.url.path == "/api/trip/GetTrip/v3":
            reads["n"] += 1
            return httpx.Response(200, json={"trip": {"trip_id": 189423}, "reservations": [], "read_number": reads["n"]})
        return httpx.Response(200, json=[1])

    c = client_for(handler)
    first = await c.get_trip_v3(189423)
    cached = await c.get_trip_v3(189423)
    assert cached is first and reads["n"] == 1          # still cached before any write

    await c.create_reservation(189423, [{"SupplierId": 1, "StartDate": "2027-03-01", "Name": "x", "PricingTypeId": 1,
                                        "TypeId": 1, "Price": 1.0, "CurrencyCodeId": 3, "Quantity": 1, "Nights": 1,
                                        "ArrivalTime": "10:00", "Comments": ""}])
    after = await c.get_trip_v3(189423)
    assert after is not first and after["read_number"] == 2    # a fresh read, not the pre-write cache


async def test_update_reservation_invalidates_the_v3_cache_only_when_a_trip_id_is_given():
    reads = {"n": 0}

    def handler(request):
        if request.url.path == "/api/trip/GetTrip/v3":
            reads["n"] += 1
            return httpx.Response(200, json={"trip": {"trip_id": 189423}, "read_number": reads["n"]})
        return httpx.Response(200, json=189423)

    c = client_for(handler)
    await c.get_trip_v3(189423)
    await c.update_reservation(189423, [{"OrderReservationId": 1, "ReservationDate": "2027-03-01", "Quantity": 1,
                                        "Duration": 1, "Price": 5.0, "ArrivalTime": "10:00", "Comments": "", "IsActive": True}])
    still_cached = await c.get_trip_v3(189423)
    assert still_cached["read_number"] == 1    # no trip_id given: the cache was not told to drop, so it is still stale

    await c.update_reservation(189423, [{"OrderReservationId": 1, "ReservationDate": "2027-03-01", "Quantity": 1,
                                        "Duration": 1, "Price": 6.0, "ArrivalTime": "10:00", "Comments": "", "IsActive": True}],
                               trip_id=189423)
    fresh = await c.get_trip_v3(189423)
    assert fresh["read_number"] == 2


async def test_update_reservation_sends_the_documented_body():
    def handler(request):
        assert request.url.path == "/api/reservations/Update"
        body = json.loads(request.content)
        assert body == {"orderDoc": {"OrderDocId": 2347217, "OrderReservations": [
            {"OrderReservationId": 6717038, "ReservationDate": "2027-03-01", "Quantity": 1, "Duration": 1,
             "Price": 7.5, "ArrivalTime": "10:00", "Comments": "", "IsActive": True}]}}
        return httpx.Response(200, text="2347217")

    result = await client_for(handler).update_reservation(2347217, [
        {"OrderReservationId": 6717038, "ReservationDate": "2027-03-01", "Quantity": 1, "Duration": 1,
         "Price": 7.5, "ArrivalTime": "10:00", "Comments": "", "IsActive": True}])
    assert result == 2347217          # MYT's body is a bare JSON integer; _post parses it, it is not left as text


async def test_create_and_update_report_myt_write_errors_readably():
    def handler(request):
        return httpx.Response(400, text='{"Message":"All Reservations must have id and Date"}')

    c = client_for(handler)
    with pytest.raises(MYTError, match="All Reservations must have id and Date"):
        await c.update_reservation(1, [{}])
    with pytest.raises(MYTError, match="rejected this write"):
        await c.create_reservation(1, [{}])


async def test_currency_code_id_reads_once_and_caches():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[{"Id": 1, "Name": "ILS"}, {"Id": 2, "Name": "USD"}, {"Id": 3, "Name": "EUR"}])

    c = client_for(handler)
    assert await c.currency_code_id("eur") == 3 and await c.currency_code_id("EUR") == 3
    assert len(calls) == 1          # cached after the first read


async def test_currency_code_id_rejects_an_unknown_code():
    def handler(request):
        return httpx.Response(200, json=[{"Id": 1, "Name": "ILS"}])

    with pytest.raises(MYTError, match="XYZ"):
        await client_for(handler).currency_code_id("XYZ")


async def test_invalidate_trip_cache_forces_a_fresh_read():
    reads = {"n": 0}

    def handler(request):
        reads["n"] += 1
        return httpx.Response(200, json={"trip": {"trip_id": 189423}, "read_number": reads["n"]})

    c = client_for(handler)
    first = await c.get_trip_v3(189423)
    cached = await c.get_trip_v3(189423)
    assert cached is first and reads["n"] == 1

    c.invalidate_trip_cache(189423)
    fresh = await c.get_trip_v3(189423)
    assert fresh is not first and fresh["read_number"] == 2


async def test_invalidate_trip_cache_only_affects_the_named_trip():
    def handler(request):
        trip_id = int(request.url.params["tripId"])
        return httpx.Response(200, json={"trip": {"trip_id": trip_id}})

    c = client_for(handler)
    await c.get_trip_v3(1)
    await c.get_trip_v3(2)
    c.invalidate_trip_cache(1)
    # trip 1's cache entry is gone; trip 2's is untouched
    assert c._v3_cache._fresh(1) == (False, None)
    assert c._v3_cache._fresh(2)[0] is True
