"""Skyscanner flights (one way, one leg per call, COMPARISON ONLY): a URL and a tested read-only script for the operator's own Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 22 Oct 2026): the address is /transport/flights/<from>/<to>/<yymmdd>/?adultsv2=N&childrenv2=6|8&cabinclass=economy&rtn=0&preferdirects=true|false&currency=EUR;
the sort tabs (Best, Cheapest, Fastest) and "Show more results" work inside the page (not in the address); every ticket has one accessibility sentence that the script parses; sponsored tickets
are marked "Advertisement by ..." and are left out; the price is per passenger with "Total cost" for the group, taxes included. Skyscanner only compares: the price to quote comes from the airline's
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
NEEDS_WIDE_WINDOW = True       # a narrow window shows the mobile layout, which the script cannot read
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
    script = with_emit((HERE / "skyscanner.js").read_text(encoding="utf-8")).replace("__SORTS__", json.dumps(["Best", "Cheapest"])).replace("__LIMIT__", str(limit)).replace("__SKIP__", str(offset))
    expect = {"origin": origin.upper(), "destination": destination.upper(), "day": day.isoformat(), "adults": adults, "children": len(ages), "cabin": CABINS[cabin][1], "direct_only": direct_only,
              "leg": f"{origin.upper()} to {destination.upper()}, {day:%d %b %Y}"}
    return {"url": url, "script": script, "expect": expect}


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
        problems.append(f"Skyscanner wrote a ticket in a form the reader does not know ({str(data['unparsed'][0])[:80]}...): the page may have changed; read it by hand and say so")
    if exp:
        route = data.get("route") or []
        if route != [exp["origin"], exp["destination"]]:
            problems.append(f"the page is for '{' to '.join(route) or 'an unknown route'}', not {exp['origin']} to {exp['destination']}: open the url again")
        d = date.fromisoformat(exp["day"])
        want_day = f"{DAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]}"
        if data.get("date") and data["date"] != want_day:
            problems.append(f"the page is for '{data['date']}', not {want_day}: open the url again")
        pax = (exp.get("adults") or 0) + (exp.get("children") or 0)
        if data.get("travellers") is not None and pax and data["travellers"] != pax:
            problems.append(f"the page counts {data['travellers']} travellers, not {pax}: open the url again")
        if data.get("cabin") and exp.get("cabin") and data["cabin"].lower() != exp["cabin"].lower():
            problems.append(f"the page shows the cabin '{data['cabin']}', not '{exp['cabin']}': open the url again")
        if bool(data.get("direct_only")) != bool(exp.get("direct_only")):
            problems.append("Skyscanner's stop filters are not as asked (direct only vs connections): open the url again")
        f = data.get("filters")
        if f is not None:        # a filter the operator did not ask for (bags, emissions, nearby airports, an airline or layover box switched off) changes the list
            extra = [x for x in f.get("ticked_extras") or [] if not (exp.get("direct_only") and x.startswith("Direct flights"))]      # the url's preferdirects=true ticks that toggle itself
            if extra or f.get("unticked_defaults"):
                problems.append(f"Skyscanner shows filters the operator did not ask for ({', '.join(extra) or str(f.get('unticked_defaults')) + ' airline or layover box(es) switched off'}): clear them, open the url again and run the script once more")
    sorts = {s["sort"] for s in data.get("sorts") or []}
    if exp and not {"Best", "Cheapest"} <= sorts:
        problems.append("both the Best and the Cheapest tabs must be read: run the script again")
    pax = (exp.get("adults") or 0) + (exp.get("children") or 0)
    offers: list[Offer] = []
    for r in data.get("rows", []):
        stops = "Direct flight" if r.get("direct") else f"{r.get('via') or 'connection'}"
        name = f"{r.get('airlines')} {r.get('dep')}-{r.get('arr')}{(' ' + r['later'] + ' later') if r.get('later') else ''} ({r.get('duration')})"
        offers.append(Offer(
            group=exp.get("leg") or group, source=SOURCE, name=name, price_total=r.get("total"), currency="EUR",
            price_basis=f"whole group ({pax} travellers), taxes included, Skyscanner list" if pax else "whole group, taxes included, Skyscanner list", fits=None if not exp else (True if (r.get("direct") or not exp.get("direct_only")) else False),
            quotable=False, connecting=not r.get("direct"), supplier=(r.get("airlines") or "").split(",")[0] or None,
            details={"stops": stops, "fare": "not shown (Skyscanner lists the cheapest fare; the airline's page has the fares)", "checked_bag": "not shown on the list", "refund_change": "not shown on the list",
                     "per_person": f"{r['per']:g} EUR (as the page says: per passenger)" if r.get("per") is not None else "not shown"}))
    n = len(offers)
    notes = [f"These are tickets {int(data['offset']) + 1} to {int(data['offset']) + n // 2 if n else 0} of each tab (the cheaper or better ones were shown before)."] if data.get("offset") else []
    notes += ["Skyscanner only compares: the price to quote comes from the airline's own page. Best and Cheapest tabs were read together."]
    where = f"{exp['leg']}: " if exp.get("leg") else ""        # one run per leg: each leg's own counts, not one leg's number for both
    if data.get("ads_skipped"):
        notes.append(f"{where}{data['ads_skipped']} sponsored ticket(s) were left out.")
    if data.get("results_total"):
        notes.append(f"{where}Skyscanner lists {data['results_total']} results for this search.")
    return SiteRows(offers=offers, read=n, total=data.get("results_total") or n, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="skyscanner_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def skyscanner_recipe_tool(origin: str, destination: str, day: date, adults: int = 2, children_ages: list[int] | None = None, direct_only: bool | None = None,
                                     cabin: str | None = None, operator_answered: bool = False, limit: int = BATCH, offset: int = 0) -> dict[str, Any]:
        """FOR SKYSCANNER (COMPARISON ONLY; one leg, one way; read in the operator's own Chrome with Claude in Chrome), next to the airlines and RateHawk. ASK FIRST: without `direct_only`
        (true/false) and `cabin` ('economy' / 'premium' / 'business' / 'first') it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers
        (`operator_answered`=true for "no preference", only after the operator replied). Then it returns the results url (filters in it) and a read-only SCRIPT: open the url, run the script
        with the javascript tool; it reads the Best and the Cheapest tabs (`limit` tickets each from `offset`, sponsored ones left out; for more call again with offset=offset+limit). The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. `origin` / `destination` are 3-letter airport or city codes; give `children_ages`. Skyscanner
        rows are comparison only: the price to quote comes from the airline's page. A human check (captcha) is never worked around: stop and tell the operator. One call per leg."""
        missing = [q for q, given in ((ASK["stops"], direct_only is not None), (ASK["cabin"], cabin is not None)) if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the airports and the travellers with the children's ages only if the request did not say them), "
                            "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = skyscanner_recipe(origin, destination, day, adults, children_ages, cabin or "economy", bool(direct_only), limit, offset)
        out["wishes"] = {"expect": out["expect"]}
        out["filters_used"] = [("Direct flights only (operator)" if direct_only else "Connections allowed (" + ("operator" if direct_only is not None else "default: no preference") + ")"),
                               f"{CABINS[cabin or 'economy'][1]} cabin (" + ("operator" if cabin else "default") + ")", "Best and Cheapest tabs read together (agency rule)"]
        out["more"] = f"For the next {limit} tickets of each tab call this tool again with the same values and offset={offset + limit}."
        # the server's own Chrome reads it first (28 Oct 2026, from the VPS: 36 tickets in 8 s, no check page); in auto mode the chat refuses a script that posts page data, so this one needs no script in the chat
        return await server_first(NAME, "SKYSCANNER_READ_IN_SERVER", "https://www.skyscanner.net", out)
