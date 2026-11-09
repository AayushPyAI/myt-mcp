"""Skyscanner flights (one way, one leg per call, COMPARISON ONLY): a URL and a tested read-only script for the operator's own Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 22 Oct 2026; the data call read in the page's own code on 7 Nov 2026): the address is /transport/flights/<from>/<to>/<yymmdd>/?adultsv2=N&childrenv2=6|8&cabinclass=economy&rtn=0&preferdirects=true|false&currency=EUR.
The page gets its tickets from its own search service (POST /g/radar/api/v2/web-unified-search/ with the search, then GET with the session id until "complete"); the script replays exactly that call in the page
(any skyscanner.net page: the airport ids come from the page's own place lookup, or from the results page's state when it is the same airports), and gets EVERY itinerary of the search with the exact price of the whole group, the segments (flight numbers, marketing and operating carrier), stops, the sellers with
their prices (the airline's own among them), self-transfer flags and emissions. Best = Skyscanner's score descending, Cheapest = price ascending (both checked 18 of 18 tickets against the page). The call carries no
filter (the page's filter boxes are client-side), so "direct only" is applied on the stop count and no hidden filter can change the list. Skyscanner only compares: the price to quote comes from the airline's
own page, so its rows are never a pick. Best and Cheapest are read together (the agency's rule). A human check is never worked around.
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
from myt_mcp.sites import SiteRows, server_first, with_emit

NAME = "skyscanner"
SOURCE = "Skyscanner"
NEEDS_WIDE_WINDOW = True       # kept from the text-reading days: not re-checked whether the mobile layout keeps the page state the script needs (window.__internal), so a narrow window is still refused
GROUP = "Flights"
HERE = Path(__file__).parent
CABINS = {"economy": ("economy", "Economy"), "premium": ("premiumeconomy", "Premium economy"), "business": ("business", "Business"), "first": ("first", "First")}
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ASK = {"stops": "Direct only, or connections allowed?", "cabin": "Cabin: economy, premium, business or first?"}
BATCH = 20


def skyscanner_recipe(origin: str, destination: str, day: date, adults: int = 2, children_ages: list[int] | None = None, cabin: str = "economy", direct_only: bool = False,
                      limit: int = BATCH, offset: int = 0) -> dict[str, Any]:
    origin, destination = origin.strip().lower(), destination.strip().lower()
    if not (re.fullmatch(r"[a-z]{3}", origin) and re.fullmatch(r"[a-z]{3}", destination)):
        raise ValueError("origin and destination must be 3-letter IATA codes (flr, lis)")
    ages = list(children_ages or [])
    if cabin not in CABINS or not 1 <= adults <= 8 or len(ages) > 8 or any(not 0 <= a <= 17 for a in ages) or not 1 <= limit <= 50 or offset < 0:
        raise ValueError(f"cabin must be one of {sorted(CABINS)}, adults 1-8, children's ages 0-17, limit 1-50")
    q = f"adultsv2={adults}" + (f"&childrenv2={'%7C'.join(str(a) for a in ages)}" if ages else "") + f"&cabinclass={CABINS[cabin][0]}&rtn=0&preferdirects={'true' if direct_only else 'false'}&currency=EUR"
    url = f"https://www.skyscanner.net/transport/flights/{origin}/{destination}/{day:%y%m%d}/?{q}"
    script = (with_emit((HERE / "skyscanner.js").read_text(encoding="utf-8")).replace("__SORTS__", json.dumps(["Best", "Cheapest"])).replace("__LIMIT__", str(limit)).replace("__SKIP__", str(offset))
              .replace("__DIRECT__", "true" if direct_only else "false").replace("__REQUEST__", json.dumps({"origin": origin.upper(), "destination": destination.upper(), "day": day.isoformat(), "adults": adults, "ages": ages, "cabin": CABINS[cabin][0]})))
    expect = {"origin": origin.upper(), "destination": destination.upper(), "day": day.isoformat(), "adults": adults, "children": len(ages), "children_ages": sorted(ages), "cabin": CABINS[cabin][1], "direct_only": direct_only,
              "leg": f"{origin.upper()} to {destination.upper()}, {day:%d %b %Y}"}
    return {"url": url, "script": script, "expect": expect}


def _clock(iso: str | None) -> str:
    return (iso or "")[11:16]


def _hours(minutes: Any) -> str:
    h, m = divmod(int(minutes or 0), 60)
    return f"{m} min" if not h else (f"{h} h {m:02d} min" if m else f"{h} h")


def _plus(days: Any) -> str:
    n = int(days or 0)
    return f" (+{n} day{'s' if n != 1 else ''})" if n else ""


def _cabin_label(code: Any) -> str | None:
    for _, (url_code, label) in CABINS.items():
        if url_code == str(code or "").lower():
            return label
    return None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Skyscanner result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Skyscanner script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    if data.get("unparsed"):
        problems.append(f"{data['unparsed']} Skyscanner ticket(s) came without a price or a flight (the service may have changed): they are left out; say so")
    if data.get("currency") and data["currency"] != "EUR":
        problems.append(f"Skyscanner priced in {data['currency']}, not EUR: open the url again")
    if exp:
        route = data.get("route") or []
        if [str(x).upper() for x in route] != [exp["origin"], exp["destination"]]:
            problems.append(f"the page is for '{' to '.join(route) or 'an unknown route'}', not {exp['origin']} to {exp['destination']}: open the url again")
        if data.get("date") and data["date"] != exp["day"]:
            problems.append(f"the page is for '{data['date']}', not {exp['day']}: open the url again")
        if data.get("adults") is not None and data["adults"] != exp.get("adults"):
            problems.append(f"the search has {data['adults']} adult(s), not {exp.get('adults')}: open the url again")
        if data.get("children_ages") is not None and sorted(data["children_ages"]) != sorted(exp.get("children_ages") or []):
            problems.append(f"the search has children aged {sorted(data['children_ages']) or 'none'}, not {sorted(exp.get('children_ages') or []) or 'none'}: open the url again")
        if data.get("cabin") and exp.get("cabin") and _cabin_label(data["cabin"]) != exp["cabin"]:
            problems.append(f"the search is for the cabin '{_cabin_label(data['cabin']) or data['cabin']}', not '{exp['cabin']}': open the url again")
        if bool(data.get("direct_only")) != bool(exp.get("direct_only")):
            problems.append("the script's stop filter is not as asked (direct only vs connections allowed): run it again from the recipe's script")
    sorts = {x["sort"] for x in data.get("sorts") or []}
    if exp and not {"Best", "Cheapest"} <= sorts:
        problems.append("both the Best and the Cheapest lists must be read: run the script again")
    pax = (exp.get("adults") or data.get("adults") or 0) + (exp.get("children") if exp.get("children") is not None else len(data.get("children_ages") or []))
    offers: list[Offer] = []
    for r in data.get("rows", []):
        total = round(float(r["total"]), 2) if r.get("total") is not None else None
        mk = ", ".join(r.get("mk") or []) or "unknown airline"
        op = r.get("op") or []
        operated = f" (operated by {', '.join(op)})" if op and set(op) != set(r.get("mk") or []) else ""
        name = f"{mk}{operated} {_clock(r.get('dep'))}-{_clock(r.get('arr'))}{_plus(r.get('plus'))} ({_hours(r.get('mins'))})"
        direct = int(r.get("stops") or 0) == 0
        via = ", ".join(f"{v.get('name') or v.get('code')} ({v.get('code')})" if v.get("code") and v.get("name") and v.get("name") != v.get("code") else str(v.get("name") or v.get("code")) for v in r.get("via") or [])
        stops = "Direct flight" if direct else f"{r['stops']} stop{'s' if r['stops'] != 1 else ''} via {via or 'a connection'}" + (f", {_hours(r['layover'])} in total on the ground" if r.get("layover") else "")
        sellers = r.get("sellers") or []
        sold = "; ".join(f"{x['n']}{' (airline)' if x.get('a') else ''} {x['p']:.2f} EUR" for x in sellers[:4]) or "not shown"
        if r.get("airline_price") is not None:
            airline = f"{r['airline_price']:.2f} EUR for the whole group (the airline's own price listed on Skyscanner)"
        else:
            airline = "the airline is not among Skyscanner's sellers for this ticket"
        details = {"stops": stops, "flights": ", ".join(r.get("flights") or []) or "not shown", "fare": "not shown (Skyscanner lists the cheapest fare; the airline's page has the fares)",
                   "checked_bag": "not shown on the list", "refund_change": "not shown on the list",
                   "per_person": f"{total / pax:.2f} EUR (the whole-group price divided by {pax} travellers)" if total is not None and pax else "not shown",
                   "sold_by": f"{sold} ({r.get('seller_count') or len(sellers)} seller(s) on Skyscanner)", "airline_price": airline,
                   "self_transfer": ("yes: separate tickets" + (", protected by the seller" if r.get("protected") else ", NOT protected: a delay on the first can lose the second")) if r.get("self_transfer") else "no",
                   "emissions": f"{r['em_kg']:.0f} kg CO2e ({r.get('em_level') or 'level not shown'})" if r.get("em_kg") is not None else "not shown"}
        offers.append(Offer(
            group=exp.get("leg") or group, source=SOURCE, name=name, price_total=total, currency="EUR",
            price_basis=f"whole group ({pax} travellers), taxes included, exact Skyscanner price (the page shows it rounded up)" if pax else "whole group, taxes included, exact Skyscanner price (the page shows it rounded up)",
            fits=None if not exp else (True if (direct or not exp.get("direct_only")) else False),
            quotable=False, connecting=not direct, supplier=(r.get("mk") or [None])[0], details=details))
    n = len(offers)
    per_sort = max([int(x.get("read") or 0) for x in data.get("sorts") or []] or [0])
    notes = [f"These are tickets {int(data['offset']) + 1} to {int(data['offset']) + per_sort} of each list (the cheaper or better ones were shown before)."] if data.get("offset") else []
    notes += ["Skyscanner only compares: the price to quote comes from the airline's own page. The Best and the Cheapest lists were read together."]
    where = f"{exp['leg']}: " if exp.get("leg") else ""        # one run per leg: each leg's own counts, not one leg's number for both
    if data.get("results_total") is not None:
        direct_note = f" ({data['matching_total']} of them direct)" if data.get("direct_only") and data.get("matching_total") is not None else ""
        notes.append(f"{where}Skyscanner lists {data['results_total']} tickets for this search{direct_note}.")
    return SiteRows(offers=offers, read=n, total=data.get("matching_total") if data.get("matching_total") is not None else (data.get("results_total") or n), problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="skyscanner_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def skyscanner_recipe_tool(origin: str, destination: str, day: date, adults: int = 2, children_ages: list[int] | None = None, direct_only: bool | None = None,
                                     cabin: str | None = None, operator_answered: bool = False, limit: int = BATCH, offset: int = 0) -> dict[str, Any]:
        """FOR SKYSCANNER (COMPARISON ONLY; one leg, one way; read in the operator's own Chrome with Claude in Chrome), next to the airlines and RateHawk. ASK FIRST: without `direct_only`
        (true/false) and `cabin` ('economy' / 'premium' / 'business' / 'first') it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers
        (`operator_answered`=true for "no preference", only after the operator replied). Then it returns the results url (filters in it) and a read-only SCRIPT: open the url, run the script
        with the javascript tool; it replays the page's own search call and reads the Best and the Cheapest lists (`limit` tickets each from `offset`; for more call again with offset=offset+limit). The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. `origin` / `destination` are 3-letter airport or city codes; give `children_ages`. Skyscanner
        rows are comparison only: the price to quote comes from the airline's page. A human check (captcha) is never worked around: stop and tell the operator. One call per leg."""
        missing = [q for q, given in ((ASK["stops"], direct_only is not None), (ASK["cabin"], cabin is not None)) if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the airports and the travellers with the children's ages only if the request did not say them), "
                            "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = skyscanner_recipe(origin, destination, day, adults, children_ages, cabin or "economy", bool(direct_only), limit, offset)
        out["wishes"] = {"expect": out["expect"]}
        out["filters_used"] = [("Direct flights only (operator)" if direct_only else "Connections allowed (" + ("operator" if direct_only is not None else "default: no preference") + ")"),
                               f"{CABINS[cabin or 'economy'][1]} cabin (" + ("operator" if cabin else "default") + ")", "Best and Cheapest lists read together (agency rule)"]
        out["more"] = f"For the next {limit} tickets of each tab call this tool again with the same values and offset={offset + limit}."
        # OFF unless SKYSCANNER_READ_IN_SERVER=1: it read fine from the VPS once (8 s) and then showed a PerimeterX check page (28 Oct 2026); tried again from the server's automation Chrome on 7 Nov 2026: HTTP 403 on the search service (a block, so it is NOT switched on).
        # It is read in the operator's Chrome, which the site does not stop. The recipe came back unchanged for that Chrome and nothing was retried or worked around.
        return await server_first(NAME, "SKYSCANNER_READ_IN_SERVER", "https://www.skyscanner.net", out, default=False)
