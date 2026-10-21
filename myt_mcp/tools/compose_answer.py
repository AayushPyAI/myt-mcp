"""compose_answer: the final answer is built by the server from the rows Claude collected (see myt_mcp/compose.py)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import NotChecked, Offer, SourceRead, compose
from myt_mcp.recipes import offers_from_ratehawk, ratehawk_hotels_recipe
from myt_mcp.errors import tool_errors

Kind = Literal["flights", "hotels", "cars", "transfers", "trains", "activities", "lounges"]


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def compose_answer(kind: Kind, filters_used: list[str], sources_read: list[SourceRead], not_checked: list[NotChecked], offers: list[Offer],
                             myt_supplier: dict[str, str] | None = None, pickup_time: str | None = None, sorted_by_price: bool = True,
                             notes: str = "", ratehawk_results: list[str] | None = None, ratehawk_urls: list[str] | None = None,
                             hotel_wishes: dict[str, Any] | None = None) -> dict[str, Any]:
        """BUILD THE FINAL ANSWER with this tool for every price or comparison request and show its `answer` text as it is. Pass the rows you
        read (from the tools and the Chrome pages) as `offers`, the sources with how many you read (`read` of `of`) and their exact links,
        the sources you did not read with an allowed reason, the filters with their source (operator / trip / default), and the MYT supplier
        check per pick (`myt_supplier`, e.g. {"TAP AIR PORTUGAL": "yes"}). The server fills missing fields with "not shown", picks Cheapest, Best
        fit, Most flexible and Recommended by fixed rules (10% rule, one currency, quotable rows only), and writes the required lines and
        links. If something is missing it returns `problems`: fix them and call again. It reads no site and changes nothing."""
        offers = list(offers)
        sources_read = list(sources_read)
        if ratehawk_results:
            extra, src, problems, by_price = offers_from_ratehawk(ratehawk_results, ratehawk_urls or [], hotel_wishes, "Hotels")
            if problems:
                return {"ok": False, "problems": problems, "next": "Fix these (run the recipe again as the problem says) and call compose_answer again. Do not write the answer yourself."}
            offers += extra
            sources_read = [x for x in sources_read if x.name.lower() != "ratehawk"] + src
            sorted_by_price = by_price
        return compose(kind, filters_used, sources_read, not_checked, offers, myt_supplier or {}, pickup_time, sorted_by_price, notes)

    @mcp.tool(name="ratehawk_hotels_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_hotels_recipe_tool(country: str, city: str, check_in: date, check_out: date, adults: int = 2, sort: Literal["price_asc", "price_desc", "rating"] = "price_asc",
                                          breakfast: bool = False, free_cancellation: bool = False, stars: int | None = None, max_pages: int = 3,
                                          children_ages: list[int] | None = None) -> dict[str, Any]:
        """FOR HOTELS ON RATEHAWK: returns the exact results URL and a tested read-only SCRIPT for the operator's logged-in Chrome. Open the url with Claude in
        Chrome, run the script with the javascript tool (it reads every hotel card on `max_pages` pages, 20 a page, and checks the sort, the page and
        the count), then give its answer text unchanged to compose_answer (`ratehawk_results`, `ratehawk_urls`). Run it once with sort='price_asc' and
        once with sort='rating'. Never read the list by eye. `country` and `city` are the words in RateHawk's address (portugal, lisbon). Give `children_ages` for children."""
        return ratehawk_hotels_recipe(country, city, check_in, check_out, adults, sort, breakfast, free_cancellation, stars, max_pages, children_ages)
