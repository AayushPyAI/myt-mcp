"""Airport lounge tools (Aspire Lounges)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.lounges.aspire import SITE
from myt_mcp.lounges.parse import check_rates, match_airport, summarize_rates
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def lounge_prices(airport: str, flight_departure: datetime, adults: int = 2, children: int = 0,
                            infants: int = 0) -> dict[str, Any]:
        """Airport lounge price or access question (טרקלין): Aspire lounge prices at an airport for a flight: lounge name and location, the entry and exit time
        (usually up to 2-3 hours before the flight), the price per ticket (Adult, Child, Infant) and the total for
        the group, in EUR. `airport` is an IATA code (TLV, VCE, VRN, AMS...) or a name ("Ben Gurion", "Venice").
        `flight_departure` is the flight's local departure date and time. Nothing is booked."""
        if flight_departure.replace(tzinfo=None) < datetime.now():
            raise ToolError("flight_departure is in the past.")
        if not 0 <= adults <= 9 or not 0 <= children <= 9 or not 0 <= infants <= 9 or adults + children + infants == 0:
            raise ToolError("adults, children and infants must be 0-9 each, with at least one traveller.")
        if not airport or not airport.strip():
            raise ToolError("airport is empty.")
        aspire = services.aspire()
        airports = await aspire.airports()
        matches = match_airport(airport, airports)
        if not matches:
            return {"airport": airport, "lounges": [],
                    "note": "Aspire has no lounge at this airport. Ask the operator about other lounge providers there.",
                    "source": f"{SITE}/airports/",      # the page that lists the airports Aspire serves: the link the answer needs
                    "next": "Put Aspire Lounges in not_checked with the reason 'route not served: Aspire has no lounge at this airport' (never '0 of 0 lounges checked'), link the source above, and say which airports Aspire does serve if the operator asks.",
                    "aspire_airports": [a.replace("-", " ") for a in airports]}
        if len(matches) > 1:
            raise ToolError(f"{airport!r} matches several Aspire airports: {', '.join(matches)}. Use the IATA code or a fuller name.")
        group = {"adults": adults, "children": children, "infants": infants}
        lounges = []
        for lounge in await aspire.lounges(matches[0]):
            rates = await aspire.rates(lounge["lounge_id"], flight_departure.replace(tzinfo=None))
            ensure("Aspire", check_rates(rates, flight_departure.strftime("%Y-%m-%dT%H:%M")))
            lounges.append({**lounge, **summarize_rates(rates, group)})
        answer: dict[str, Any] = {"airport": matches[0].replace("-", " "), "flight_departure": flight_departure.strftime("%Y-%m-%d %H:%M"),
                                  "travellers": group, "lounges": lounges}
        if lounges and lounges[0].get("url"):
            answer["source"] = lounges[0]["url"]            # the lounge page: where prices and age rules can be checked
        if not lounges:
            answer["note"] = "Could not read the lounges on this airport's Aspire page; check the website."
        if children or infants:
            answer["age_rules"] = "Aspire's child and infant ages differ by lounge; check the lounge page before quoting."
        return answer
