"""Booking.com flights (one way, one leg per call, COMPARISON ONLY): a URL and a tested read-only script for the operator's own Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 27 Oct 2026): the address is flights.booking.com/flights/<FROM>.AIRPORT-<TO>.AIRPORT/?type=ONEWAY&adults=N&cabinClass=ECONOMY&from=<FROM>.AIRPORT&to=<TO>.AIRPORT
&depart=YYYY-MM-DD&sort=BEST&currency=EUR[&stops=0]. The address honours: the cabin (cabinClass ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST: ECONOMY and BUSINESS checked live), the euro, the sort
(BEST, CHEAPEST, FASTEST) and stops=0 (direct only; the site writes it itself when its stops radio "Direct only" is set; stops=1 is "1 stop max"). The "Direct flights only" box of the SEARCH form changes nothing
in the list: the stops radio of the results does. A route with no direct flight still lists other options under "There are no direct flights for your search. Here are other options". The list holds 15
flights a page with page numbers under it (the site's own buttons, no reload); "We found N flight options" is the size of the whole list; the Sort menu (Best / Cheapest / Fastest) is a button menu that
changes the list inside the page. Every flight is a card with named parts (data-testid flight_card_segment_departure_time_0, ..._stops_0, ..._duration_0, flight_card_carriers, upt_price = per adult,
flight_card_price_total_price = "EUR 313 total" for the group). The list shows no bag, no fare name and no change or refund terms: those are "not shown". No connect-src in the page's CSP, no human check
seen. Filters of the results: stops, airlines (all ticked by default), flight times (none ticked by default), duration: only the stops radio is used; a changed airline or times filter makes the read
refuse. Booking.com only compares: the price to quote comes from the airline's own page, so its rows are never a pick. Airport codes only (a city code needs another address that was not tested). Children are
not supported (their ages are not in the address). Best and Cheapest are read together (the agency's rule). A human check is never worked around.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, with_emit

NAME = "booking_flights"
SOURCE = "Booking.com flights (public website price)"
GROUP = "Flights"
HERE = Path(__file__).parent
PER_PAGE = 15
DEFAULT_PAGES = 2       # pages of each sort: 30 flights of Best and 30 of Cheapest
MAX_PAGES = 5      # 4 page changes took 8 s live (27 Oct 2026), so 2 sorts x 5 pages stay well inside the browser tool's 45 s
SORTS = ["Best", "Cheapest"]
CABINS = {"economy": ("ECONOMY", "Economy"), "premium": ("PREMIUM_ECONOMY", "Premium economy"), "business": ("BUSINESS", "Business"), "first": ("FIRST", "First class")}
ASK = {"stops": "Direct only, or connections allowed?", "cabin": "Cabin: economy, premium, business or first?"}
PAGE_KEYS = ("type", "origin", "destination", "day", "adults", "children", "cabin", "currency", "sort", "stops")      # what the script checks in the page's own address


def booking_flights_recipe(origin: str, destination: str, day: date, adults: int = 2, direct_only: bool = False, cabin: str = "economy", pages: int = DEFAULT_PAGES) -> dict[str, Any]:
    origin, destination = origin.strip().upper(), destination.strip().upper()
    if not (re.fullmatch(r"[A-Z]{3}", origin) and re.fullmatch(r"[A-Z]{3}", destination)) or origin == destination:
        raise ValueError("origin and destination must be two different 3-letter AIRPORT codes (TLV, LIS)")
    if cabin not in CABINS or not 1 <= adults <= 8 or not 1 <= pages <= MAX_PAGES:
        raise ValueError(f"cabin must be one of {sorted(CABINS)}, adults 1-8, pages 1-{MAX_PAGES} (15 flights a page, read for Best and for Cheapest)")
    code, cabin_name = CABINS[cabin]
    expect = {"type": "ONEWAY", "origin": origin, "destination": destination, "day": day.isoformat(), "adults": adults, "children": 0, "cabin": code, "currency": "EUR", "sort": "BEST",
              "stops": "0" if direct_only else None, "direct_only": direct_only, "cabin_name": cabin_name, "pages": pages, "leg": f"{origin} to {destination}, {day:%d %b %Y}"}
    url = (f"https://flights.booking.com/flights/{origin}.AIRPORT-{destination}.AIRPORT/?type=ONEWAY&adults={adults}&cabinClass={code}&from={origin}.AIRPORT&to={destination}.AIRPORT"
           f"&depart={day.isoformat()}&sort=BEST&currency=EUR" + ("&stops=0" if direct_only else ""))
    page_expect = {k: expect[k] for k in PAGE_KEYS}
    script = with_emit((HERE / "booking_flights.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps(page_expect)).replace("__PAGES__", str(pages)).replace("__SORTS__", json.dumps(SORTS))
    return {"url": url, "script": script, "expect": expect}


def _direct(stops: str | None) -> bool | None:
    s = (stops or "").lower()
    if re.search(r"\b(direct|nonstop|non-stop)\b", s):
        return True
    return False if re.search(r"\d+\s+stops?", s) else None      # a wording that is neither: unknown, never assumed direct


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Booking.com result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Booking.com script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    if data.get("unparsed"):
        problems.append(f"Booking.com wrote a flight card in a form the reader does not know ({str(data['unparsed'][0])[:80]}...): the page may have changed; read it by hand and say so")
    form = data.get("form") or {}
    for k in PAGE_KEYS:
        if k in exp and form.get(k) != exp[k]:
            problems.append(f"the page searched {k} {form.get(k)} instead of {exp[k]}: open the url again")
    f = data.get("filters")
    if exp and f is not None:        # a filter the operator did not ask for (an airline off, a flight-time box on, a stops radio that is not the asked one) changes the list
        want_stops = "0" if exp.get("direct_only") else "-1"
        extra = []
        if f.get("stops") not in (want_stops, None) and not (f.get("stops") == "-1" and exp.get("direct_only") and data.get("no_direct_notice")):
            extra.append(f"stops filter {f.get('stops')} instead of {want_stops}")
        if f.get("airlines_off"):
            extra.append(f"{f['airlines_off']} airline box(es) switched off")
        if f.get("times_on"):
            extra.append(f"{f['times_on']} flight-time box(es) ticked")
        if extra:
            problems.append(f"Booking.com shows filters the operator did not ask for ({'; '.join(extra)}): clear them, open the url again and run the script once more")
    sorts = {s.get("sort"): s for s in data.get("sorts") or []}
    if exp and not {"Best", "Cheapest"} <= set(sorts):
        problems.append("both the Best and the Cheapest sorts must be read: run the script again")
    for name, s in sorts.items():
        if str(s.get("shown_as") or "").lower() != str(name).lower():
            problems.append(f"the page showed '{s.get('shown_as')}' instead of {name} when its flights were read: run the script again")
        if not s.get("pages_read"):
            problems.append(f"no page of the {name} sort was read: run the script again")
    pax = (exp.get("adults") or 0) + (exp.get("children") or 0)
    merged: dict[tuple, dict[str, Any]] = {}
    for r in data.get("rows", []):
        legs = r.get("legs") or []
        if len(legs) != 1:
            problems.append(f"a Booking.com flight card has {len(legs)} legs, not one: this recipe reads one way only; open the url again")
            continue
        if r.get("cur") != "€":
            problems.append(f"a Booking.com price is in '{r.get('cur')}', not euro: open the url again (the address asks currency=EUR)")
            continue
        leg = legs[0]
        key = (r.get("carriers"), leg.get("dep"), leg.get("arr"), leg.get("dep_date"), leg.get("arr_date"), r.get("total"))
        if key in merged:      # the same flight in the Best list and in the Cheapest list is one row with both labels
            if r.get("sort") not in merged[key]["tabs"]:
                merged[key]["tabs"].append(r.get("sort"))
            continue
        merged[key] = {"row": r, "tabs": [r.get("sort")]}
    offers: list[Offer] = []
    for item in merged.values():
        r, leg = item["row"], item["row"]["legs"][0]
        direct = _direct(leg.get("stops"))
        arrives = f" (arrives {leg['arr_date']})" if leg.get("arr_date") and leg.get("dep_date") and leg["arr_date"] != leg["dep_date"] else ""
        name = f"{r.get('carriers') or 'airline not shown'} {leg.get('dep')}-{leg.get('arr')}{arrives} ({leg.get('duration')})"
        offers.append(Offer(
            group=exp.get("leg") or group, source=SOURCE, name=name, price_total=r.get("total"), currency="EUR",
            price_basis=f"whole group ({pax} travellers), the total the Booking.com list shows; bags and seats are not in it unless the airline's page says so" if pax else "whole group, the total the Booking.com list shows",
            fits=None if not exp else (True if (direct or not exp.get("direct_only")) else (None if direct is None else False)),
            quotable=False, connecting=direct is False, supplier=(r.get("carriers") or "").split(",")[0].strip() or None,
            details={"stops": leg.get("stops") or "not shown",
                     "fare": "flexible ticket upgrade offered (not priced on the list)" if r.get("flexible_upgrade") else "not shown (the list shows the cheapest fare; the airline's page has the fares)",
                     "checked_bag": "not shown on the list", "refund_change": "not shown on the list",
                     "per_person": f"{r['per_adult']:g} EUR (as the page says: per adult)" if r.get("per_adult") is not None else "not shown",
                     "from_tab": " and ".join(item["tabs"])}))
    n = len(offers)
    seen = ", ".join(f"{name} {s.get('pages_read')} of {s.get('pages_seen')} page(s)" for name, s in sorts.items())
    notes = ["Booking.com only compares: the price to quote comes from the airline's own page. Best and Cheapest were read together; a flight in both lists is one row (column from tab).",
             f"Pages read: {seen} (the site lists {data.get('per_page') or PER_PAGE} flights a page)."]
    if data.get("results_total"):
        notes.append(f"Booking.com says it found {data['results_total']} flight options for this search; only the first pages of each sort were read, so a flight further down was not seen.")
    if data.get("no_direct_notice") and exp.get("direct_only"):
        notes.append("Booking.com says there are no direct flights for this search and lists other options instead: none of these rows is direct, so none meets the direct-only wish.")
    elif exp.get("direct_only") and exp.get("stops") == "0" and (data.get("filters") or {}).get("stops") == "0":
        notes.append("Booking.com's own direct-only filter was set in the address (stops=0).")
    return SiteRows(offers=offers, read=n, total=max(data.get("results_total") or 0, n), problems=problems, sorted_by_price=("Cheapest" in sorts and bool(sorts["Cheapest"].get("pages_read"))), extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="booking_flights_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def booking_flights_recipe_tool(origin: str, destination: str, day: date, adults: int = 2, children_ages: list[int] | None = None, direct_only: bool | None = None, cabin: str | None = None,
                                          operator_answered: bool = False, pages: int = DEFAULT_PAGES) -> dict[str, Any]:
        """FOR BOOKING.COM FLIGHTS (COMPARISON ONLY; one leg, one way; read in the operator's own Chrome with Claude in Chrome), next to the airlines, RateHawk Air and Skyscanner. ASK FIRST: without
        `direct_only` (true/false) and `cabin` ('economy' / 'premium' / 'business' / 'first') it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers
        (`operator_answered`=true for "no preference", only after the operator replied). Then it returns the results url (cabin, euro, Best sort and, for direct only, the site's own stops filter are in it)
        and a read-only SCRIPT: open the url, run the script with the javascript tool. The script reads the first `pages` pages (15 flights each, default 2, at most 5) of the Best sort, then picks Cheapest
        in the page's own Sort menu and reads the first `pages` pages of that (Best and Cheapest are read together, the agency's rule), sends its whole answer from the page to the server by itself and returns a
        short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. `origin` / `destination` are 3-letter AIRPORT
        codes. Children are not supported: search the adults and say so. Booking.com rows are comparison only: the price to quote comes from the airline's page. A human check (captcha) is never worked
        around: stop and tell the operator. One call per leg."""
        if children_ages:
            raise ToolError("Booking.com's address takes no child ages that were tested: search with adults only, say so, and put the children in not_checked for this source (reason: could not be read: children not supported by the recipe)")
        missing = [q for q, given in ((ASK["stops"], direct_only is not None), (ASK["cabin"], cabin is not None)) if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the airports and the travellers only if the request did not say them), "
                            "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        try:
            out = booking_flights_recipe(origin, destination, day, adults, bool(direct_only), cabin or "economy", pages)
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        out["wishes"] = {"expect": out["expect"]}
        out["filters_used"] = [("Direct flights only (operator; the site's own stops filter)" if direct_only else "Connections allowed (" + ("operator" if direct_only is not None else "default: no preference") + ")"),
                               f"{out['expect']['cabin_name']} cabin (" + ("operator" if cabin else "default") + ")", "Best and Cheapest sorts read together (agency rule)", "Prices in EUR (server default)"]
        return out
