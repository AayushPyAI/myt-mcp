"""El Al flights (one way, one leg per call): a read-only script for the results page of El Al's own booking engine, read in the operator's own Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 22 Oct 2026): there is no address for a search: the search is kept in the page's session, so the form (Modify panel or the home page) is filled once by hand and the
results page is booking.elal.com/booking/flights?market=IL&lang=en (the English page). Each flight row has ECONOMY / PREMIUM / BUSINESS columns; the price is PER PASSENGER (a 1-passenger search showed
the same Economy price as the 3-passenger one), in the market's currency (USD for the Israel market), "-" means not offered, "N left at this price" is the seats at that fare. The list does not show baggage
or refund terms. These are the airline's own prices: they are quotable.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, with_emit

NAME = "elal"
SOURCE = "El Al"
GROUP = "Flights"
HERE = Path(__file__).parent
RESULTS_URL = "https://booking.elal.com/booking/flights?market=IL&lang=en"
CABINS = {"economy": ("eco", "ECONOMY"), "premium": ("prem", "PREMIUM"), "business": ("biz", "BUSINESS")}
ASK = {"stops": "Direct only, or connections allowed?", "cabin": "Cabin: economy, premium, business, or any?"}


def elal_recipe(origin: str, destination: str, day: date, adults: int = 2, children: int = 0, seniors: int = 0, infants: int = 0, cabin: str = "any", direct_only: bool = False) -> dict[str, Any]:
    origin, destination = origin.strip().upper(), destination.strip().upper()
    if len(origin) != 3 or len(destination) != 3 or not origin.isalpha() or not destination.isalpha():
        raise ValueError("origin and destination must be 3-letter IATA airport codes (TLV, LIS)")
    if cabin != "any" and cabin not in CABINS:
        raise ValueError(f"cabin must be one of {sorted(CABINS)} or 'any'")
    if adults < 0 or children < 0 or seniors < 0 or infants < 0 or adults + seniors < 1 or infants > adults + seniors or adults + children + seniors > 9:
        raise ValueError("at least one adult or senior; infants no more than the adults and seniors; at most 9 seated passengers")
    pax = adults + children + seniors
    expect = {"origin": origin, "destination": destination, "day": day.isoformat(), "pax": pax, "adults": adults, "children": children, "seniors": seniors, "infants": infants, "cabin": cabin,
              "direct_only": direct_only, "leg": f"{origin} to {destination}, {day:%d %b %Y}"}
    steps = [f"Open https://booking.elal.com/ (El Al's own booking page, English) in the operator's Chrome; on a results page you can instead click Modify. Click 'One way'.",
             f"Where to: click the field, type the airport code ({destination}) and click the suggestion that shows exactly that code (the origin is {origin}; change it the same way if it is not). If it says 'No matching city/airport found', El Al does not fly there: say so and stop.",
             f"Departure: click the field, pick the month tab and the day {day:%d %b %Y} (the calendar shows the lowest price of each day; a day with no price has no seats), press Done.",
             f"Passengers: open the passenger box and set Senior {seniors}, Adults {adults}, Child {children}, Infant {infants}. Press Search. If a cookie banner is in the way, close it with the choice that declines non-essential cookies.",
             f"Wait about 10 seconds until the flights show: the page must be English and its heading must show {day:%d %B %Y} (the day strip above the flights). If the address is booking.elal.com/booking/flights in Hebrew, open {RESULTS_URL}. Then run `script` with the javascript tool; ok=false: do what `error` says; never read the rows by eye.",
             "Pass its answer parts UNCHANGED to compose_answer as site_results [{\"site\": \"elal\", \"result\": <part>, \"url\": <the results page address>}] with the returned `wishes`. For another day click that day in the strip and run the script again; \"Selling fast\" and \"N left at this price\" are the airline's own seat warnings."]
    return {"script": with_emit((HERE / "elal.js").read_text(encoding="utf-8")), "url": RESULTS_URL, "expect": expect, "steps": steps}


def _money(f: dict[str, Any] | None) -> tuple[float | None, str | None]:
    return (f.get("price"), f.get("currency")) if isinstance(f, dict) and f.get("price") is not None else (None, None)


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the El Al result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the El Al script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    if data.get("settled") is False:
        problems.append("El Al was still adding flights when the page was read: wait and run the script once more")
    if data.get("english") is False:
        problems.append("the El Al page is not in English: open booking.elal.com/booking/flights?market=IL&lang=en and run the script again")
    if exp:
        if data.get("route") != [exp["origin"], exp["destination"]]:
            problems.append(f"the page searched '{' to '.join(data.get('route') or []) or 'an unknown route'}', not {exp['origin']} to {exp['destination']}: search again")
        if data.get("trip") not in (None, "One way"):
            problems.append(f"the page searched '{data['trip']}', not 'One way': search again")
        if data.get("day") and data["day"] != exp["day"]:
            problems.append(f"the page shows {data['day']}, not {exp['day']}: click that day in the strip or search again")
        if data.get("pax") is not None and exp.get("pax") and data["pax"] != exp["pax"]:
            problems.append(f"the page searched {data['pax']} passengers, not {exp['pax']}: search again")
    pax = exp.get("pax") or data.get("pax") or 0
    offers: list[Offer] = []
    for r in data.get("rows", []):
        stops = r.get("stops") or "stops not shown"
        direct = stops.lower().startswith("non-stop")
        name = f"El Al {' + '.join(r.get('flights') or []) or 'flight'} {r.get('dep')}-{r.get('arr')} ({r.get('duration') or 'duration not shown'})"
        cabins = [c for c in CABINS if exp.get("cabin") in (None, "any", c)]
        for c in cabins:
            key, label = CABINS[c]
            per, cur = _money(r.get(key))
            if per is None:
                continue
            fare = r[key]
            offers.append(Offer(
                group=exp.get("leg") or group, source=SOURCE, name=name, price_total=round(per * pax, 2) if pax else per, currency=cur,
                price_basis=f"{per:g} {cur} per passenger x {pax} travellers (El Al lists per passenger; multiplied by the server)" if pax else "per passenger (traveller count unknown)",
                fits=(direct or not exp.get("direct_only")) if exp else None, connecting=not direct, supplier="El Al",
                details={"stops": stops, "fare": label + (" (lowest price of the day)" if fare.get("lowest") else ""), "checked_bag": "not shown on the list (fare rules on elal.com)",
                         "refund_change": "not shown on the list", "per_person": f"{per:g} {cur} (as the page says: per passenger)",
                         "seats_left": (f"{fare['left']} left at this price" if fare.get("left") else "not shown") + ("; the flight is marked 'Selling fast'" if r.get("selling_fast") else "")}))
    n = len(data.get("rows", []))
    notes = ["El Al prices are per passenger; the totals here are multiplied by the number of travellers. The search is not a shareable link: the operator searches again on elal.com to see it."]
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="elal_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def elal_recipe_tool(origin: str, destination: str, day: date, adults: int = 2, children: int = 0, seniors: int = 0, infants: int = 0, direct_only: bool | None = None,
                               cabin: str | None = None, operator_answered: bool = False) -> dict[str, Any]:
        """FOR EL AL (legs touching Israel; one leg, one way; read in the operator's own Chrome with Claude in Chrome, on El Al's own booking engine; these are the airline's own prices). ASK FIRST:
        without `direct_only` (true/false) and `cabin` ('economy' / 'premium' / 'business' / 'any') it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the
        answers (`operator_answered`=true for "no preference", only after the operator replied). Then it returns the steps to fill El Al's search once (there is no address for a search) and a read-only
        SCRIPT for the results page: run it there, give its answer parts unchanged to compose_answer in `site_results` as {"site": "elal", "result": <part>, "url": <the results page address>} with the
        returned `wishes`. Airport codes as `origin` / `destination`; passengers split into adults, children, seniors (60+) and infants. A human check is never worked around: stop and tell the operator."""
        missing = [q for q, given in ((ASK["stops"], direct_only is not None), (ASK["cabin"], cabin is not None)) if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the airports and the travellers split into adults, children, seniors and infants only if the request did not say "
                            "them), wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = elal_recipe(origin, destination, day, adults, children, seniors, infants, cabin or "any", bool(direct_only))
        out["wishes"] = {"expect": out["expect"]}
        out["filters_used"] = [("Direct flights only (operator)" if direct_only else "Connections allowed (" + ("operator" if direct_only is not None else "default: no preference") + ")"),
                               (f"{cabin.capitalize()} cabin (operator)" if cabin and cabin != "any" else "All cabins (" + ("operator" if cabin else "default: no preference") + ")")]
        return out
