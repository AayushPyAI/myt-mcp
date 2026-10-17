"""MYT read tools: trips, itineraries, travellers and the selected quotation."""

from __future__ import annotations

from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.myt.summaries import quotation_summary, trip_summary, trips_list
from myt_mcp.services import Services

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


CONTACT_KEYS = {"email", "phone", "mobile", "telephone"}


def strip_contact_details(data: Any) -> Any:
    """Travellers' emails and phone numbers are not needed to build a quote, so they never reach Claude or the chat."""
    if isinstance(data, dict):
        return {k: strip_contact_details(v) for k, v in data.items() if k.lower() not in CONTACT_KEYS}
    if isinstance(data, list):
        return [strip_contact_details(v) for v in data]
    return data


def register(mcp: MCPServer, services: Services) -> None:
    async def trip_v3(trip_id: int, fresh: bool = False) -> dict[str, Any]:
        """The trip, after checking MYT answered with the trip that was asked for. `fresh` drops the cached copy first:
        use it right after a write made via Claude in Chrome (a screen edit this client did not make itself and so
        cannot know to invalidate), never for an ordinary read."""
        services.check_trip(trip_id)
        if fresh:
            services.myt().invalidate_trip_cache(trip_id)
        v3 = await services.myt().get_trip_v3(trip_id)
        got = (v3.get("trip") or {}).get("trip_id")
        ensure("MYT", [] if got == trip_id else [f"MYT returned trip {got} instead of {trip_id}"])
        return v3

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    async def find_trip(trip_number: str | None = None, name: str | None = None, from_date: date | None = None) -> Any:
        """Find an MYT trip. Use trip_number for the number shown in MYT (e.g. "906"); otherwise search by
        (part of) the trip name and/or a start date. Returns the internal trip_id that the other tools need."""
        if name and len(name) > 100:
            raise ToolError("name is too long; give a few words of the trip name.")
        if trip_number:
            if not trip_number.strip().isdigit():
                raise ToolError("trip_number must be the number shown in MYT, e.g. 906")
            trip = await services.myt().get_trip_by_number(trip_number.strip())
            services.check_trip(trip.get("trip_id"))
            return {
                "trip_id": trip.get("trip_id"),
                "number": trip.get("trip_number"),
                "name": trip.get("trip_name"),
                "start": (trip.get("trip_start") or "")[:10] or None,
                "end": (trip.get("trip_endtime") or "")[:10] or None,
            }
        if not (name and name.strip()) and not from_date:
            raise ToolError("Give trip_number, name or from_date")
        rows = trips_list(await services.myt().get_trips(name=name, from_date=from_date.isoformat() if from_date else None))
        allowed = services.settings.allowed_trip_ids
        return [r for r in rows if not allowed or r["trip_id"] in allowed]

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def get_trip(trip_id: int, fresh: bool = False) -> Any:
        """Read a trip by its internal trip_id (from find_trip; NOT the trip number shown in MYT): dates, travellers, the day-by-day itinerary with activities and
        suppliers, hotels, flights, the trip's suppliers, and which quotation is selected. Pass fresh=true to force a live
        read right after a change made via Claude in Chrome (the screen, not this connector): without it, a read within
        60 seconds of that change can still show the old data and wrongly look like the change did not take."""
        return trip_summary(await trip_v3(trip_id, fresh))

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    @with_checked_at
    async def get_quotation(trip_id: int, fresh: bool = False) -> Any:
        """Read the selected MYT quotation of a trip, by trip_id (from find_trip; NOT the trip number shown in MYT): every cost line (category, supplier, PP/PS, qty, nights,
        unit price and total, both including the line profit), the markups, and the totals MYT calculated
        (price per person and per group). Use it to check a quote and compare with calculate_quote. **Pass fresh=true when
        verifying a write just made through Claude in Chrome** (a quote-line edit, a margin, a publish price): the cache can
        serve a read within 60 seconds of a screen change that looks unchanged even though MYT already saved it (seen 17 Oct 2026,
        the Margin Prices "Markup" and publish-price save: both worked, but reading them back immediately, uncached, showed the old numbers)."""
        summary = quotation_summary(await trip_v3(trip_id, fresh))
        if summary is None:
            raise ToolError("This trip has no quotation yet.")
        return summary

    @mcp.tool(annotations=READ_ONLY)
    @tool_errors
    async def get_trip_participants(trip_id: int) -> Any:
        """List the travellers registered on a trip, by trip_id (from find_trip; NOT the trip number shown in MYT).
        Emails and phone numbers are removed on purpose; do not ask for them."""
        services.check_trip(trip_id)
        return strip_contact_details(await services.myt().get_participants(trip_id))
