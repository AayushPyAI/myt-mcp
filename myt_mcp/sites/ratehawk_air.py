"""RateHawk air tickets (one way, one leg per call): a URL with the filters in the address and a tested read-only script for the operator's own logged-in Chrome
(a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 22 Oct 2026): the address carries route=<FROM>a<DDMMYYYY><TO>a, adt / chd / inf, class, and the filters stops=direct|one_stop,
baggageIncluded=on, withoutAirportChange=on. One card = one validating carrier with several flight alternatives and fare tiers; the price is for the WHOLE group.
The list does not say refund or change conditions ("More rates" opens them), so those stay "not shown".
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

NAME = "ratehawk_air"
SOURCE = "RateHawk Air"
GROUP = "Flights"
HERE = Path(__file__).parent
CABINS = {"economy": "Economy", "premium": "Premium", "business": "Business", "first": "First"}
STOPS = {"direct": ("direct", "Direct flight"), "one_stop": ("one_stop", "Up to 1 stop"), "any": (None, "All flights")}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ASK_AIR = {"stops": "Direct only, up to 1 stop, or any?", "bag": "Checked bag needed?", "cabin": "Cabin: economy, premium, business or first?"}


def air_url(origin: str, destination: str, day: date, adults: int, children: int, infants: int, cabin: str, stops: str, checked_bag: bool, no_airport_change: bool) -> str:
    q = f"route={origin}a{day:%d%m%Y}{destination}a&adt={adults}&tns=0&chd={children}&inf={infants}&class={cabin}"
    if STOPS[stops][0]:
        q += f"&stops={STOPS[stops][0]}"
    if checked_bag:
        q += "&baggageIncluded=on"
    if no_airport_change:
        q += "&withoutAirportChange=on"
    return "https://www.ratehawk.com/air/?" + q


def ratehawk_air_recipe(origin: str, destination: str, day: date, adults: int = 2, children: int = 0, infants: int = 0, cabin: str = "economy", stops: str = "any",
                        checked_bag: bool = False, no_airport_change: bool = False) -> dict[str, Any]:
    origin, destination = origin.strip().upper(), destination.strip().upper()
    if not (re.fullmatch(r"[A-Z]{3}", origin) and re.fullmatch(r"[A-Z]{3}", destination)):
        raise ValueError("origin and destination must be 3-letter IATA airport codes (FLR, LIS)")
    if cabin not in CABINS or stops not in STOPS:
        raise ValueError(f"cabin must be one of {sorted(CABINS)} and stops one of {sorted(STOPS)}")
    if not 1 <= adults <= 9 or not 0 <= children <= 8 or not 0 <= infants <= adults:
        raise ValueError("adults 1-9, children 0-8, infants no more than adults")
    url = air_url(origin, destination, day, adults, children, infants, cabin, stops, checked_bag, no_airport_change)
    expect = {"origin": origin, "destination": destination, "day": day.isoformat(), "adults": adults, "children": children, "infants": infants, "cabin": CABINS[cabin], "stops": stops,
              "checked_bag": checked_bag, "no_airport_change": no_airport_change, "leg": f"{origin} to {destination}, {day:%d %b %Y}"}
    return {"url": url, "script": with_emit((HERE / "ratehawk_air.js").read_text(encoding="utf-8")), "expect": expect}


def _bag(bags: list[int]) -> str:
    big = [b for b in bags if b >= 20]
    return f"{big[0]} kg checked bag included" if big else "not shown on the list (open More rates)"


def _stops_text(its: list[dict[str, Any]]) -> str:
    kinds = {(i.get("s") or "").strip() for i in its}
    if len(kinds) == 1:
        s = next(iter(kinds))
        lay = next((i.get("l") for i in its if i.get("l")), None)
        return s + (f" ({lay})" if lay and "stop" in s.lower() else "") if s else "not shown"
    return "mixed: " + " / ".join(sorted(k for k in kinds if k)) + " (depends on the time)"


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the RateHawk air result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the RateHawk air script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    if data.get("settled") is False:
        problems.append("RateHawk was still adding flights when the list was read: wait and run the script once more")
    if exp:
        allowed = {"One way", exp.get("cabin"), STOPS.get(exp.get("stops") or "any", (None, "All flights"))[1]}
        allowed |= {"Checked baggage"} if exp.get("checked_bag") else set()
        allowed |= {"No airport change"} if exp.get("no_airport_change") else set()
        ticked = data.get("page_ticked") or []
        extra = [f for f in ticked if f not in allowed]
        missing = [f for f in allowed if f and f not in ticked]
        if extra or missing:
            problems.append(f"RateHawk's filters are not as asked (unexpected: {', '.join(extra) or 'none'}; missing: {', '.join(missing) or 'none'}): open the url again and run the script once more")
    pax = (exp.get("adults") or 0) + (exp.get("children") or 0)
    offers: list[Offer] = []
    for r in data.get("rows", []):
        route, day_text = r.get("route") or "", r.get("date") or ""
        if exp.get("origin") and (not re.search(rf"\b{exp['origin']}\b", route) or not re.search(rf"\b{exp['destination']}\b", route)):
            problems.append(f"a card is for '{route}', not {exp['origin']} to {exp['destination']}: open the url again")
            break
        if exp.get("day"):
            m = re.match(r"([A-Z][a-z]{2}) (\d{1,2})", day_text)
            if m and (m.group(1) != MONTHS[int(exp["day"][5:7]) - 1] or int(m.group(2)) != int(exp["day"][8:10])):
                problems.append(f"a card is for '{day_text}', not {exp['day']}: open the url again")
                break
        its = r.get("itineraries") or []
        first = its[0] if its else {}
        times = f"{first.get('d')}-{first.get('a')}{(' ' + first['n']) if first.get('n') else ''}" if first else "times not read"
        name = f"{r.get('carrier') or 'carrier not shown'} {times} {' + '.join(first.get('f') or [])}".strip() + (f" (+{len(its) - 1} other times)" if len(its) > 1 else "")
        for f in r.get("fares") or []:
            bag = _bag(f.get("bags") or [])
            fits: bool | None = True
            if exp.get("checked_bag"):
                fits = True if "included" in bag else None
            offers.append(Offer(
                group=exp.get("leg") or group, source=SOURCE, name=name, price_total=f.get("price"), currency=f.get("currency"),
                price_basis=f"whole group ({pax} travellers)" if pax else "whole group", fits=fits if wishes else None, supplier=r.get("carrier"), connecting=any("stop" in (i.get("s") or "").lower() for i in its),
                details={"stops": _stops_text(its), "fare": f.get("name"), "checked_bag": bag, "refund_change": "not shown on the list (open More rates)",
                         "per_person": f"{f['price'] / pax:.2f} {f.get('currency') or ''} (calculated: group total / {pax})" if f.get("price") and pax else "not shown"}))
    n = len(data.get("rows", []))          # the cards of THIS part (the parts are added up in the source line)
    notes = []
    if data.get("lowest_fare_order") == "not ascending":
        notes.append("RateHawk's list was not strictly in price order: the picks use every card read.")
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)      # N cards read, several fare offers each


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ratehawk_air_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_air_recipe_tool(origin: str, destination: str, day: date, adults: int = 2, children: int = 0, infants: int = 0, stops: str | None = None,
                                       checked_bag: bool | None = None, cabin: str | None = None, no_airport_change: bool = False, operator_answered: bool = False) -> dict[str, Any]:
        """FOR FLIGHTS ON RATEHAWK (one leg, one way; read in the operator's own Chrome with Claude in Chrome), next to TAP, Israir and the other flight sources. ASK FIRST: without `stops`
        ('direct' / 'one_stop' / 'any'), `checked_bag` (true/false) and `cabin` ('economy' / 'premium' / 'business' / 'first') it opens nothing and returns `ask_operator`: ask those
        questions in ONE message, wait, call again with the answers (`operator_answered`=true for "no preference", only after the operator replied). Then it returns the results url (filters
        already in it) and a read-only SCRIPT: open the url, run the script with the javascript tool, give its answer parts unchanged to compose_answer in `site_results` as {"site":
        "ratehawk_air", "result": <part>, "url": <the url>} with the returned `wishes`. `origin` / `destination` are 3-letter airport codes. Children's ages are not in the address:
        say so to the operator. One call per leg."""
        missing = [q for q, given in ((ASK_AIR["stops"], stops is not None), (ASK_AIR["bag"], checked_bag is not None), (ASK_AIR["cabin"], cabin is not None)) if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the airports and the travellers only if the request did not say them), wait for the reply, "
                            "then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = ratehawk_air_recipe(origin, destination, day, adults, children, infants, cabin or "economy", stops or "any", bool(checked_bag), no_airport_change)
        out["wishes"] = {"expect": out["expect"]}
        out["filters_used"] = [f"{STOPS[stops or 'any'][1]} (" + ("operator" if stops else "default: no preference") + ")", f"{CABINS[cabin or 'economy']} cabin (" + ("operator" if cabin else "default") + ")"] + \
            (["Checked baggage (operator)"] if checked_bag else []) + (["No airport change (operator)"] if no_airport_change else [])
        out["note"] = "RateHawk's address has no child ages: tell the operator the price is for the passengers as counted (adults, children, infants)."
        return out
