"""Private airport and city transfers (Kiwitaxi)."""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.kiwitaxi.parse import check_results
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def _today() -> date:
    return date.today()


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def kiwitaxi_transfer_prices(from_place: str, to_place: str, travel_date: date, passengers: int = 2,
                                       from_match: int = 0, to_match: int = 0) -> dict[str, Any]:
        """Private transfer prices (airport to hotel, hotel to airport, city to city) from Kiwitaxi: every vehicle class with its
        price for the WHOLE vehicle one way in EUR, how many passengers and standard bags it takes, and its free-cancellation rule.
        `from_place` and `to_place` are free text: an airport name or code ("Fiumicino", "PDL"), a hotel name or a street address
        with the city ("Hotel Berchielli Florence"). The answer says which place Kiwitaxi matched for each (`matched_from`,
        `matched_to`, with address): check them against the trip's hotel, and if one is wrong call again with the next
        number in `from_match` / `to_match` (0 = first suggestion, `other_from` / `other_to` list the alternatives).
        `passengers` = everyone travelling (children included). The price does not depend on the pick-up time here; the time is
        chosen when booking. Nothing is booked."""
        if not from_place.strip() or not to_place.strip():
            raise ToolError("from_place and to_place need a place name, e.g. 'Fiumicino' and 'Room Mate Collection Mia Rome'.")
        if len(from_place) > 120 or len(to_place) > 120:
            raise ToolError("from_place and to_place are too long; use a short name or address.")
        if travel_date < _today():
            raise ToolError("travel_date is in the past.")
        if not 1 <= passengers <= 16:
            raise ToolError("passengers must be between 1 and 16.")
        if not 0 <= from_match <= 4 or not 0 <= to_match <= 4:
            raise ToolError("from_match and to_match must be between 0 and 4.")
        found = await services.kiwitaxi().search(from_place, to_place, travel_date, passengers, from_match, to_match)
        matched = {"matched_from": {"name": found["chosen_from"]["title"], "address": found["chosen_from"].get("address")},
                   "matched_to": {"name": found["chosen_to"]["title"], "address": found["chosen_to"].get("address")},
                   "other_from": found["other_from"], "other_to": found["other_to"]}
        if not found["offers"] and not found["route"]["date"]:
            return {"date": travel_date.isoformat(), "passengers": passengers, **matched, "offers": [], "source": found["url"],
                    "note": "Kiwitaxi shows no private transfer between these two places (for example a long ride to a village). Check that the places matched are the "
                            "right ones (`other_from` / `other_to` list the alternatives); if they are, Kiwitaxi cannot price this leg: ask the operator for another source."}
        ensure("Kiwitaxi", check_results(found, travel_date, passengers))
        offers = sorted([o for o in found["offers"] if o["price"] is not None], key=lambda o: (o["price"], -(o["max_passengers"] or 0)))
        fits = [o for o in offers if (o["max_passengers"] or 0) >= passengers]
        for o in offers:
            o["fits_group"] = (o["max_passengers"] or 0) >= passengers
        route = found["route"]
        answer: dict[str, Any] = {
            "date": travel_date.isoformat(), "passengers": passengers, "prices_are": "per vehicle (the whole group), one way, in EUR",
            **matched, "approx_driving_time": (route.get("driving_time") or "").replace("~", "").strip() or None, "offers": offers,
            "at_a_glance": {"cheapest_that_fits": fits[0] if fits else None,
                            "note": "Among the vehicles that take all passengers; luggage is not counted: check `max_standard_bags` against the group's bags."},
            "payment_note": "Kiwitaxi may ask for a small prepayment online and the rest in cash to the driver; the page's own wording decides: check it at booking.",
            "source": found["url"],
        }
        if not fits:
            answer["note"] = "No vehicle class on the page takes this many passengers; ask the operator about two vehicles."
        if route.get("to_address") and route["to_address"] != found["chosen_to"].get("address"):
            answer["page_destination"] = route["to_address"]
        return answer
