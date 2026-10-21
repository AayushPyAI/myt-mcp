"""Ofran car rental tools."""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.labels import cars_glance
from myt_mcp.ofran.offers import Transmission, check_offers, summarize_offers
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def register(mcp: MCPServer, services: Services) -> None:
    async def resolve(query: str, what: str):
        if not query or not query.strip():
            raise ToolError(f"{what} is empty.")
        matches = await services.ofran().find_locations(query, limit=4)
        if not matches:
            raise ToolError(f"No Ofran location matches {query!r}. Try the city name, the airport name or its IATA code (ofran_find_location).")
        return matches[0], matches[1:]

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    async def ofran_find_location(query: str) -> list[dict[str, Any]]:
        """Find Ofran pick-up/drop-off points by city, airport name or IATA code (e.g. "Lisbon", "LIS",
        "Florence"). Airports come first. Pass the exact `name` to ofran_car_prices. NOTE: Ofran blocks this server (HTTP 403 from
        India) and the agency's price is the net price in the operator's logged-in Chrome: search cars there first (quote_guide('cars'))."""
        if not query or not query.strip():
            raise ToolError("query is empty.")
        return [loc.public() for loc in await services.ofran().find_locations(query)]

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def ofran_car_prices(
        location: str,
        pickup_date: date,
        dropoff_date: date,
        pickup_time: str = "10:00",
        dropoff_time: str = "10:00",
        dropoff_location: str | None = None,
        driver_age: int | None = None,
        transmission: Transmission = "any",
        max_results: int = 15,
    ) -> dict[str, Any]:
        """Rental car prices, FALLBACK ONLY: for car hire questions first search Ofran in the operator's logged-in Chrome (Claude in Chrome, quote_guide('cars')) and read RateHawk Car rental there; this server tool is blocked by Ofran from India (HTTP 403) and gives only the public price, so do not rely on it or explain the 403 as a fault of the operator. Live car rental offers from Ofran for one rental, cheapest first. `location` is an Ofran point
        name or code (check with ofran_find_location when unsure). Prices are Ofran's PUBLIC website price (this server's browser is not logged in, so it is not the agency's net price; for the net price use the operator's logged-in Chrome, see quote_guide('cars'))
        for the whole rental in the listed currency, with insurance excess, deposit and optional extras.
        Each call runs one search on Ofran: don't repeat it for the same dates."""
        if pickup_date < date.today():
            raise ToolError("pickup_date is in the past.")
        if dropoff_date <= pickup_date:
            raise ToolError("dropoff_date must be after pickup_date.")
        for label, value in (("pickup_time", pickup_time), ("dropoff_time", dropoff_time)):
            if not TIME.match(value):
                raise ToolError(f"{label} must look like 10:00 (24-hour HH:MM).")
        if driver_age is not None and not 18 <= driver_age <= 99:
            raise ToolError("driver_age must be between 18 and 99.")
        if not 1 <= max_results <= 50:
            raise ToolError("max_results must be between 1 and 50.")

        pickup, others = await resolve(location, "location")
        dropoff = (await resolve(dropoff_location, "dropoff_location"))[0] if dropoff_location else pickup
        result = await services.ofran().search(pickup, dropoff, pickup_date, dropoff_date, pickup_time, dropoff_time, driver_age)
        summary = summarize_offers(result, transmission, max_results)
        ensure("Ofran", check_offers(summary.cars))

        answer: dict[str, Any] = {
            "pickup": {**pickup.public(), "date": pickup_date.isoformat(), "time": pickup_time},
            "dropoff": {**dropoff.public(), "date": dropoff_date.isoformat(), "time": dropoff_time},
            "rental_days": (dropoff_date - pickup_date).days,
            "offers_found": summary.total,
            "cars": summary.cars,
            "at_a_glance": cars_glance(summary.cars),
        }
        if others:
            answer["other_matching_locations"] = [o.name for o in others]
        if summary.total == 0:
            answer["note"] = "Ofran has no cars for this location and these dates" + (f" with {transmission} transmission" if transmission != "any" else "") + "."
        if summary.skipped:
            answer["warning"] = f"{summary.skipped} offers were left out because Ofran sent them in an unexpected format."
        return answer
