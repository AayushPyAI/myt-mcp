"""RateHawk train tickets (one way, one leg per call): a URL and a tested read-only script for the operator's own logged-in Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 22 Oct 2026): the address is railway/?from=<station id>&to=<station id>&date=YYYY-MM-DD&time=HH:MM&adt=<adults>; the station ids are
learned once (ratehawk_stations.json). The filters (changes, service class) are NOT in the address: the script ticks them. 15 cards come first, "Load more" gives more. The "from"
price of a class is for the WHOLE group of adults (30.69 for 1 adult, 61.38 for 2). The list does not show refund terms or seats left (Select fare does).
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, place_matches, with_emit

NAME = "ratehawk_trains"
SOURCE = "RateHawk Trains"
NEEDS_WIDE_WINDOW = True       # a narrow window shows the mobile layout, which the script cannot read
GROUP = "Trains"
HERE = Path(__file__).parent
CHANGES = {"direct": "Direct route", "one_change": "Up to 1 change of train", "any": "All routes"}
CLASSES = {"standard": "Standard", "comfort": "Comfort", "premier": "Premier"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
ASK_TRAINS = {"changes": "Direct trains only, up to 1 change, or any?", "class": "Class: standard, comfort, premier, or no preference?", "budget": "Budget for the whole group in EUR, or no preference?"}
BATCH = 30


def known_stations() -> dict[str, int]:
    data = json.loads((HERE / "ratehawk_stations.json").read_text(encoding="utf-8"))
    return {k: int(v) for k, v in data.items() if not k.startswith("_")}


def not_available_station(*names: str) -> str | None:
    data = json.loads((HERE / "ratehawk_stations.json").read_text(encoding="utf-8"))
    banned = {_norm(n) for n in data.get("_not_available", {}).get("names", [])}
    return next((n for n in names if n and any(w in banned for w in [_norm(n), _norm(n).split(" ")[0]])), None)


def ratehawk_trains_recipe(origin: str, destination: str, day: date, time: str, adults: int = 2, changes: str = "any", train_class: str | None = None,
                           origin_id: int | None = None, destination_id: int | None = None, offset: int = 0, limit: int = BATCH) -> dict[str, Any]:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time):
        raise ValueError("time must be HH:MM (the earliest departure: the operator's or the trip's, never your own)")
    if not 1 <= adults <= 9 or changes not in CHANGES or (train_class and train_class not in CLASSES):
        raise ValueError(f"adults 1-9, changes one of {sorted(CHANGES)}, class one of {sorted(CLASSES)} or left out")
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("offset must be 0 or more and limit 1-100")
    if not (origin_id and destination_id) and (gone := not_available_station(origin, destination)):
        return {"not_served": gone, "next": f"Nothing was opened. RateHawk's Train tickets search does not offer '{gone}': put RateHawk Train tickets in not_checked with the reason 'route not served: RateHawk's train search has no {gone} station'. Do not look for the station on the page."}
    ids = known_stations()
    o_id = origin_id or ids.get(re.sub(r"\s+", " ", origin.strip().lower()))
    d_id = destination_id or ids.get(re.sub(r"\s+", " ", destination.strip().lower()))
    if not o_id or not d_id:
        missing = origin if not o_id else destination
        return {"needs_station_id": missing, "known_stations": sorted(ids), "steps": [
            "Open https://www.ratehawk.com/ in the operator's logged-in Chrome, click the Train tickets tab, type the station in From / To and pick the suggestion with the same name, press Search.",
            "Read the numbers in `from=<id>&to=<id>` in the results address (the tab's URL). Call this tool again with origin_id and destination_id. Nothing is booked."]}
    url = f"https://www.ratehawk.com/railway/?from={o_id}&to={d_id}&date={day.isoformat()}&time={quote(time, safe='')}&adt={adults}"
    script = with_emit((HERE / "ratehawk_trains.js").read_text(encoding="utf-8")).replace("__CHANGES__", CHANGES[changes] if changes != "any" else "").replace("__CLASS__", CLASSES.get(train_class or "", ""))
    script = script.replace("__SKIP__", str(offset)).replace("__LIMIT__", str(limit))
    expect = {"origin": origin, "destination": destination, "day": day.isoformat(), "adults": adults, "changes": changes, "class": train_class, "leg": f"{origin} to {destination}, {day:%d %b %Y}"}
    return {"url": url, "script": script, "expect": expect}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _price_text(c: dict[str, Any]) -> str:
    return f"{c['price']:g} {c.get('currency') or ''}".strip()


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the RateHawk trains result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the RateHawk trains script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    if data.get("settled") is False:
        problems.append("RateHawk was still adding trains when the list was read: wait and run the script once more")
    if exp:
        allowed = {"One way", CHANGES.get(exp.get("changes") or "any")}
        allowed |= {CLASSES[exp["class"]]} if exp.get("class") else set()
        ticked = data.get("page_ticked") or []
        extra = [f for f in ticked if f not in allowed]
        missing = [f for f in allowed if f and f not in ticked]
        if extra or missing:
            problems.append(f"RateHawk's filters are not as asked (unexpected: {', '.join(extra) or 'none'}; missing: {', '.join(missing) or 'none'}): open the url again and run the script once more")
    adults = exp.get("adults")
    offers: list[Offer] = []
    for r in data.get("rows", []):
        route = _norm(r.get("route"))
        if exp.get("origin") and exp.get("destination"):
            sides = (r.get("route") or "").split("\u2192")          # "From -> To": the direction matters
            if len(sides) == 2 and not (place_matches(exp["origin"], sides[0]) and place_matches(exp["destination"], sides[1])):
                problems.append(f"a card is for '{r.get('route')}', not {exp['origin']} to {exp['destination']}: open the url again")
                break
        if exp.get("day"):
            m = re.match(r"(\d{1,2}) ([A-Z][a-z]+)", r.get("date") or "")
            if m and (int(m.group(1)) != int(exp["day"][8:10]) or m.group(2) != MONTHS[int(exp["day"][5:7]) - 1]):
                problems.append(f"a card is for '{r.get('date')}', not {exp['day']}: open the url again")
                break
        for c in r.get("classes") or []:
            if c.get("price") is None or (exp.get("class") and c["name"].lower() != exp["class"]):
                continue
            fits: bool | None = True
            if wishes.get("max_total") is not None:
                fits = c["price"] <= float(wishes["max_total"])
            changes_text = r.get("changes") or "not shown"
            if exp.get("changes") == "direct" and not changes_text.lower().startswith("direct"):
                fits = False
            offers.append(Offer(
                group=exp.get("leg") or group, source=SOURCE, name=f"{r.get('train')} {r.get('dep')}-{r.get('arr')} ({r.get('travel')}) {c['name']}" + (f", {r['tag'].lower()}" if r.get("tag") else ""),      # the class is in the name: Standard and Premier can cost the same
                price_total=c["price"], currency=c.get("currency"), price_basis=f"cheapest {c['name']} fare for {adults or 'the'} adult(s), whole group", fits=fits if wishes else None, supplier="RateHawk Trains",
                details={"class_fare": f"{c['name']} from {_price_text(c)}", "changes": changes_text, "seats_left": "not shown on the list (open Select fare)", "conditions": "not shown on the list (open Select fare)"}))
    n = len(data.get("rows", []))
    notes = [f"The page lists {data['cards_total']} trains with these filters (all loaded)." if data.get("cards_total") and data.get("all_loaded") else "More trains exist on the page than were loaded."] if data.get("cards_total") else []
    notes += ["RateHawk shows 'from' prices (the cheapest fare of each class); the exact fare and its refund and change conditions are on its Select fare page."]
    if data.get("offset"):
        notes.append(f"These are trains {int(data['offset']) + 1} to {int(data['offset']) + n} of the list.")
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ratehawk_trains_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_trains_recipe_tool(origin: str, destination: str, day: date, time: str, adults: int = 2, changes: str | None = None, train_class: str | None = None,
                                          max_total: float | None = None, operator_answered: bool = False, origin_id: int | None = None, destination_id: int | None = None,
                                          offset: int = 0, limit: int = BATCH) -> dict[str, Any]:
        """FOR TRAINS ON RATEHAWK (one leg, one way; read in the operator's own Chrome with Claude in Chrome), next to Trenitalia. ASK FIRST: without `changes` ('direct' / 'one_change' / 'any'),
        `train_class` ('standard' / 'comfort' / 'premier') and `max_total` (EUR, whole group) it opens nothing and returns `ask_operator`: ask those questions in ONE message, wait, call again with
        the answers (`operator_answered`=true for "no preference", only after the operator replied). `time` is the earliest departure (HH:MM, the operator's or the trip's). Then it returns the
        results url and a read-only SCRIPT: open the url, run the script with the javascript tool; it ticks the filters, presses Load more and reads the next `limit` (30) trains from `offset`. The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row with the returned `wishes` and `filters_used`. Station names
        as RateHawk writes them ('Firenze Santa Maria Novella', 'Roma Termini'); an unknown station returns steps to learn its id once. One call per leg."""
        missing = [q for q, given in ((ASK_TRAINS["changes"], changes is not None), (ASK_TRAINS["class"], train_class is not None), (ASK_TRAINS["budget"], max_total is not None)) if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the stations, the day, the earliest departure and the travellers only if the request did not say them), "
                            "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = ratehawk_trains_recipe(origin, destination, day, time, adults, changes or "any", train_class, origin_id, destination_id, offset, limit)
        if "url" in out:
            out["wishes"] = {"expect": out["expect"], "max_total": max_total}
            out["filters_used"] = [f"{CHANGES[changes or 'any']} (" + ("operator" if changes else "default: no preference") + ")"] + ([f"{CLASSES[train_class]} class (operator)"] if train_class else []) + \
                ([f"budget up to {max_total:g} EUR for the group (operator)"] if max_total is not None else []) + [f"earliest departure {time} (operator)"]
            out["more"] = f"For the next {limit} trains call this tool again with the same values and offset={offset + limit}."
        return out
