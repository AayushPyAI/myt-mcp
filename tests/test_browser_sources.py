"""hotel_prices, transfer_prices and other_source_prices: no prices, only the plan and the guard rails."""

from datetime import date, timedelta

import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings

pytestmark = pytest.mark.anyio


async def call(name, args):
    async with Client(create_server(Settings())) as c:
        return await c.call_tool(name, args)


def future(days):
    return (date.today() + timedelta(days=days)).isoformat()


async def test_hotel_plan_has_both_sites_formats_and_the_playbook():
    r = await call("hotel_prices", {"hotel_or_city": "Hotel Berchielli", "check_in": "2099-02-25", "check_out": "2099-02-28"})
    out = r.structured_content
    assert not r.is_error
    assert out["search"]["nights"] == 3 and out["search"]["meal_plan"].startswith("BB")
    assert out["ratehawk"]["dates_in_url"] == "25.02.2099-28.02.2099"
    assert out["arbitrip"]["dates_in_url"] == "check_in=990225&check_out=990228"
    assert "Israel" in out["ratehawk"]["citizenship"] and "Show N more rates" in out["playbook"]
    assert "Claude in Chrome" in out["browser"] and "price" not in {k for k in out if k.endswith("price")}


@pytest.mark.parametrize("args, message", [
    ({"check_in": "2020-02-25", "check_out": "2020-02-28"}, "too far away"),
    ({"check_in": future(10), "check_out": future(10)}, "after check_in"),
    ({"check_in": future(10), "check_out": future(60)}, "30 nights"),
    ({"check_in": future(10), "check_out": future(12), "adults": 0}, "adults must be"),
    ({"check_in": future(10), "check_out": future(12), "children_ages": [30]}, "ages 0-17"),
])
async def test_hotel_plan_refuses_bad_searches(args, message):
    r = await call("hotel_prices", {"hotel_or_city": "Florence", **args})
    assert r.is_error and message in r.content[0].text


async def test_hotel_plan_refuses_an_empty_name():
    r = await call("hotel_prices", {"hotel_or_city": "  ", "check_in": future(5), "check_out": future(7)})
    assert r.is_error and "empty" in r.content[0].text


async def test_transfer_has_no_price_and_points_to_the_playbook():
    out = (await call("transfer_prices", {"from_place": "Rome FCO", "to_place": "Hotel Mia", "transfer_date": future(3)})).structured_content
    assert "Never estimate" in out["no_prices_here"] and "kiwitaxi_transfer_prices" in out["no_prices_here"] and "Never estimate a transfer price" in out["playbook"]


@pytest.mark.parametrize("asked, expected", [
    ("Tripadvisor", "Viator"), ("Check Booking.com for me", "hotel_prices"), ("Ryanair flights", "sata_flight_prices"),
    ("Sixt", "ofran_car_prices"), ("Priority Pass", "lounge_prices"), ("El Al", "tap_flight_prices"), ("Skyscanner", "sata_flight_prices"),
])
async def test_other_sources_offer_the_connected_alternative(asked, expected):
    out = (await call("other_source_prices", {"site_or_topic": asked})).structured_content
    assert expected in out["offer_instead"] and "web search" in out["no_prices_here"]


@pytest.mark.parametrize("asked, tool", [("TAP", "tap_flight_prices"), ("kiwitaxi.com", "kiwitaxi_transfer_prices")])
async def test_a_connected_source_is_not_called_unconnected(asked, tool):
    out = (await call("other_source_prices", {"site_or_topic": asked})).structured_content
    assert tool in out["offer_instead"] and "IS connected" in out["no_prices_here"] and "not connected" not in out["no_prices_here"].replace("IS connected", "")


async def test_unknown_site_still_gets_the_rules():
    out = (await call("other_source_prices", {"site_or_topic": "some-random-site.example"})).structured_content
    assert out["category"] == "not in the agency's list" and "not connected" in out["no_prices_here"]


async def test_a_past_date_without_year_moves_to_the_next_occurrence_and_says_so():
    start = date.today() - timedelta(days=30)
    out = (await call("hotel_prices", {"hotel_or_city": "Florence", "check_in": start.isoformat(),
                                       "check_out": (start + timedelta(days=3)).isoformat()})).structured_content
    assert date.fromisoformat(out["search"]["check_in"]) >= date.today() and out["search"]["nights"] == 3
    assert "past" in out["date_note"] and "Say which year" in out["date_note"]


async def test_a_future_date_has_no_date_note():
    out = (await call("hotel_prices", {"hotel_or_city": "Florence", "check_in": future(20), "check_out": future(23)})).structured_content
    assert "date_note" not in out


@pytest.mark.parametrize("asked", ["Skyscanner", "El Al", "elal.com"])
async def test_skyscanner_and_el_al_are_read_in_the_operators_chrome_not_unconnected(asked):
    out = (await call("other_source_prices", {"site_or_topic": asked})).structured_content
    assert "operator's own Chrome" in out["no_prices_here"] and "web search" in out["no_prices_here"]
    assert "Claude in Chrome" in out["how"] and "Skyscanner" in out["playbook"]
