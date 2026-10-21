"""The playbook tool: the detailed operator rules for one topic."""

from __future__ import annotations

from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.errors import tool_errors
from myt_mcp.guide import sections

Topic = Literal["workflow", "capabilities", "cost_lines", "myt_filling", "reservations", "cars", "website_rules", "trains", "flights", "lounges", "hotels",
                "filters", "transfers", "other_sources", "activities", "versions", "correct_data", "source_data", "comparison", "answer_format", "rules"]


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def quote_guide(topic: Topic) -> str:
        """CALL THIS FIRST for any travel price or availability request (hotels, cars, trains, flights, lounges, activities,
        transfers), even when the operator names a website or says to use the browser: it says which source and tool to use.
        The Selected Places playbook for one topic. Read "workflow", "correct_data" and "answer_format" at the start of a quote, "comparison" before you compare options or sources,
        and the topic's section before pricing it: cost_lines (how to fill MYT lines), cars, website_rules,
        trains, flights, lounges, hotels (RateHawk/Arbitrip in Chrome), filters (the filters to apply on RateHawk, Arbitrip and Ofran: read before a hotel or car search), transfers (Kiwitaxi, Mozio), source_data (the fields to read from each source: availability, price, booking conditions), other_sources (sites
        without a tool, e.g. Tripadvisor, Booking.com), activities (GetYourGuide + Viator),
        capabilities (READ FIRST when asked "can you ... in MYT?": statuses, vouchers, uploads, margins, commissions, emails),
        myt_filling (writing lines into MYT with Claude in Chrome), reservations (supplier reservations, vouchers, reconciliation), versions (comparing quotation V1/V2), rules."""
        text = sections().get(topic)
        if not text:
            raise ToolError(f"The playbook has no section for {topic!r}.")
        return text

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def connector_capabilities() -> str:
        """CALL THIS FIRST when the operator asks what this connector or MYT can or cannot do: "can you change a status,
        upload a voucher or file, edit margins or commissions, delete, send an email, change the trip status?". It returns the
        exact list: what a tool does, what only Claude in Chrome does on the MYT screen, what was never tested and what is never
        done. Answer such questions only from it, never from the other tools' names (for example update_supplier_reservation
        does NOT change a status and nothing here uploads a file). Not for price or availability questions."""
        return sections()["capabilities"]
