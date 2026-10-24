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
from myt_mcp.lounges.airlines import azores_rows, offer_azores, offer_tap, tap_rows
from myt_mcp.lounges.loungepair import SITE as LOUNGEPAIR_SITE
from myt_mcp.lounges.loungepair import hours_note, offer_row
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

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def loungepair_lounges(airport: str, flight_departure: datetime | None = None) -> dict[str, Any]:
        """Airport lounge access on LoungePair (one-time passes; a comparison source next to `lounge_prices`, and the only one for airports Aspire does not serve). `airport` is the 3-letter
        IATA code (LIS, TLV, FCO...). Returns each lounge LoungePair lists there: name, terminal, opening hours, the LOWEST price per person in EUR ("from" price, not the price for the
        flight or the group), the FlexiPass extra (change or cancel unused passes), and the notices the page shows (for example "temporarily closed for renovation": always say it).
        Every row is a comparison, never a quote: the exact price is in LoungePair's booking widget. Each lounge comes with a ready `offer` row: pass it to compose_answer(offers=[...]) AS IT IS and never multiply the price by the group or reword it. Give `flight_departure` (the flight's local date and time) to get the boarding note: leave the lounge 45 minutes before departure. Nothing is booked."""
        iata = airport.strip().upper()
        lounges = await services.loungepair().lounges(iata)
        flight_at = flight_departure.replace(tzinfo=None) if flight_departure else None
        answer: dict[str, Any] = {"airport": iata, "comparison_only": True, "lounges": [
            {**lounge, "price_kind": "'from' price per person in EUR, the lowest LoungePair sells at any date; not a price for this flight or group", "quotable": False,
             "offer": offer_row(lounge, iata, flight_at), "boarding_note": hours_note(lounge.get("opening_hours"), flight_at)} for lounge in lounges]}
        if not lounges:
            answer["note"] = "LoungePair lists no lounge at this airport."
            answer["source"] = f"{LOUNGEPAIR_SITE}/at/{iata}/"
            return answer
        answer["source"] = lounges[0]["url"]
        if any(lounge["closed"] for lounge in lounges):
            answer["warning"] = "A lounge here is marked closed on its LoungePair page: say so and do not offer it as an option."
        children = next((lounge["children"] for lounge in lounges if lounge["children"]), None)
        if children:
            answer["age_rules"] = children
        return answer

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def airline_lounges(airport: str) -> dict[str, Any]:
        """Lounge access the AIRLINES sell, from their own public pages: Azores Airlines (its lounge prices per airport, e.g. the ANA Lounge at LIS, OPO, FAO) and TAP Air Portugal (the lounges TAP
        runs, e.g. TAP Premium Lounge Tejo and Atlântico at Lisbon, with opening hours and capacity, and TAP's 'from' price). `airport` is the 3-letter IATA code. Next to `lounge_prices` and
        `loungepair_lounges`. Every lounge comes with a ready `offer` row for compose_answer(offers=[...]): pass it AS IT IS. They are comparison rows: the Azores price is sold with an Azores Airlines
        flight booking and the TAP price with a TAP booking, and neither page lists who flies free (fare, status or card). Nothing is booked."""
        iata = airport.strip().upper()
        if len(iata) != 3 or not iata.isalpha():
            raise ToolError("Give the 3-letter IATA code of the airport (LIS, OPO, FAO...).")
        azores = azores_rows(await services.airline_lounges().azores(), iata)
        tap = await services.airline_lounges().tap()
        own = tap_rows(tap, iata)
        lounges = [{"source": "Azores Airlines", **row, "offer": offer_azores(row, iata)} for row in azores] + \
                  [{"source": "TAP Air Portugal", **row, "from_price_eur": tap["from_price_eur"], "offer": offer_tap(row, iata, tap["from_price_eur"])} for row in own]
        answer: dict[str, Any] = {"airport": iata, "comparison_only": True, "lounges": lounges}
        if not lounges:
            answer["note"] = "Neither Azores Airlines nor TAP lists a lounge of its own at this airport."
            answer["source"] = "https://azoresairlines.pt/en/information/before-boarding/lounges"
            return answer
        answer["source"] = lounges[0]["url"]
        if own:
            answer["tap_price_note"] = tap["price_note"]
        return answer
