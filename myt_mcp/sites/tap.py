"""TAP Air Portugal flights (one way, one leg per call): a URL and a tested read-only script for the operator's own Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 22 Oct 2026): the search is the deeplink booking.flytap.com/booking/flights/deeplink?market=PT&language=en&origin&destination&flightType=single&adt&chd&inf&depDate=DD.MM.YYYY
(it redirects to /booking/flights with the same parameters); TAP's availability service refuses plain HTTP clients, so the page itself draws the list. The page keeps the availability answer it drew the list from
in its own session storage (`airportTranslationData`: data.listOutbound = flights with segments, data.offers.listOffers = fares with the group total, price per passenger type, bag and refund flags per segment,
seats left); the script only reads that. The page's own "N direct flights" / "N connecting flights" lines are read too, as a cross-check. The fare is only as good as its worst segment (bag, refund). The market PT
shows EUR. TAP also sells offers that start from a station (a train leg, for example ZMS = Florence station): they are not flights from the airport and are listed apart. These are the airline's own prices: quotable.
A human check is never worked around.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, with_emit
from myt_mcp.tap.client import search_link

NAME = "tap"
SOURCE = "TAP Air Portugal"
GROUP = "Flights"
HERE = Path(__file__).parent
ASK = {"stops": "Direct only, or connections allowed?", "bag": "Is a checked bag needed (only fares with one), or any fare?", "refund": "Refundable fares only, or any fare?"}
BATCH = 24          # flights per call (the first 12 and the next 12: a whole day is read at once); each flight carries all its fares
CODE = re.compile(r"[A-Z]{3}")


def tap_recipe(origin: str, destination: str, day: date, adults: int = 2, children: int = 0, infants: int = 0, direct_only: bool = False, checked_bag: bool = False,
               refundable: bool = False, limit: int = BATCH, offset: int = 0) -> dict[str, Any]:
    origin, destination = origin.strip().upper(), destination.strip().upper()
    if not (CODE.fullmatch(origin) and CODE.fullmatch(destination)) or origin == destination:
        raise ValueError("origin and destination must be two different 3-letter IATA airport codes (FLR, LIS)")
    if not 1 <= adults <= 9 or children < 0 or infants < 0 or adults + children > 9 or infants > adults or not 1 <= limit <= 30 or offset < 0:
        raise ValueError("adults 1-9 (travellers aged 12+), adults + children at most 9, infants (under 2) at most one per adult, limit 1-30")
    url = search_link(origin, destination, day, adults, children, infants)
    script = with_emit((HERE / "tap.js").read_text(encoding="utf-8")).replace("__LIMIT__", str(limit)).replace("__SKIP__", str(offset))
    expect = {"origin": origin, "destination": destination, "day": day.isoformat(), "adults": adults, "children": children, "infants": infants, "direct_only": direct_only,
              "checked_bag": checked_bag, "refundable": refundable, "leg": f"{origin} to {destination}, {day:%d %b %Y}"}
    return {"url": url, "script": script, "expect": expect}


def _hm(stamp: str | None) -> str:
    return (stamp or "")[11:16] or "?"


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the TAP result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the TAP script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    rows = data.get("rows", [])
    want = {"ADT": exp.get("adults", 0), **({"CHD": exp["children"]} if exp.get("children") else {}), **({"INF": exp["infants"]} if exp.get("infants") else {})} if exp else {}
    if exp:
        got = {k: v for k, v in (data.get("pax") or {}).items() if v}
        if got != want:
            problems.append(f"the page searched passengers {got}, not {want}: open the url again")
        if rows and data.get("currency") != "EUR":
            problems.append(f"TAP shows prices in {data.get('currency')}, not EUR: open the url (market=PT) again")
    pax_n = sum(want.values()) - want.get("INF", 0) if want else 0
    offers: list[Offer] = []
    elsewhere: dict[str, dict[str, Any]] = {}
    n_flights = 0          # a flight is counted on its first (cheapest) fare row: its fares may continue in the next part
    for r in rows:
        name = r.get("flights") or "flight"
        if exp and r.get("from") != exp["origin"]:
            elsewhere.setdefault(f"{name} {r.get('dep')}", r)         # e.g. a train leg from a station: not a flight from the asked airport
            continue
        if exp and r.get("to") != exp["destination"]:
            problems.append(f"flight {name} ends at {r.get('to')}, not {exp['destination']}: open the url again")
        if exp and not (r.get("dep") or "").startswith(exp["day"]):
            problems.append(f"flight {name} departs {r.get('dep')}, not on {exp['day']}: open the url again")
        if r.get("total") is None:
            problems.append(f"flight {name}, fare {r.get('fare')}: no total price")
            continue
        per_type = {"ADT": r.get("adt"), "CHD": r.get("chd"), "INF": r.get("inf")}
        if want and all(per_type.get(k) is not None for k in want):
            expected = round(sum(per_type[k] * n for k, n in want.items()), 2)
            if abs(expected - r["total"]) > 0.05:
                problems.append(f"flight {name}, fare {r.get('fare')}: total {r['total']} does not add up from the fares per passenger ({expected})")
        direct = r.get("stops") == 0
        bag, ref = r.get("bag"), r.get("ref")
        n_flights += 1 if r.get("fi") == 0 else 0
        mins = r.get("mins")
        dur = f"{mins // 60}h {mins % 60:02d}" if isinstance(mins, int) else "duration not shown"
        label = f"{name} {_hm(r.get('dep'))}-{_hm(r.get('arr'))}" + (f" operated by {r['op']}" if r.get("op") else "")
        fits = None
        if exp:
            fits = ((direct or not exp.get("direct_only")) and (bag == 1 or not exp.get("checked_bag")) and (ref == 1 or not exp.get("refundable")))
        offers.append(Offer(
            group=exp.get("leg") or group, source=SOURCE, name=f"{label} ({'direct' if direct else str(r.get('stops')) + ' stop via ' + (r.get('via') or '?')}, {dur}) fare {r.get('fare')}",
            price_total=r["total"], currency="EUR", price_basis=f"whole group ({pax_n} seated travellers), taxes included, TAP's own price" if pax_n else "whole group, taxes included, TAP's own price",
            fits=fits, flexible=True if ref == 1 else (False if ref == 0 else None), connecting=not direct, supplier="TAP Air Portugal",
            details={"stops": "Direct" if direct else f"{r.get('stops')} stop(s) via {r.get('via') or '?'}", "fare": f"{r.get('fare')} ({r.get('cabin') or 'cabin not shown'})",
                     "checked_bag": "yes" if bag == 1 else ("no" if bag == 0 else "not shown"), "refund_change": "refundable" if ref == 1 else ("not refundable" if ref == 0 else "not shown") + "; change fees not shown",
                     "per_person": " / ".join(f"{k} {v:g} EUR" for k, v in per_type.items() if v is not None) or "not shown",
                     "seats_left": r.get("seats") if r.get("seats") is not None else "not shown"}))
    flights_total = data.get("flights_total") or n_flights
    if exp and data.get("page_direct") is not None and data.get("page_connecting") is not None and not data.get("offset") and not elsewhere:
        if data["page_direct"] + data["page_connecting"] != flights_total:
            problems.append(f"the page lists {data['page_direct']} direct and {data['page_connecting']} connecting flights but the data holds {flights_total}: the list changed while it was read; run the script once more")
    offset = int(data.get("offset") or 0)
    notes = ["TAP's own prices: the group total includes taxes. Bag and refund flags are per fare (the cheapest fare may have neither); change fees and refund amounts are not shown by the page."]
    if offset:
        notes.append(f"These are flights {offset + 1} to {offset + data.get('flights_in_part', n_flights)} of {flights_total}, cheapest first (the cheaper ones were shown before).")
    if elsewhere:
        notes.append(f"{len(elsewhere)} offer(s) start from another place than {exp.get('origin')} (for example a train leg from a station): not flights from the asked airport, left out.")
    return SiteRows(offers=offers, read=n_flights, total=flights_total, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="tap_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def tap_recipe_tool(origin: str, destination: str, day: date, adults: int = 2, children: int = 0, infants: int = 0, direct_only: bool | None = None,
                              checked_bag: bool | None = None, refundable: bool | None = None, operator_answered: bool = False, limit: int = BATCH, offset: int = 0) -> dict[str, Any]:
        """FOR TAP AIR PORTUGAL (one leg, one way; read in the operator's own Chrome with Claude in Chrome, on TAP's own booking page; these are the airline's own prices: quotable). ASK FIRST: without
        `direct_only`, `checked_bag` and `refundable` (true/false each) it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers (`operator_answered`=true for
        "no preference", only after the operator replied). Then it returns the TAP results url and a read-only SCRIPT: open the url in a tab, run the script with the javascript tool (it reads the flights and
        every fare of each with the group total, bag and refund flags; `limit` flights from `offset`, cheapest first; for more call again with offset=offset+limit). The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. Airport codes as `origin` / `destination`; `children` = ages 2-11, `infants` = under 2,
        travellers aged 12+ count as adults. If a cookie banner is in the way, decline non-essential cookies. A human check is never worked around: stop and tell the operator. One call per leg."""
        asked = ((ASK["stops"], direct_only is not None), (ASK["bag"], checked_bag is not None), (ASK["refund"], refundable is not None))
        missing = [q for q, given in asked if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the airports and the travellers with the children's ages only if the request did not say them), "
                            "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = tap_recipe(origin, destination, day, adults, children, infants, bool(direct_only), bool(checked_bag), bool(refundable), limit, offset)
        out["wishes"] = {"expect": out["expect"]}
        src = lambda v: "operator" if v is not None else "default: no preference"       # noqa: E731
        out["filters_used"] = [("Direct flights only (operator)" if direct_only else f"Connections allowed ({src(direct_only)})"),
                               ("Fares with a checked bag only (operator)" if checked_bag else f"Any bag option ({src(checked_bag)})"),
                               ("Refundable fares only (operator)" if refundable else f"Any refund option ({src(refundable)})")]
        out["more"] = f"For the next {limit} flights call this tool again with the same values and offset={offset + limit}."
        return out
