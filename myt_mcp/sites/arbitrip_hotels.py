"""Arbitrip hotels: a URL (filters already in the address) and a tested read-only script for the operator's own logged-in Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real pages, 22 Oct 2026):
* Filters live in the address: max_distance (km), max_price_per_night (EUR), categories / amenities / stars / review as JSON maps that hold only the CHANGES from the
  agency's defaults (defaults: Hotel only, stars 2-5, review score without "Poor"). RateHawk shows everything, so the URL switches Apartment, Other and Poor on:
  no filter the operator did not name.
* The agency contract (contract_id) must be in the address: without it the page is not "Showing results for <contract>" and the rates may differ.
* The list price is the cheapest room (with breakfast when that filter is on) and can be NON-REFUNDABLE; there is no free-cancellation filter in the list. List rows are
  therefore "comparison only" and never a pick; cancellation is read on the hotel page (arbitrip_rooms_recipe) for the hotels the operator is interested in.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer, meets_limits
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, with_emit
from myt_mcp.sites.ratehawk_hotels import BATCH, ask_gate, limits

NAME = "arbitrip_hotels"
SOURCE = "Arbitrip"
GROUP = "Hotels"
HERE = Path(__file__).parent
SORT_LABEL = "Price (Low to High)"
DEFAULT_STARS_ON = {2, 3, 4, 5}      # the agency's default star boxes (1 star is off)


def known_places() -> dict[str, str]:
    data = json.loads((HERE / "arbitrip_places.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def results_url(place_id: str, contract_id: str, check_in: date, check_out: date, guests: int, children_ages: list[int] | None, stars: int | None, breakfast: bool, budget_per_night: float | None,
                max_distance_km: float | None) -> tuple[str, list[str]]:
    """The results address with the operator's filters, and the names of the filters it carries (the script checks that the page kept them)."""
    j = lambda obj: quote(json.dumps(obj, separators=(",", ":")), safe="")      # noqa: E731
    parts = [("place_id", place_id), ("check_in", f"{check_in:%y%m%d}"), ("check_out", f"{check_out:%y%m%d}"), ("guests", str(guests)), ("rooms", "1"), ("contract_id", contract_id),
             ("max_distance", str(int(-(-max_distance_km // 1)) if max_distance_km else 50))]
    keys = ["place_id", "check_in", "check_out", "guests", "rooms", "contract_id", "max_distance"]
    if children_ages:           # found on the real page 23 Oct 2026: children=<count> and children_ages=<ages, comma-separated> (guests = the adults); the header then reads "2 Adults · 1 Child" and the prices change
        parts += [("children", str(len(children_ages))), ("children_ages", ",".join(str(a) for a in children_ages))]
        keys += ["children", "children_ages"]
    if budget_per_night is not None:
        parts.append(("max_price_per_night", str(int(budget_per_night)))), keys.append("max_price_per_night")
    parts += [("categories", j({"Apartment": True, "Other": True}))]
    keys.append("categories")
    if breakfast:
        parts.append(("amenities", j({"BREAKFAST_INCLUDED": True}))), keys.append("amenities")
    wanted = {s for s in range(1, 6) if s >= (stars or 1)}
    changes = {str(s): s in wanted for s in range(1, 6) if (s in wanted) != (s in DEFAULT_STARS_ON)}
    if changes:
        parts.append(("stars", j(changes))), keys.append("stars")
    parts += [("review", j({"Poor": True})), ("sort", quote(SORT_LABEL, safe="()"))]
    keys += ["review", "sort"]
    return "https://app.arbitrip.com/results?" + "&".join(f"{k}={v}" for k, v in parts), keys


def arbitrip_hotels_recipe(city: str, check_in: date, check_out: date, adults: int = 2, children_ages: list[int] | None = None, stars: int | None = None, breakfast: bool = False,
                           budget_per_night: float | None = None, max_distance_km: float | None = None, offset: int = 0, limit: int = BATCH, place_id: str | None = None) -> dict[str, Any]:
    if check_out <= check_in:
        raise ValueError("check_out must be after check_in")
    if children_ages and (len(children_ages) > 6 or any(not 0 <= a <= 17 for a in children_ages)):
        raise ValueError("children's ages must be 0-17 and at most 6 children")
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("offset must be 0 or more and limit 1-100")
    if stars is not None and not 1 <= stars <= 5:
        raise ValueError("stars must be 1-5 (the minimum star rating)")
    key = re.sub(r"\s+", " ", city.strip().lower())
    pid = place_id or known_places().get(key)
    if not pid:
        return {"needs_place_id": city, "known_cities": sorted(known_places()), "steps": [
            "Open https://app.arbitrip.com/search in the operator's logged-in Chrome, type the city, pick the suggestion with the same name, enter the dates and guests, press Search.",
            "On the results page run with the javascript tool: (() => new URLSearchParams(location.search).get('place_id'))()  and call this tool again with that value as place_id. Nothing is booked."]}
    contract = os.environ.get("ARBITRIP_CONTRACT_ID", "").strip()
    if not contract:
        return {"needs_contract_id": True, "steps": [
            "The agency contract id is missing on the server (ARBITRIP_CONTRACT_ID in .env). Ask the operator to add it: open any Arbitrip results page and read contract_id from its address. "
            "Without it Arbitrip does not show the agency's rates."]}
    url, keys = results_url(pid, contract, check_in, check_out, adults, children_ages, stars, breakfast, budget_per_night, max_distance_km)
    start = offset
    script = with_emit((HERE / "arbitrip_hotels.js").read_text(encoding="utf-8")).replace("__LIMIT__", str(limit)).replace("__SKIP__", str(start))
    script = script.replace("__EXPECT_SORT__", SORT_LABEL).replace("__EXPECT_KEYS__", json.dumps(keys))
    return {"url": url, "expect_sort": SORT_LABEL, "script": script, "filters_in_url": keys}


def _int(text: Any) -> int | None:
    m = re.search(r"[\d,]+", str(text or ""))
    return int(m.group(0).replace(",", "")) if m else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Arbitrip result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Arbitrip script reported: {data.get('error', 'not ok')}"])
    problems: list[str] = []
    if data.get("price_order") == "not ascending":
        problems.append("the Arbitrip prices are not in ascending order: the page may have changed while reading")
    breakfast_on = bool(data.get("breakfast_filter"))
    offers: list[Offer] = []
    seen: set[str] = set()
    for r in data.get("rows", []):
        name, price = r.get("name"), r.get("price")
        key = f"{name}|{price}"
        if key in seen or not name:
            continue
        seen.add(key)
        fits: bool | None = True
        if wishes.get("breakfast") and not breakfast_on:
            fits = None                                      # no breakfast filter in the address: the list does not say
        if wishes.get("stars_min") and not (r.get("stars") and r["stars"] >= int(wishes["stars_min"])):
            fits = False
        if not meets_limits(price, r.get("distance"), wishes):
            fits = False
        if fits is not False and wishes.get("free_cancellation"):
            fits = None                                      # the list price can be a non-refundable room: only the hotel page tells
        offers.append(Offer(
            group=group, source=SOURCE, name=name, price_total=price, currency="EUR", price_basis="whole stay, tax included (cheapest room in the list)",
            details={"stars": r.get("stars"), "score": r.get("score"), "reviews": _int(r.get("reviews")), "distance_from_centre": r.get("distance"),
                     "meal": "Breakfast included (filter on in the list)" if breakfast_on else None,
                     "cancellation": "not in the list: the cheapest room can be non-refundable (open the hotel page)", "room_bed": None},
            fits=fits, quotable=False, supplier=name))
    notes = ["Arbitrip list rows are comparison only: the price is the cheapest room (with breakfast when that filter is on) and may be non-refundable. "
             "Ask the operator which hotels to check; the hotel page shows the free-cancellation rate."]
    if data.get("offset"):
        notes.append(f"These are Arbitrip options {int(data['offset']) + 1} to {int(data['offset']) + len(offers)} of the list.")
    if data.get("sort") == SORT_LABEL and not data.get("offset"):
        notes.append("Arbitrip's list was read sorted by price (low to high), the cheapest first.")
    approx = data.get("approx_total")
    reached = len(offers) + int(data.get("offset") or 0)
    if approx and reached > approx:      # the page's header count is an estimate (17 on one read, 14 on another, 15 rows each time): never print "15 of 14 read"
        notes.append(f"The page's header says about {approx} results; {reached} rows were read (the header is only an estimate).")
        approx = reached
    return SiteRows(offers=offers, read=len(offers), total=approx, problems=problems, sorted_by_price=data.get("sort") == SORT_LABEL, extra_notes=notes)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="arbitrip_hotels_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def arbitrip_hotels_recipe_tool(city: str, check_in: date, check_out: date, adults: int = 2, breakfast: bool = False, stars: int | None = None,
                                          budget_per_night: float | None = None, max_distance_km: float | None = None, operator_answered: bool = False,
                                          offset: int = 0, limit: int = BATCH, place_id: str | None = None, children_ages: list[int] | None = None) -> dict[str, Any]:
        """FOR HOTELS ON ARBITRIP (read in the operator's own Chrome with Claude in Chrome), next to RateHawk. ASK FIRST like ratehawk_hotels_recipe: without minimum
        `stars`, `budget_per_night` and `max_distance_km` it opens nothing and returns `ask_operator` (one message, wait; `operator_answered`=true for "no preference").
        Then it returns the results url (filters already in it) and a read-only SCRIPT: open the url, run the script with the javascript tool; it reads the next `limit`
        (30) hotels from `offset`. The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row
        with the `wishes` and `filters_used` from ratehawk_hotels_recipe. The list price can be a non-refundable room: Arbitrip rows are comparison only; for the hotels the
        operator wants, open the hotel page (Select) and read its rooms. `city` is the name as typed (lisbon); an unknown city returns steps to learn its place_id once."""
        asked = ask_gate(stars, budget_per_night, max_distance_km, operator_answered)
        if asked:
            return asked
        out = arbitrip_hotels_recipe(city, check_in, check_out, adults, children_ages, stars, breakfast, budget_per_night, max_distance_km, offset, limit, place_id)
        if "url" in out:
            out["more"] = f"For the next {limit} hotels call this tool again with the same values and offset={offset + limit}."
        return out
