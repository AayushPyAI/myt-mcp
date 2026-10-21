"""compose_answer: the final answer is built by the server from the rows Claude collected (see myt_mcp/compose.py)."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import NotChecked, Offer, SourceRead, compose
from myt_mcp.errors import tool_errors

Kind = Literal["flights", "hotels", "cars", "transfers", "trains", "activities", "lounges"]


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def compose_answer(kind: Kind, filters_used: list[str], sources_read: list[SourceRead], not_checked: list[NotChecked], offers: list[Offer],
                             myt_supplier: dict[str, str] | None = None, pickup_time: str | None = None, sorted_by_price: bool = True,
                             notes: str = "") -> dict[str, Any]:
        """BUILD THE FINAL ANSWER with this tool for every price or comparison request and show its `answer` text as it is. Pass the rows you
        read (from the tools and the Chrome pages) as `offers`, the sources with how many you read (`read` of `of`) and their exact links,
        the sources you did not read with an allowed reason, the filters with their source (operator / trip / default), and the MYT supplier
        check per pick (`myt_supplier`, e.g. {"TAP AIR PORTUGAL": "yes"}). The server fills missing fields with "not shown", picks Cheapest, Best
        fit, Most flexible and Recommended by fixed rules (10% rule, one currency, quotable rows only), and writes the required lines and
        links. If something is missing it returns `problems`: fix them and call again. It reads no site and changes nothing."""
        return compose(kind, filters_used, sources_read, not_checked, offers, myt_supplier or {}, pickup_time, sorted_by_price, notes)
