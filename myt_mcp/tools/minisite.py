"""Connect the customer mini-site after an MYT quote has been written."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.checks import ensure, with_checked_at
from myt_mcp.errors import tool_errors
from myt_mcp.myt.summaries import quotation_summary
from myt_mcp.services import Services

WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def register(mcp: MCPServer, services: Services) -> None:
    @mcp.tool(annotations=WRITE)
    @tool_errors
    @with_checked_at
    async def update_minisite(trip_id: int, version: str | int | None = None, confirm: bool = False) -> dict[str, Any]:
        """Call the Selected Places mini-site webhook after a quote has been written in MYT. It syncs the trip, generates
        the customer trip page (and FillFaster form), can forward details to Salesforce and can email the customer.
        Use trip_id from find_trip (the internal MYT id, NOT the trip number shown in MYT). `version` is the quotation
        version; omit it to send the trip's currently selected quotation version (the webhook fetches the latest if MYT
        has none). Without confirm=true this only shows what would be sent and changes nothing: show it to the operator
        first. After they explicitly say the quote is ready and to connect/update the mini-site, call again with
        confirm=true. Never report a link as live unless this tool returned sent=true and a trip_url. Only trips in
        If ALLOWED_TRIP_IDS lists trips only those can be touched; when it is empty, any trip the operator names."""
        services.check_trip(trip_id)
        v3 = await services.myt().get_trip_v3(trip_id)
        got = (v3.get("trip") or {}).get("trip_id")
        ensure("MYT", [] if got == trip_id else [f"MYT returned trip {got} instead of {trip_id}"])
        quote = quotation_summary(v3)
        if quote is None:
            raise ToolError("This trip has no quotation yet. Write the quote in MYT first, then call update_minisite.")
        sending_version = quote["version"] if version is None or str(version).strip() == "" else version
        preview = {
            "webhook": services.settings.minisite_webhook_url,
            "trip_id": trip_id,
            "trip_number": (v3.get("trip") or {}).get("number"),
            "quotation_number": quote.get("number"),
            "version": sending_version,
            "quotation_status": quote.get("status"),
        }
        if not confirm:
            return {**preview, "sent": False,
                    "note": "Nothing was sent. The webhook can email the customer. Show this to the operator; call again "
                            "with confirm=true only after they say the quote is ready and to update the mini-site."}
        data = await services.minisite().generate_trip_link(trip_id, sending_version)
        trip_url = data.get("trip_url") or ""
        return {**preview, "sent": True, "status": data.get("status"), "message": data.get("message"),
                "trip_url": trip_url, "customer_link": trip_url}
