"""Arbitrip hotel page: the rooms of ONE hotel with their cancellation and meal plan (a site module, see myt_mcp/sites/__init__.py).

The results list shows only the cheapest room of a hotel, which can be non-refundable. This reads the room table of the hotel the operator picked, so free cancellation
and breakfast are confirmed per room. Rooms are quotable; the cheapest room that meets the wishes is the offer, the cheapest room overall is told in a note.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer, meets_limits
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, with_emit
from myt_mcp.sites.arbitrip_hotels import known_places
from myt_mcp.sites.ratehawk_hotels import limits

NAME = "arbitrip_rooms"
SOURCE = "Arbitrip hotel page"      # its own line in "Sources checked": the list rows and the room tables are different reads
GROUP = "Hotels"
HERE = Path(__file__).parent
ORIGIN = "https://app.arbitrip.com"


def arbitrip_rooms_recipe(city: str, check_in: date, check_out: date, adults: int = 2, place_id: str | None = None, children_ages: list[int] | None = None) -> dict[str, Any]:
    if check_out <= check_in:
        raise ValueError("check_out must be after check_in")
    pid = place_id or known_places().get(re.sub(r"\s+", " ", city.strip().lower()))
    contract = os.environ.get("ARBITRIP_CONTRACT_ID", "").strip()
    if not pid or not contract:
        return {"error": "the place id or the agency contract id is not known: call arbitrip_hotels_recipe first (it explains how to learn them)"}
    expect = {"check_in": f"{check_in:%y%m%d}", "check_out": f"{check_out:%y%m%d}", "guests": str(adults)}
    ages = list(children_ages or [])
    if ages:
        expect |= {"children": str(len(ages)), "children_ages": ",".join(str(a) for a in ages)}
    script = with_emit((HERE / "arbitrip_rooms.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps(expect))
    query = f"place_id={pid}&check_in={expect['check_in']}&check_out={expect['check_out']}&guests={adults}" + (f"&children={len(ages)}&children_ages={','.join(str(a) for a in ages)}" if ages else "") + f"&rooms=1&contract_id={contract}"
    return {"script": script, "expect": expect, "link_query": query}


def _int(text: Any) -> int | None:
    m = re.search(r"[\d,]+", str(text or ""))
    return int(m.group(0).replace(",", "")) if m else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Arbitrip rooms result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Arbitrip rooms script reported: {data.get('error', 'not ok')}"])
    hotel = data.get("hotel") or "Arbitrip hotel"
    link = ORIGIN + data["hotel_path"] + ("?" + wishes["arbitrip_link_query"] if wishes.get("arbitrip_link_query") else "") if data.get("hotel_path") else None
    rooms = [r for r in data.get("rows", []) if r.get("price") is not None]
    problems: list[str] = []
    if data.get("price_order") == "not ascending":
        problems.append("the Arbitrip room prices are not in ascending order: the page may have changed while reading")

    def fits(r: dict[str, Any]) -> bool:
        ok = True
        if wishes.get("breakfast"):
            ok &= bool(re.search(r"breakfast|half board|full board|all inclusive", r.get("meal") or "", re.I))
        if wishes.get("free_cancellation"):
            ok &= (r.get("cancellation") or "").lower().startswith("free cancellation")
        if wishes.get("stars_min"):
            ok &= bool(data.get("stars")) and data["stars"] >= int(wishes["stars_min"])
        return ok and meets_limits(r["price"], data.get("distance"), wishes)

    def offer(r: dict[str, Any], ok: bool | None) -> Offer:
        free = (r.get("cancellation") or "").lower().startswith("free cancellation")
        return Offer(group=group, source=SOURCE, name=f"{hotel} - {r.get('room')}", price_total=r["price"], currency="EUR", price_basis="whole stay, tax included",
                     details={"stars": data.get("stars"), "score": data.get("score"), "reviews": _int(data.get("reviews")), "distance_from_centre": data.get("distance"),
                              "meal": r.get("meal"), "cancellation": r.get("cancellation"), "room_bed": r.get("room")},
                     flexible=free or None, fits=ok if wishes else None, supplier=hotel, link=link)

    best = next((r for r in sorted(rooms, key=lambda r: r["price"]) if fits(r)), None) if wishes else (min(rooms, key=lambda r: r["price"]) if rooms else None)
    offers = [offer(best, True if wishes else None)] if best else []
    notes: list[str] = []
    if rooms:
        cheapest = min(rooms, key=lambda r: r["price"])
        if best is None:
            notes.append(f"{hotel}: none of its {len(rooms)} rooms meets every wish of the operator; its cheapest room is {cheapest['price']:g} EUR ({cheapest.get('cancellation') or 'cancellation not shown'}, {cheapest.get('meal') or 'meal not shown'}).")
        elif cheapest is not best:
            notes.append(f"{hotel}: the cheapest room overall is {cheapest['price']:g} EUR ({cheapest.get('cancellation') or 'cancellation not shown'}); the cheapest room that meets every wish is {best['price']:g} EUR.")
    return SiteRows(offers=offers, read=len(rooms), total=len(rooms), problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="arbitrip_rooms_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def arbitrip_rooms_recipe_tool(city: str, check_in: date, check_out: date, adults: int = 2, place_id: str | None = None, children_ages: list[int] | None = None) -> dict[str, Any]:
        """FOR ONE ARBITRIP HOTEL (read in the operator's own Chrome): the list price is only the cheapest room and can be NON-REFUNDABLE, so for each hotel the operator
        wants, press Select on it in the Arbitrip results (a new tab opens: that is the hotel page) and run the returned read-only SCRIPT in that tab. It reads every
        room with its cancellation and meal plan and checks the dates and guests. The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row, and add `arbitrip_link_query` (the returned `link_query`) to the `wishes` you pass, so the link opens
        the same search. One call per hotel; never book (do not press Book)."""
        return arbitrip_rooms_recipe(city, check_in, check_out, adults, place_id, children_ages)
