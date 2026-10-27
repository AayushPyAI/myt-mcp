"""SATA Azores Airlines (S4) and SATA Air Açores (SP) flights, one way, one leg per call: a URL and a tested read-only script for the operator's own Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 22 Oct 2026): the search is the deeplink book.azoresairlines.pt/booking/dl?step=flights&pointOfSale=PT&adults=N&children=N&infants=N&lang=en&search=LIS.PDL.2027-03-08
(it redirects to /booking/flights); SATA's search service answers only the page itself (an invisible reCAPTCHA token), so nothing is called directly. The page is a React app whose state store (Redux, found
through the React tree: `Availability.availability`) holds the answer the list was drawn from: bounds / sectorSolutions (flights), cabins / fareFamilies / fareBenefits (carry-on, checked bag, change and
refund terms per fare code) and itineraryInfoDictionary ("<flightId>_<fareFamilyId>" -> total for the whole group and the total per passenger type). The script only reads that state. The card list shows
the price per adult ("Prices are per passenger"); the group total comes from the store. Fare codes only (SPL, BSC, FLX, TOP, LIT, PLU): no invented names. One-way legs only (a SATA return fare can be
cheaper: the operator checks it on azoresairlines.pt). These are the airline's own prices: quotable. A human check is never worked around.
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

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sata.client import search_link
from myt_mcp.sites import SiteRows, server_first, with_emit

NAME = "sata"
SOURCE = "SATA / Azores Airlines"
GROUP = "Flights"
HERE = Path(__file__).parent
ASK = {"stops": "Direct only, or connections allowed?", "bag": "Is a checked bag needed (only fares with one), or any fare?", "refund": "Refundable fares only (a penalty is allowed), or any fare?"}
BATCH = 16          # flights per call (the first 8 and the next 8: a whole day is read at once); each flight carries all its fares
CODE = re.compile(r"[A-Z]{3}")


def sata_recipe(origin: str, destination: str, day: date, adults: int = 2, children: int = 0, infants: int = 0, direct_only: bool = False, checked_bag: bool = False,
                refundable: bool = False, limit: int = BATCH, offset: int = 0) -> dict[str, Any]:
    origin, destination = origin.strip().upper(), destination.strip().upper()
    if not (CODE.fullmatch(origin) and CODE.fullmatch(destination)) or origin == destination:
        raise ValueError("origin and destination must be two different 3-letter IATA airport codes (LIS, PDL)")
    if not 1 <= adults <= 9 or children < 0 or infants < 0 or adults + children > 9 or infants > adults or not 1 <= limit <= 30 or offset < 0:
        raise ValueError("adults 1-9 (travellers aged 12+), adults + children at most 9, infants (under 2) at most one per adult, limit 1-30")
    url = search_link(origin, destination, day, None, adults, children, infants)
    script = with_emit((HERE / "sata.js").read_text(encoding="utf-8")).replace("__LIMIT__", str(limit)).replace("__SKIP__", str(offset))
    expect = {"origin": origin, "destination": destination, "day": day.isoformat(), "adults": adults, "children": children, "infants": infants, "direct_only": direct_only,
              "checked_bag": checked_bag, "refundable": refundable, "leg": f"{origin} to {destination}, {day:%d %b %Y}"}
    return {"url": url, "script": script, "expect": expect}


def _hm(stamp: str | None) -> str:
    return (stamp or "")[11:16] or "?"


def _included(text: str | None) -> bool | None:
    """'1 x 23 kg (included)' -> True; 'BAG (chargeable)' -> False; nothing -> None."""
    t = (text or "").lower()
    return None if not t else ("(included)" in t)


def _refund(text: str | None) -> tuple[bool | None, bool | None]:
    """(refundable at all, refundable without a penalty): 'Non Refundable (not included)' -> (False, False); 'Penalty €65 (chargeable)' -> (True, False); 'Without penalties (included)' -> (True, True)."""
    t = (text or "").lower()
    if not t:
        return None, None
    if t.startswith("non refundable"):
        return False, False
    return True, t.startswith("without penalt")


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the SATA result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the SATA script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    rows = data.get("rows", [])
    s = data.get("searched") or {}
    if exp:
        want = (exp["origin"], exp["destination"], exp["day"], exp["adults"], exp.get("children", 0), exp.get("infants", 0))
        got = (s.get("from"), s.get("to"), s.get("day"), s.get("adults"), s.get("children") or 0, s.get("infants") or 0)
        if got != want:
            problems.append(f"the page searched {got[0]} to {got[1]} on {got[2]} for {got[3]} adults, {got[4]} children, {got[5]} infants, not {want[0]} to {want[1]} on {want[2]} for {want[3]}, {want[4]}, {want[5]}: open the url again")
        if s.get("directions") not in (None, 1):
            problems.append(f"the page searched {s.get('directions')} directions, not a one-way leg: open the url again")
        if rows and data.get("currency") != "EUR":
            problems.append(f"SATA shows prices in {data.get('currency')}, not EUR: open the url (pointOfSale=PT) again")
    if not rows and not problems:
        return SiteRows(problems=["SATA / Azores Airlines lists no flight for this route and day (it flies from and to the Azores, Madeira and Portugal's mainland, a few European and North American cities): put SATA in not_checked with the reason 'route not served: SATA has no flights for this search'; never write it as '0 of 0 read'."])
    offers: list[Offer] = []
    n_flights = 0           # a flight is counted on its first (cheapest) fare row: its fares may continue in the next part
    for r in rows:
        name = r.get("flights") or "flight"
        if exp and (r.get("from") != exp["origin"] or r.get("to") != exp["destination"]):
            problems.append(f"flight {name} runs {r.get('from')} to {r.get('to')}, not {exp['origin']} to {exp['destination']}: open the url again")
            continue
        if exp and not (r.get("dep") or "").startswith(exp["day"]):
            problems.append(f"flight {name} departs {r.get('dep')}, not on {exp['day']}: open the url again")
        total = r.get("total")
        if total is None:
            problems.append(f"flight {name}, fare {r.get('fare')}: no total price")
            continue
        parts = [r.get(k) for k in ("adt", "chd", "inf") if r.get(k) is not None]
        if parts and abs(sum(parts) - total) > 0.05:
            problems.append(f"flight {name}, fare {r.get('fare')}: total {total} does not add up from the totals per passenger type ({sum(parts):.2f})")
        if exp and (r.get("nadt"), r.get("nchd") or 0, r.get("ninf") or 0) != (exp["adults"], exp.get("children", 0), exp.get("infants", 0)):
            problems.append(f"flight {name}, fare {r.get('fare')}: priced for {r.get('nadt')} adults, {r.get('nchd')} children, {r.get('ninf')} infants, not the asked group: open the url again")
        n_flights += 1 if r.get("fi") == 0 else 0
        direct = r.get("stops") == 0
        bag = _included(r.get("bag"))
        refundable, free = _refund(r.get("refund"))
        mins = r.get("mins")
        dur = f"{mins // 60}h {mins % 60:02d}" if isinstance(mins, int) else "duration not shown"
        pax_n = (r.get("nadt") or 0) + (r.get("nchd") or 0)
        fits = None
        if exp:
            fits = ((direct or not exp.get("direct_only")) and (bag is True or not exp.get("checked_bag")) and (refundable is True or not exp.get("refundable")))
        per = " / ".join(f"{label} {v:g} EUR for all {n} {kind}" for label, kind, v, n in (("adults", "adults", r.get("adt"), r.get("nadt")), ("children", "children", r.get("chd"), r.get("nchd")),
                                                                                           ("infants", "infants", r.get("inf"), r.get("ninf"))) if v is not None)
        offers.append(Offer(
            group=exp.get("leg") or group, source=SOURCE, name=f"{name} {_hm(r.get('dep'))}-{_hm(r.get('arr'))} ({'direct' if direct else str(r.get('stops')) + ' stop via ' + (r.get('via') or '?')}, {dur}) fare {r.get('fare')}",
            price_total=total, currency="EUR", price_basis=f"whole group ({pax_n} seated travellers), taxes included, SATA's own price" if pax_n else "whole group, taxes included, SATA's own price",
            fits=fits, flexible=True if free else (False if refundable is False else None), connecting=not direct, supplier="SATA Azores Airlines",
            details={"stops": "Direct" if direct else f"{r.get('stops')} stop(s) via {r.get('via') or '?'}" + (f" (of which {r['tech']} technical stop(s) of the same flight number)" if r.get("tech") else ""), "fare": f"{r.get('fare')} ({r.get('cabin') or 'cabin not shown'})",
                     "checked_bag": f"{r.get('bag')}" if r.get("bag") else "not shown", "hand_luggage": r.get("carry") or "not shown",
                     "refund_change": f"refund: {r.get('refund') or 'not shown'}; change before departure: {r.get('change') or 'not shown'}", "per_person": per or "not shown"}))
    flights_total = data.get("flights_total") or n_flights
    offset = int(data.get("offset") or 0)
    notes = ["SATA's own prices: the group total includes taxes. SATA names its fares by code only (SPL, BSC, FLX, TOP, LIT, PLU): bag, change and refund terms are per fare as the page lists them; an asterisk after a condition means conditions apply."]
    if data.get("no_flight_found"):
        notes.append("SATA says it has no flight for this search.")
    if offset:
        notes.append(f"These are flights {offset + 1} to {offset + data.get('flights_in_part', n_flights)} of {flights_total}, cheapest first (the cheaper ones were shown before).")
    return SiteRows(offers=offers, read=n_flights, total=flights_total, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="sata_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def sata_recipe_tool(origin: str, destination: str, day: date, adults: int = 2, children: int = 0, infants: int = 0, direct_only: bool | None = None,
                               checked_bag: bool | None = None, refundable: bool | None = None, operator_answered: bool = False, limit: int = BATCH, offset: int = 0) -> dict[str, Any]:
        """FOR SATA AZORES AIRLINES (S4) AND SATA AIR AÇORES (SP): flights to, from and between the Azores, Madeira and mainland Portugal; one leg, one way; these are the airline's own prices: quotable.
        ASK FIRST: without `direct_only`, `checked_bag` and `refundable` (true/false each) it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers
        (`operator_answered`=true for "no preference", only after the operator replied). Then THE SERVER reads SATA's booking page itself in its own browser (SATA's page does not let the operator's Chrome
        send data to the server; no Chrome action is needed from you) and returns a short receipt with an `ingest` id: call compose_answer with `runs`=[that id] and show its text. It reads `limit` flights from
        `offset`, cheapest first, with every fare (group total, total per adult and child, carry-on, checked bag, change and refund terms); for more call again with offset=offset+limit. `children` = ages 2-11,
        `infants` = under 2, travellers aged 12+ count as adults. If it answers ok=false (a human check, no flights, the browser not running), put SATA in not_checked with that reason and say it; never type a
        row and never work around a human check. One call per leg. (When the server has no browser it returns the url and a script for the operator's Chrome instead.)"""
        asked = ((ASK["stops"], direct_only is not None), (ASK["bag"], checked_bag is not None), (ASK["refund"], refundable is not None))
        missing = [q for q, given in asked if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the airports and the travellers with the children's ages only if the request did not say them), "
                            "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = sata_recipe(origin, destination, day, adults, children, infants, bool(direct_only), bool(checked_bag), bool(refundable), limit, offset)
        out["wishes"] = {"expect": out["expect"]}
        src = lambda v: "operator" if v is not None else "default: no preference"       # noqa: E731
        out["filters_used"] = [("Direct flights only (operator)" if direct_only else f"Connections allowed ({src(direct_only)})"),
                               ("Fares with a checked bag only (operator)" if checked_bag else f"Any bag option ({src(checked_bag)})"),
                               ("Refundable fares only, a penalty allowed (operator)" if refundable else f"Any refund option ({src(refundable)})")]
        out["more"] = f"For the next {limit} flights call this tool again with the same values and offset={offset + limit}."
        # SATA's page only lets its own hosts receive data from it (connect-src), so the operator's Chrome cannot send the answer to this server: the server reads the page itself; when it cannot, the recipe comes
        # back for the operator's Chrome and its script returns the rows in parts (sata is in NO_POST)
        result = await server_first(NAME, "SATA_READ_IN_SERVER", "https://book.azoresairlines.pt", out, "/booking/flights")
        result["more"] = out["more"]
        return result
