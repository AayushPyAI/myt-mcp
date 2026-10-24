"""Azores Airlines and TAP lounge pages (patterns taken from the real pages of 24 Oct 2026)."""

import httpx
import pytest
from mcp import Client

from myt_mcp.app import create_server
from myt_mcp.config import Settings
from myt_mcp.lounges.airlines import (AirlineLoungesClient, AirlineLoungesError, _text, offer_azores, offer_tap, parse_azores, parse_tap, tap_rows)
from myt_mcp.ratelimit import SiteLimiter
from myt_mcp.services import Services

pytestmark = pytest.mark.anyio

AZORES = ("<html><script>x=1</script><p>Sales Offices and Contact Center or your Travel Agency. Check here the sales point near you.</p>"
          "<h3>Lisbon Airport | LIS</h3><h4>ANA Lounge</h4><p>Located in the commercial heart of Lisbon Airport's Terminal 1, a private space. Prices for access to the lounge: Contact Center, Sales Offices, Sales Counters, "
          "Travel Agents, and Website - €38.00 Price for TOP fare – €35.00 Free access for children aged 2 and under. Notes: Changes allowed if the flight is changed. Refunds not allowed, except in case of flight cancellation. "
          "Stay limited to a maximum of 3 hours. (Schedule 6:00 a.m. - 10:00 p.m.*) Entry to the lounge is only permitted 3h30 before the scheduled departure time. "
          "*As of January 1, 2026, the opening hours of the ANA Lounge at Lisbon Airport will be extended. The ANA Lounge will therefore open at 4:00 a.m. and close at 11:00 p.m.</p>"
          "<h3>Faro Airport | FAO</h3><h4>ANA Lounge</h4><p>This lounge is in Faro. Prices for access to the lounge: Website - €30.00 Price for TOP fare – €26.00 Stay limited to a maximum of 3 hours.</p>"
          "<h3>Madeira Airport | FNC | Lounge ANA | Vinci</h3><p>Lounge on Madeira.</p></html>")
TAP = ("<html>Buy access to the Lounges Buy your access to the Lounges and take your trip to new levels of comfort with prices starting from 28 EUR / 37 USD / 48 CAD or 5.544 miles. Buy access "
       "Prices may vary depending on the purchase channel. TAP Premium Lounges in Lisbon These Lounges managed by TAP emphasize Portuguese identity. "
       "TAP Premium Lounge Tejo Location Terminal 1 of the Lisbon airport, Schengen area Opening hours From 5 am to midnight Capacity 320 seats "
       "TAP Premium Lounge Atlântico Location Terminal 1 of the Lisbon airport, Non-Schengen area Opening hours From 5 am to midnight Capacity 100 seats "
       "TAP Premium Lounge Tejo Location Terminal 1 of the Lisbon airport, Schengen area Opening hours From 5 am to midnight Capacity 320 seats "
       "TAP Premium Lounge at Paris-Orly Location Terminal 1B Paris-Orly Airport, in the public area Opening hours From 4:30 a.m. to 9:30 p.m. Capacity Approximately 30 seats</html>")


def client_for(handler, limiter=None):
    return AirlineLoungesClient(httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True), limiter=limiter or SiteLimiter("x", 0, 1000))


def pages(seen):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, text=AZORES if "azoresairlines" in request.url.host else TAP)
    return handle


def test_azores_sections_give_airport_lounge_prices_stay_schedule_and_the_extension_without_the_text_before_them():
    sections = {s["iata"]: s for s in parse_azores(_text(AZORES))}
    lis = sections["LIS"]
    assert (lis["airport"], lis["lounge"], lis["price_website_eur"], lis["price_top_fare_eur"], lis["max_stay_hours"]) == ("Lisbon Airport", "ANA Lounge", 38.0, 35.0, 3)
    assert lis["entry_allowed_before_departure"] == "3h30" and lis["schedule"].startswith("6:00 a.m.") and lis["children"] == "Free access for children aged 2 and under"
    assert lis["refunds"].startswith("not allowed") and lis["schedule_change"].endswith("close at 11:00 p.m.")
    assert sections["FAO"]["price_website_eur"] == 30.0 and sections["FNC"]["lounge"] == "Lounge ANA | Vinci" and sections["FNC"]["price_website_eur"] is None


def test_tap_gives_its_from_price_and_each_own_lounge_once():
    tap = parse_tap(_text(TAP))
    assert tap["from_price_eur"] == 28.0 and "purchase channel" in tap["price_note"]
    assert [l["lounge"] for l in tap["own_lounges"]] == ["TAP Premium Lounge Tejo", "TAP Premium Lounge Atlântico", "TAP Premium Lounge at Paris-Orly"]
    assert [l["lounge"] for l in tap_rows(tap, "LIS")] == ["TAP Premium Lounge Tejo", "TAP Premium Lounge Atlântico"] and tap_rows(tap, "FCO") == []


def test_ready_rows_state_whose_price_it_is_and_never_multiply_it():
    lis = parse_azores(_text(AZORES))[0]
    row = offer_azores(lis, "LIS")
    assert row["price_total"] == 38.0 and row["quotable"] is False and "Azores Airlines flight booking" in row["price_basis"] and "not multiplied" in row["price_basis"]
    assert row["details"]["adult_price"] == "38 EUR per person (35 EUR with a TOP fare)" and row["details"]["stay"] == "maximum 3 hours" and "3h30" in row["details"]["entry_window"] and "see notice" in row["details"]["entry_window"] and row["details"]["notice"].endswith("close at 11:00 p.m.")
    tap = offer_tap(parse_tap(_text(TAP))["own_lounges"][0], "LIS", 28.0)
    assert tap["price_total"] == 28.0 and "varies with the channel" in tap["price_basis"] and tap["details"]["capacity"] == "320 seats"


async def test_the_client_reads_each_page_once_a_day_and_stops_at_a_human_check():
    seen: list[str] = []
    client = client_for(pages(seen))
    await client.azores(); await client.azores(); await client.tap(); await client.tap()
    assert seen == ["azoresairlines.pt", "www.flytap.com"]
    limiter = SiteLimiter("x", 0, 1000)
    blocked = client_for(lambda r: httpx.Response(200, text="<title>Just a moment...</title>"), limiter)
    with pytest.raises(AirlineLoungesError, match="human check"):
        await blocked.azores()
    with pytest.raises(Exception, match="(?i)pause|cool|wait|blocked|try again"):
        await blocked.tap()


async def test_the_tool_gives_ready_rows_for_lisbon_and_a_link_when_no_airline_lounge_exists():
    settings = Settings()
    services = Services(settings, airline_lounges=client_for(pages([])))
    async with Client(create_server(settings, services)) as c:
        lis = (await c.call_tool("airline_lounges", {"airport": "lis"})).structured_content
        fco = (await c.call_tool("airline_lounges", {"airport": "FCO"})).structured_content
        bad = await c.call_tool("airline_lounges", {"airport": "Lisbon"})
    sources = [l["source"] for l in lis["lounges"]]
    assert sources == ["Azores Airlines", "TAP Air Portugal", "TAP Air Portugal"] and lis["comparison_only"] is True and "purchase channel" in lis["tap_price_note"]
    assert lis["lounges"][0]["offer"]["price_total"] == 38.0 and lis["lounges"][1]["offer"]["price_total"] == 28.0 and "not_provided" in lis
    assert fco["lounges"] == [] and "Neither" in fco["note"] and fco["source"].startswith("https://azoresairlines.pt")
    assert bad.is_error and "3-letter IATA" in bad.content[0].text


async def test_every_lounge_source_gives_its_rows_the_same_group_so_one_table_and_one_set_of_picks_come_out():
    from tests.test_loungepair import LIS_PAGE, TLV_PAGE  # noqa: F401  (the fake LoungePair pages)
    from myt_mcp.lounges.loungepair import offer_row, parse_lounge
    from myt_mcp.lounges.airlines import offer_azores, offer_tap
    lis = parse_lounge(LIS_PAGE, "/at/LIS/x/")
    rows = [offer_row(lis, "LIS", None), offer_azores(parse_azores(_text(AZORES))[0], "LIS"), offer_tap(parse_tap(_text(TAP))["own_lounges"][0], "LIS", 28.0)]
    assert len({r["group"] for r in rows}) == 1
    settings = Settings()
    async with Client(create_server(settings, Services(settings))) as c:
        out = (await c.call_tool("compose_answer", {"kind": "lounges", "offers": rows, "filters_used": ["Airport LIS (operator)"],
                                                     "sources_read": [{"name": r["source"], "read": 1, "of": 1, "link": r["link"]} for r in rows]})).structured_content
    assert out["ok"] and out["answer"].count("| Cheapest |") == 1 and out["answer"].count("### ") == 1
