"""Flight tools: SATA (Azores Airlines S4 and SATA Air Açores SP) from SATA's own site."""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.labels import flights_glance
from myt_mcp.sata.client import search_link
from myt_mcp.tap.parse import check_availability as check_tap, parse_availability as parse_tap, split_by_origin
from myt_mcp.sata.parse import check_answer, summarize_availability
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
AIRPORT = re.compile(r"^[A-Z]{3}$")


def found_link(origin: str, destination: str, day: date, adults: int, children: int, infants: int) -> str:
    from myt_mcp.tap.client import search_link as tap_link
    return tap_link(origin, destination, day, adults, children, infants)


def _today() -> date:
    return date.today()


def _airport(value: str, what: str) -> str:
    code = (value or "").strip().upper()
    if not AIRPORT.match(code):
        raise ToolError(f"{what} must be an airport code like LIS, OPO or PDL.")
    return code


def register(mcp: MCPServer, services: Services) -> None:
    # TAP and SATA are read with Claude in Chrome (tap_recipe, sata_recipe: the operator's own browser, ask-first). The server-browser tools below stay in the code
    # but are OFF unless TAP_SERVER_BROWSER=1 / SATA_SERVER_BROWSER=1; the old names stay known as pointers (claude.ai keeps the tool list it saw when the connector was added).
    tap_live, sata_live = os.environ.get("TAP_SERVER_BROWSER") == "1", os.environ.get("SATA_SERVER_BROWSER") == "1"

    def live(enabled: bool):
        def decorate(fn):
            return mcp.tool(annotations=READ_ONLY)(fn) if enabled else fn
        return decorate

    @live(sata_live)
    @tool_errors
    @with_checked_at
    async def sata_flight_prices(
        from_airport: str,
        to_airport: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 2,
        children: int = 0,
        infants: int = 0,
        max_results: int = 10,
    ) -> dict[str, Any]:
        """Flight prices to, from and between the Azores (the only airline source built; for other airlines use other_source_prices). Live SATA fares from azoresairlines.pt: Azores Airlines (S4: Lisbon, Porto, other gateways <-> Azores)
        and SATA Air Açores (SP: between the islands PDL, TER, HOR, PIX, SJZ, GRW, FLW, CVU, SMA).
        Airports are IATA codes. children = ages 2-11, infants = under 2. Give `return_date` for a round trip
        (often cheaper than two one-ways). Each option shows the flights per direction, the cheapest fare,
        the TOTAL for all passengers (and per passenger type), and what every fare costs on those flights
        (price_by_fare). fare_conditions explains each fare: bags, changes, refund. Nothing is booked."""
        origin, destination = _airport(from_airport, "from_airport"), _airport(to_airport, "to_airport")
        if origin == destination:
            raise ToolError("from_airport and to_airport are the same.")
        if departure_date < date.today():
            raise ToolError("departure_date is in the past.")
        if return_date and return_date < departure_date:
            raise ToolError("return_date is before departure_date.")
        if not 1 <= adults <= 9 or not 0 <= children <= 8 or not 0 <= infants <= adults or adults + children > 9:
            raise ToolError("adults must be 1-9, children 0-8 (at most 9 seats in all), and infants at most one per adult.")
        if not 1 <= max_results <= 15:
            raise ToolError("max_results must be between 1 and 15.")
        answer = await services.sata().search(origin, destination, departure_date, return_date, adults, children, infants)
        ensure("SATA", check_answer(answer, origin, destination, departure_date.isoformat(),
                                    return_date.isoformat() if return_date else None,
                                    {"adults": adults, "children": children, "infants": infants}))
        result = summarize_availability(answer, max_results, {"adults": adults, "children": children, "infants": infants})
        reply: dict[str, Any] = {
            "search": {"from": origin, "to": destination, "departure_date": departure_date.isoformat(),
                       "return_date": return_date.isoformat() if return_date else None,
                       "adults": adults, "children": children, "infants": infants},
            "prices_are_for": f"all passengers together, in {result['currency'] or 'EUR'}",
            "source": search_link(origin, destination, departure_date, return_date, adults, children, infants),
            **result,
        }
        reply["at_a_glance"] = flights_glance(result["options"])
        if not result["options"]:
            reply["note"] = "SATA has no flights with seats for this route and date. Try nearby dates or another route."
        messages = [m.get("text") or m.get("code") for m in answer.get("messages") or [] if isinstance(m, dict)]
        if messages:
            reply["sata_messages"] = messages
        return reply


    @live(tap_live)
    @tool_errors
    @with_checked_at
    async def tap_flight_prices(from_airport: str, to_airport: str, departure_date: date, adults: int = 2, child_ages: list[int] | None = None,
                                max_results: int = 8, sort_by: str = "price", direct_only: bool = False, max_price: float | None = None,
                                checked_bag_only: bool = False, refundable_only: bool = False) -> dict[str, Any]:
        """TAP Air Portugal (and its partners) one-way flight prices in EUR, read from TAP's own booking page (it takes ~20 s): every
        flight of the day with its segments (flight number, local times, aircraft, who operates it), stops and duration, and for each flight
        its fares (fare code, TOTAL for the whole group, per passenger type, whether a checked bag is included, whether it is refundable,
        seats left). Airports are IATA codes (FLR, LIS, OPO, FAO, PDL...). `child_ages` = each child's age on the flight (under 2 = infant,
        2-11 = child, 12+ counts as an adult). Choose from the traveller's wishes: sort_by "price" (default), "departure" or "duration";
        direct_only; max_price (whole group, EUR, on a fare); checked_bag_only (fares with a checked bag); refundable_only. The answer says how many
        flights were read and how many are shown. Offers that start at another place (for example a train leg from a station) are listed
        apart in `other_origin_offers`. Give two searches for a return. Nothing is booked."""
        origin, destination = _airport(from_airport, "from_airport"), _airport(to_airport, "to_airport")
        child_ages = child_ages or []
        if origin == destination:
            raise ToolError("from_airport and to_airport are the same.")
        if departure_date < _today():
            raise ToolError("departure_date is in the past.")
        if (departure_date - _today()).days > 360:
            raise ToolError("TAP shows flights up to about a year ahead; departure_date is later.")
        if any(not 0 <= a <= 17 for a in child_ages):
            raise ToolError("child_ages must be ages 0-17; put travellers aged 18+ in adults.")
        infants, children = sum(1 for a in child_ages if a < 2), sum(1 for a in child_ages if 2 <= a < 12)
        adults += sum(1 for a in child_ages if a >= 12)
        if not 1 <= adults <= 9 or adults + children > 9 or infants > adults:
            raise ToolError("adults must be 1-9 (travellers aged 12+), adults + children at most 9, and infants at most one per adult.")
        if not 1 <= max_results <= 20:
            raise ToolError("max_results must be between 1 and 20.")
        if sort_by not in ("price", "departure", "duration"):
            raise ToolError("sort_by must be one of: price, departure, duration.")
        if max_price is not None and max_price <= 0:
            raise ToolError("max_price must be more than 0 (EUR, whole group).")
        found = await services.tap().search(origin, destination, departure_date, adults, children, infants)
        parsed = parse_tap(found)
        ensure("TAP", check_tap(parsed, origin, destination, departure_date, adults, children, infants, "EUR"))
        flights, elsewhere = split_by_origin(parsed, origin)
        read = len(flights)

        def keep(fare: dict[str, Any]) -> bool:
            return ((max_price is None or (fare["price_total"] is not None and fare["price_total"] <= max_price))
                    and (not checked_bag_only or fare["checked_bag_included"] is True) and (not refundable_only or fare["refundable"] is True))

        shown = []
        for fl in flights:
            if direct_only and fl["stops"] != 0:
                continue
            fares = [f for f in fl["fares"] if keep(f)]
            if fares:
                shown.append({**fl, "fares": fares, "cheapest_total": fares[0]["price_total"]})
        key = {"price": lambda f: (f["cheapest_total"], f["duration_minutes"] or 0), "departure": lambda f: f["segments"][0]["departure"] or "",
               "duration": lambda f: (f["duration_minutes"] or 10 ** 6, f["cheapest_total"])}[sort_by]
        shown.sort(key=key)
        rows = [{"rank": n, **f} for n, f in enumerate(shown[:max_results], 1)]
        answer: dict[str, Any] = {
            "search": {"from": origin, "to": destination, "date": departure_date.isoformat(), "adults": adults, "children": children, "infants": infants},
            "prices_are_for": "all passengers together, one way, in EUR", "sorted_by": sort_by,
            "filters": {"direct_only": direct_only, "max_price": max_price, "checked_bag_only": checked_bag_only, "refundable_only": refundable_only},
            "coverage": {"flights_read": read, "passed_filters": len(shown), "shown": len(rows), "other_origin_offers": len(elsewhere)},
            "flights": rows, "source": found_link(origin, destination, departure_date, adults, children, infants),
        }
        cheapest = min((f for f in shown), key=lambda f: f["cheapest_total"], default=None)
        with_bag = min(((f, fare) for f in shown for fare in f["fares"] if fare["checked_bag_included"]), key=lambda x: x[1]["price_total"], default=None)
        answer["at_a_glance"] = {
            "cheapest": cheapest and {"flights": "+".join(s["flight"] for s in cheapest["segments"]), "departure": cheapest["segments"][0]["departure"], "price_total": cheapest["cheapest_total"]},
            "cheapest_with_checked_bag": with_bag and {"flights": "+".join(s["flight"] for s in with_bag[0]["segments"]), "departure": with_bag[0]["segments"][0]["departure"],
                                                      "fare_code": with_bag[1]["fare_code"], "price_total": with_bag[1]["price_total"]},
            "note": "Cheapest among the flights read; the cheapest fare often has no checked bag and no refund: see each fare's flags.",
        }
        if elsewhere:
            answer["other_origin_offers"] = [{"from": f["segments"][0]["from"], "flights": "+".join(s["flight"] for s in f["segments"]), "departure": f["segments"][0]["departure"],
                                              "arrival": f["segments"][-1]["arrival"], "cheapest_total": f["cheapest_total"]} for f in elsewhere[:5]]
            answer["other_origin_note"] = (f"{len(elsewhere)} offers start from another place than {origin} (for example a train leg from a station such as ZMS = Florence station); "
                                           "they are not flights from the airport you asked for. Mention them only if the operator is open to it.")
        if not rows:
            answer["note"] = ("TAP shows no flight on this route and date." if not read else
                              "None of the flights read passes the filters; say so and offer a higher price, a stop or no bag filter.")
        return answer

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def tap_fare_calendar(from_airport: str, to_airport: str, year: int, month: int) -> dict[str, Any]:
        """TAP's fare calendar for a route and month: the lowest one-way economy price of each day, per ADULT, in USD (TAP's calendar
        currency), from flytap.com (fast, no browser). It is TAP's cached "lowest price" reference, not a live fare for a group:
        use it to pick a cheap day, then call tap_flight_prices for that day for the real flights and the group total in EUR."""
        origin, destination = _airport(from_airport, "from_airport"), _airport(to_airport, "to_airport")
        today = _today()
        if not 1 <= month <= 12 or not today.year <= year <= today.year + 1 or (year, month) < (today.year, today.month):
            raise ToolError("year and month must be this month or a later one within about a year.")
        found = await services.tap().calendar(origin, destination, year, month)
        days = [{"date": d["departureDate"][:10], "lowest_price_per_adult": d.get("bestTotalPrice") or None, "sold_out": bool(d.get("soldOut")), "no_flights": bool(d.get("noFlights")),
                 "price_checked_on": (d.get("insertionDate") or "")[:10] or None} for d in found["days"] if isinstance(d, dict) and d.get("departureDate")]
        priced = [d for d in days if d["lowest_price_per_adult"]]
        answer: dict[str, Any] = {"route": f"{origin}-{destination}", "month": f"{year}-{month:02d}", "prices_are": "lowest one-way economy price per adult, in USD, from TAP's cached calendar (indicative, not live)",
                                  "days": days, "source": "https://www.flytap.com/en-us"}
        if priced:
            cheapest = min(priced, key=lambda d: d["lowest_price_per_adult"])
            answer["cheapest_day"] = {"date": cheapest["date"], "lowest_price_per_adult": cheapest["lowest_price_per_adult"]}
        else:
            answer["note"] = "TAP's calendar shows no price for this route and month; the route may not be flown, or TAP has no fares loaded yet."
        return answer

    if not tap_live:
        @mcp.tool(annotations=READ_ONLY)
        @tool_errors
        async def tap_flight_prices(from_airport: str, to_airport: str, departure_date: date, adults: int = 2, child_ages: list[int] | None = None, max_results: int = 8,
                                    sort_by: str = "price", direct_only: bool = False, max_price: float | None = None, checked_bag_only: bool = False,
                                    refundable_only: bool = False) -> dict[str, Any]:
            """NOT USED in this setup (TAP is read with Claude in Chrome): call tap_recipe with the same values. It asks the operator first."""
            return {"ok": False, "searched": False, "next": "This tool is off. Call tap_recipe with the same airports, date and travellers (it asks direct only, checked bag and refundable first, "
                                                             "then gives the url and the script for Claude in Chrome). tap_fare_calendar still works for the cheapest days."}

    if not sata_live:
        @mcp.tool(annotations=READ_ONLY)
        @tool_errors
        async def sata_flight_prices(from_airport: str, to_airport: str, departure_date: date, return_date: date | None = None, adults: int = 2, children: int = 0,
                                     infants: int = 0, max_results: int = 10) -> dict[str, Any]:
            """NOT USED in this setup (SATA / Azores Airlines is read with Claude in Chrome): call sata_recipe with the same values, one call per leg. It asks the operator first."""
            return {"ok": False, "searched": False, "next": "This tool is off. Call sata_recipe once per leg with the same airports, date and travellers (it asks direct only, checked bag and refundable "
                                                             "first, then gives the url and the script for Claude in Chrome). For a round trip call it for each leg."}
