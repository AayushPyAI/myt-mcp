"""compose_answer: the final answer is built by the server from the rows Claude collected (see myt_mcp/compose.py)."""

from __future__ import annotations

import logging
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import NotChecked, Offer, SourceRead, apply_wishes, compose
from myt_mcp.sites import convert_all, register_all
from myt_mcp.errors import tool_errors

log = logging.getLogger("myt_mcp")

Kind = Literal["flights", "hotels", "cars", "transfers", "trains", "activities", "lounges"]


def register(mcp: MCPServer) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def compose_answer(kind: Kind, site_results: list[dict[str, str]] | None = None, wishes: dict[str, Any] | None = None, filters_used: list[str] | None = None,
                             sources_read: list[SourceRead] | None = None, not_checked: list[NotChecked] | None = None, offers: list[Offer] | None = None,
                             myt_supplier: dict[str, str] | None = None, pickup_time: str | None = None, sorted_by_price: bool = True, notes: str = "",
                             ratehawk_results: list[str] | None = None, ratehawk_urls: list[str] | None = None, hotel_wishes: dict[str, Any] | None = None) -> dict[str, Any]:
        """BUILD THE FINAL ANSWER with this tool for every price or comparison request and show its `answer` text as it is; never write the table or the
        picks yourself. SHORTEST CALL for a Chrome site with a recipe: compose_answer(kind, site_results=[every part of every script answer, unchanged],
        wishes={...}, not_checked=[a source you could not read, with an allowed reason]); the server fills the rest and tells you in `problems` what is missing.
        Longer form: pass the rows you
        read (from the tools) as `offers`, the sources with how many you read (`read` of `of`) and their exact links, the sources you did not read
        with an allowed reason, the filters with their source (operator / trip / default), and the MYT supplier check per pick (`myt_supplier`,
        e.g. {"TAP AIR PORTUGAL": "yes"}). For a Chrome site that has a recipe tool (ratehawk_hotels_recipe, ...) pass the script's answer UNCHANGED in
        `site_results`: [{"site": "<recipe site name>", "result": "<script answer text>", "url": "<page url>"}]; the server turns it into rows itself.
        `wishes` = the operator's wishes ({"breakfast": true, "free_cancellation": true, "stars_min": 4}). The server fills missing fields with "not
        shown", picks Cheapest, Best fit, Most flexible and Recommended by fixed rules (10% rule, one currency, quotable rows only), and writes the
        required lines and links. If something is missing it returns `problems`: fix them and call again. It reads no site and changes nothing."""
        offers = list(offers or [])
        sources_read = list(sources_read or [])
        not_checked = list(not_checked or [])
        wishes = wishes or hotel_wishes
        if not filters_used and wishes:       # the operator's own wishes are the filters: no need to type them again
            filters_used = [f"{label} (operator)" for key, label in (("breakfast", "Breakfast included"), ("free_cancellation", "Free cancellation")) if wishes.get(key)]
            filters_used += [f"{wishes['stars_min']}+ stars (operator)"] if wishes.get("stars_min") else []
        filters_used = list(filters_used or [])
        items = list(site_results or [])
        for raw, url in zip(ratehawk_results or [], list(ratehawk_urls or []) + [""] * len(ratehawk_results or [])):     # the first version's parameters
            items.append({"site": "ratehawk_hotels", "result": raw, "url": url})
        if items:
            extra, srcs, problems, by_price, site_notes = convert_all(items, wishes or hotel_wishes)
            if problems:
                log.info("CHECK compose_answer site_results refused: %s", "; ".join(dict.fromkeys(problems))[:800])
                return {"ok": False, "problems": list(dict.fromkeys(problems)),
                        "next": "Fix these (run the recipe again as the problem says) and call compose_answer again. Do not write the answer yourself."}
            offers += extra
            names = {x.name.lower() for x in srcs}
            sources_read = [x for x in sources_read if x.name.lower() not in names] + srcs
            sorted_by_price = by_price
            if site_notes:
                notes = (notes + " " + " ".join(site_notes)).strip()
        apply_wishes(offers, wishes or hotel_wishes)
        out = compose(kind, filters_used, sources_read, not_checked, offers, myt_supplier or {}, pickup_time, sorted_by_price, notes)
        log.info("CHECK compose_answer kind=%s ok=%s items=%s offers=%s problems=%s", kind, out.get("ok"), [(i.get("site"), len(i.get("result", ""))) for i in items], len(offers),
                 "; ".join(out.get("problems", []))[:800])          # sizes and rule messages only, never the rows
        return out

    register_all(mcp)
