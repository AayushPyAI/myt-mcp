"""Flight tools: SATA (Azores Airlines S4 and SATA Air Açores SP) from SATA's own site, and Israir (Tel Aviv flights) from its public search."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.israir.parse import CITY_OF_AIRPORT, check_packages, parse_packages
from myt_mcp.labels import flights_glance
from myt_mcp.sata.client import search_link
from myt_mcp.sata.parse import check_answer, summarize_availability
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
AIRPORT = re.compile(r"^[A-Z]{3}$")


def _today() -> date:
    return date.today()


def _airport(value: str, what: str) -> str:
    code = (value or "").strip().upper()
    if not AIRPORT.match(code):
        raise ToolError(f"{what} must be an airport code like LIS, OPO or PDL.")
    return code


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
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
        result = summarize_availability(answer, max_results)
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


    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def israir_flight_prices(from_airport: str, to_airport: str, departure_date: date, adults: int = 2,
                                   child_ages: list[int] | None = None) -> dict[str, Any]:
        """Israir (Israeli airline) one-way flight prices between Tel Aviv (TLV) and the ~60 cities Israir sells (Rome, Milan,
        Verona, Porto, London, Athens, Budapest...), from israir.co.il's own public search: flight number, local departure and
        arrival times, the fare per passenger type and the TOTAL for the whole group, and what baggage is in the price. Prices
        are in USD (Israir's currency here): do not convert them yourself; say "USD" and let the operator decide. One of the two
        airports must be TLV. `child_ages` = each child's age on the flight (under 2 = infant). Give two searches for a
        return. Seats an agency holds as "batch" or block flights are NOT in this public search: if a trip's flight (for
        example 6H581) is not found, say so. Nothing is booked."""
        origin, destination = _airport(from_airport, "from_airport"), _airport(to_airport, "to_airport")
        from_city, to_city = CITY_OF_AIRPORT.get(origin, origin), CITY_OF_AIRPORT.get(destination, destination)
        child_ages = child_ages or []
        if "TLV" not in (from_city, to_city) or from_city == to_city:
            raise ToolError("Israir sells flights between Tel Aviv (TLV) and other cities: one of from_airport and to_airport must be TLV.")
        if departure_date < _today():
            raise ToolError("departure_date is in the past.")
        if (departure_date - _today()).days > 365:
            raise ToolError("Israir shows flights up to one year ahead; departure_date is later.")
        if not 1 <= adults <= 9 or len(child_ages) > 8 or adults + len(child_ages) > 9:
            raise ToolError("adults must be 1-9 and adults + children at most 9.")
        if any(not 0 <= a <= 17 for a in child_ages):
            raise ToolError("child_ages must be ages 0-17; put travellers aged 18+ in adults.")
        israir = services.israir()
        cities = await israir.cities()
        for name, city in ((origin, from_city), (destination, to_city)):
            if city not in cities:
                raise ToolError(f"Israir does not sell flights to or from {name} (city code {city}). Cities it sells: {', '.join(sorted(cities))}.")
        found = await israir.search(from_city, to_city, departure_date, adults, tuple(sorted(child_ages)))
        options = parse_packages(found)
        children = sum(1 for a in child_ages if a >= 2)
        ensure("Israir", check_packages(options, departure_date, adults, children, from_city, to_city))
        options.sort(key=lambda o: (o["price_total"] or 0, o["departure"] or ""))
        answer: dict[str, Any] = {
            "search": {"from": origin, "to": destination, "date": departure_date.isoformat(), "adults": adults, "child_ages": child_ages},
            "prices_are_for": "all passengers together, one way, in USD (Israir's own price; not converted)", "options": options,
            "source": options[0]["source"] if options else f"https://www.israir.co.il/he-IL/reservation/search/flights-abroad",
        }
        if options:
            cheapest = options[0]
            answer["at_a_glance"] = {"cheapest": {"flight_numbers": cheapest["flight_numbers"], "departure": cheapest["departure"], "price_total": cheapest["price_total"], "currency": cheapest["currency"]}}
            if not cheapest["baggage"]["checked_bag_included"]:
                answer["baggage_note"] = "A checked bag is not in the price; ask the operator whether the group needs one (its price is shown at booking)."
        else:
            answer["note"] = ("Israir's public search has no flight for this route and date. Block or batch seats held by the agency do not appear here: "
                              "ask the operator where that price comes from. Try nearby dates only if the operator agrees.")
        return answer
