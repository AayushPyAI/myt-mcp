"""Bensaude Hotels, the group's own website (its booking engine bensaude.e-gds.com): a URL (everything in the address) and a tested read-only script for the operator's own Chrome.

Site rules (found on the real pages, 27 Oct 2026):
* Every search is in the address: hotelid, adults, children, nrooms, arrivaldate and departuredate (YYYYMMDD). The page is server-rendered (a plain GET returns the prices too).
* The page keeps the last search's guests in its SESSION (27 Oct 2026: after one search with a child, the same address with children=0 still priced the child: 3 rooms and higher prices instead of 11 rate plans; the rate links then say
  children=1): the script reads the links and refuses, the converter refuses `children_on_page`.
* A child's AGE is not in the address (the page asks for it in its form and keeps it in the session; one try with a child showed no rooms): children are refused here until that is tested.
* Rooms are `div.Room` with rate plans (`div.RatePlan`: FLEX = "Book now, pay later", TN Special = half board). The price is for the whole stay and room, VAT included, local tax excluded.
* Each rate plan has a detail page (RatePlanDetail.aspx, the "i" icon) with the cancellation policy ("Cancellations must be submitted 7 days before check-in date. ... charged by 100.00%"),
  the nightly rates and the local tourist tax: the script fetches it from the same site, the server reads the rules here.
* The page does not show stars, a review score or a distance: those details stay empty and a wish for them is never judged as met.
* This is the hotel's PUBLIC website rate (the page has "Agencies or Corporate? Sign in"): the answer says so when the operator's Chrome is not logged in.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, server_first, with_emit
from myt_mcp.sites.ratehawk_hotels import limits

NAME = "bensaude_hotels"
SOURCE = "Bensaude (the hotel's own website)"
GROUP = "Hotels"
SUPPLIER = "Bensaude Group"
HERE = Path(__file__).parent
ENGINE = "https://bensaude.e-gds.com/webfrontendcorporate/shoppingcart/availability.aspx"
MEALS = (("full board", "Full board"), ("half board", "Half board (breakfast and one meal a day)"), ("breakfast included", "Breakfast included"), ("room only", "Room only"))


def hotels() -> dict[str, tuple[int, str]]:
    data = json.loads((HERE / "bensaude_hotels.json").read_text(encoding="utf-8"))
    return {k: (v[0], v[1]) for k, v in data.items() if not k.startswith("_")}


def _plain(text: str) -> str:
    """Lower case, no accents, words only: 'Hotel Açores Lisboa' and 'hotel acores lisboa' are the same."""
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", str(text).lower()).encode("ascii", "ignore").decode()).strip()


def find_hotel(text: str) -> tuple[int, str] | list[str] | None:
    """(id, name) for an exact name or one that only one hotel holds, the list of names when several fit, None when none does. A number is taken as the id."""
    table = hotels()
    key = _plain(text)
    if key.isdigit():
        return next(((i, n) for i, n in table.values() if i == int(key)), None)
    if key in table:
        return table[key]
    near = [v for k, v in table.items() if key and (key in k or k in key)]
    if len(near) == 1:
        return near[0]
    return [n for _, n in near] if near else None


def availability_url(hotel_id: int, check_in: date, check_out: date, adults: int, rooms: int) -> str:
    return f"{ENGINE}?lang=en&hotelid={hotel_id}&adults={adults}&children=0&nrooms={rooms}&arrivaldate={check_in:%Y%m%d}&departuredate={check_out:%Y%m%d}"


def bensaude_hotels_recipe(hotel_id: int, check_in: date, check_out: date, adults: int = 2, rooms: int = 1) -> dict[str, Any]:
    if check_out <= check_in:
        raise ValueError("check_out must be after check_in")
    if not 1 <= adults <= 8 or not 1 <= rooms <= 4:
        raise ValueError("adults must be 1-8 and rooms 1-4")
    expect = {"hotel_id": hotel_id, "check_in": f"{check_in:%d/%m/%Y}", "check_out": f"{check_out:%d/%m/%Y}", "adults": adults}
    script = with_emit((HERE / "bensaude_hotels.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps(expect))
    return {"url": availability_url(hotel_id, check_in, check_out, adults, rooms), "script": script, "expect": expect}


def _day(text: Any) -> date | None:
    try:
        return datetime.strptime(str(text), "%d/%m/%Y").date()
    except ValueError:
        return None


def _meal(description: str) -> str | None:
    low = (description or "").lower()
    return next((label for key, label in MEALS if key in low), None)


def _cancellation(text: str | None, check_in: date | None, today: date) -> tuple[bool | None, str]:
    """(free to cancel today?, the terms in words). None when the page's policy is missing or not understood: never assumed."""
    if not text:
        return None, "not shown (the rate plan's detail page could not be read)"
    if re.search(r"non[- ]?refundable|no refund|not refundable", text, re.I):
        return False, "non-refundable"
    days = re.search(r"submitted\s+(\d+)\s+days?\s+before check-?in", text, re.I)
    pct = re.search(r"charged by\s+([\d.]+)\s*%", text, re.I)
    if not days or not check_in:
        return None, "not understood: " + re.sub(r"\s+", " ", text)[:140]
    until = check_in - timedelta(days=int(days.group(1)))
    after = f"{float(pct.group(1)):g}% of the stay is charged after that" if pct else "a charge applies after that"
    if today <= until:
        return True, f"free cancellation until {until:%d %b %Y} ({days.group(1)} days before check-in); {after}"
    return False, f"the free cancellation ended on {until:%d %b %Y} ({days.group(1)} days before check-in): {after} from now"


def _tax(text: str | None) -> str | None:
    m = re.search(r"(tourist tax:?\s*)(.{0,170}?)(?:\.\s|$)", text or "", re.I)
    return re.sub(r"\s+", " ", m.group(2)).strip() if m else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Bensaude result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Bensaude script reported: {data.get('error', 'not ok')}"])
    problems: list[str] = []
    if data.get("children_on_page"):
        problems.append("the page priced a child kept from an earlier search in this Chrome: the rooms and prices are not for the adults asked; close every Bensaude tab, open the url again in a new Chrome window and run the script again")
    expect = wishes.get("expect") or {}
    for key, label in (("hotel_id", "hotel"), ("check_in", "check-in"), ("check_out", "check-out"), ("adults", "adults")):
        if expect.get(key) and data.get(key) != expect[key]:
            problems.append(f"the page searched {label} {data.get(key)!r}, not {expect[key]!r}: search again with the url the recipe gave")
    rows = data.get("rows") or []
    if not rows:
        problems.append("the Bensaude page showed no rooms: it could not be read (never say sold out); run the script again")
    check_in = _day(data.get("check_in"))
    today = date.today()
    hotel = str(data.get("hotel") or "Bensaude hotel").strip()
    offers: list[Offer] = []
    seen: set[str] = set()
    no_terms = 0
    for r in rows:
        price, plan, room = r.get("price"), (r.get("plan") or "").strip(), (r.get("room") or "").strip()
        if not price or not plan or not room:
            continue
        name = f"{hotel} - {room} - {plan}"
        key = f"{name}|{price}"
        if key in seen:
            continue
        seen.add(key)
        meal = _meal(r.get("description") or "")
        free, terms = _cancellation(r.get("cancel"), check_in, today)
        no_terms += free is None
        fits: bool | None = True
        if wishes.get("breakfast"):
            fits = None if meal is None else (meal != "Room only")
        if fits is not False and wishes.get("free_cancellation"):
            fits = None if free is None else free
        if wishes.get("max_total") is not None and price > float(wishes["max_total"]):
            fits = False
        if fits is not False and wishes.get("stars_min"):
            fits = None                                   # the page shows no star rating: a stars wish cannot be met from it
        offers.append(Offer(
            group=group, source=SOURCE, name=name, price_total=float(price), currency="EUR", price_basis="whole stay for the room, VAT included, local tax excluded",
            details={"stars": None, "score": None, "reviews": None, "distance_from_centre": None, "meal": meal or "not shown", "cancellation": terms, "room_bed": r.get("room_desc"),
                     "pay": "pay later at the hotel (a credit card is needed to confirm)" if re.search(r"pay later", r.get("description") or "", re.I) else None,
                     "local_tax": _tax(r.get("tax")), "special_offer": bool(r.get("special"))},
            flexible=free, fits=fits, quotable=True, supplier=SUPPLIER, link=None))
    notes = ["Bensaude rows are the hotel group's own website rates for one room."]
    if not data.get("agent_login"):
        notes.append("This is the public website rate: the operator's Chrome is not logged in to Bensaude's agency (corporate) sign-in, whose rates may differ.")
    if no_terms:
        notes.append(f"The cancellation terms of {no_terms} rate plan(s) were not readable: they are never counted as free cancellation.")
    if wishes.get("stars_min"):
        notes.append("The Bensaude page shows no star rating, so a minimum-stars wish could not be checked on these rows.")
    return SiteRows(offers=offers, read=len(offers), total=len(offers), problems=problems, sorted_by_price=False, extra_notes=notes)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="bensaude_hotels_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def bensaude_hotels_recipe_tool(hotel: str, check_in: date, check_out: date, adults: int = 2, rooms: int = 1, breakfast: bool = False, free_cancellation: bool = False,
                                          budget_per_night: float | None = None, children_ages: list[int] | None = None) -> dict[str, Any]:
        """FOR A BENSAUDE HOTEL (Azores and Lisbon: Terra Nostra Garden, Grand Hotel Açores Atlântico, Caloura, São Miguel Park, Marina Atlântico, Terceira Mar, Canal, Caracol, NEAT Avenida, Botania Hall, Hotel
        Açores Lisboa) on the group's OWN website, read in the operator's Chrome with Claude in Chrome, next to RateHawk and Arbitrip (the client compares the hotel's direct rate). `hotel` is the hotel's
        name (an unclear name returns the list: ask the operator). Then it returns the url and a read-only SCRIPT: open the url in Claude in Chrome, run the script with the javascript tool; it reads every room
        and rate plan with its meal, price of the whole stay and cancellation policy, sends them to the server by itself and returns a short receipt (the `ingest` id): then call compose_answer with `runs`=[that id]
        and the `wishes` and `filters_used` of this tool. Never type a row. The page shows no stars or review score. Children are not supported yet (their ages are not in the address): search adults only
        and say so. `budget_per_night` is per night; the price is per room for the stay. SERVER FIRST: the server first reads this page itself in its own automation Chrome (the same script); then the answer is a short receipt with an `ingest` id and you only call compose_answer with `runs`=[that id]. If it could not (the answer then has `server_read` with the reason, and the url and script below), read the page in Claude in Chrome as described here. Never retry the server's read."""
        if children_ages:
            raise ToolError("Bensaude's page takes a child's age in its form, not in the address, and that is not tested: search with adults only, say so, and put the children in not_checked for this source (reason: could not be read: children are not supported yet)")
        found = find_hotel(hotel)
        if not isinstance(found, tuple):
            return {"ok": False, "searched": False, "known_hotels": found or [n for _, n in hotels().values()],
                    "next": "Nothing was opened. Ask the operator which Bensaude hotel (the names above), then call this tool again with the exact name."}
        hotel_id, hotel_name = found
        try:
            out = bensaude_hotels_recipe(hotel_id, check_in, check_out, adults, rooms)
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        wishes, filters = limits(None, budget_per_night, None, breakfast, free_cancellation, (check_out - check_in).days)
        wishes["expect"] = out.pop("expect")
        out.update({"hotel": hotel_name, "wishes": wishes, "filters_used": filters + [f"Guests: {adults} adults (operator)"], "nights": (check_out - check_in).days})
        return await server_first(NAME, "BENSAUDE_READ_IN_SERVER", "https://bensaude.e-gds.com", out)
