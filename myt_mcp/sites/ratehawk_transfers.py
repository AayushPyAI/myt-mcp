"""RateHawk transfers: a read-only script for the operator's own logged-in Chrome (a site module, see myt_mcp/sites/__init__.py).

RateHawk's transfer results address holds opaque place tokens (f=..., t=...), so the search is made once through RateHawk's own form
(tested flow in the playbook); the script then reads the results page and reports what the page says it searched, and convert() checks that
against the request (places, date, time, travellers) so a wrong search is refused.
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
from myt_mcp.sites import SiteRows, place_matches, with_emit

NAME = "ratehawk_transfers"
SOURCE = "RateHawk Transfers"
NEEDS_WIDE_WINDOW = True       # a narrow window shows the mobile layout, which the script cannot read
GROUP = "Transfers"
HERE = Path(__file__).parent


def ratehawk_transfers_recipe(pickup_place: str, dropoff_place: str, day: str, pickup_time: str, adults: int, children_ages: list[int] | None = None, sort_tab: str | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", pickup_time):
        raise ValueError("pickup_time must be HH:MM (from the trip's flight or the operator; never your own choice)")
    if not re.fullmatch(r"\d{4}-\d\d-\d\d", day):
        raise ValueError("day must be YYYY-MM-DD")
    if not 1 <= adults <= 16:
        raise ValueError("adults must be between 1 and 16")
    ages = children_ages or []
    return {
        "required_next": "Your answer is the text compose_answer returns, shown unchanged: never write the table or the picks yourself. Order: task_plan -> the recipe tool -> run its script in Chrome -> compose_answer -> check_answer. The script's answer comes in parts (`part 1 of N`): run `window.__mytParts[1]`, `[2]` ... in the same tab with the javascript tool and pass EVERY part, unchanged, as its own item of site_results (only when the answer says `part 1 of N`; an `ingest` receipt has no parts).",
        "script": with_emit((HERE / "ratehawk_transfers.js").read_text(encoding="utf-8")),
        "expect": {"pickup": pickup_place, "dropoff": dropoff_place, "day": day, "time": pickup_time, "adults": adults, "children": len(ages), **({"sort_tab": sort_tab} if sort_tab else {})},
        "steps": [
            "Open https://www.ratehawk.com/ in the operator's logged-in Chrome, click the Transfers tab, keep 'One way'. The form remembers the last search: replace every field.",
            "Pick-up point and drop-off: click the field once, select all (cmd+A), type a distinctive part of the name (an airport code like FCO, a hotel name), click the suggestion, and read the label back.",
            "Date: click it, pick the month then the day. Pick-up time: a list in 15-minute steps (pick the earlier one and say so). Passengers: adults, and 'Add children' with each age.",
            "Press Search, wait about 15 seconds until the cards show, then run `script` with the javascript tool (ok=false: wait and run once more). Never read the cards by eye.",
            "The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row, with `expect` as `wishes` (+ pickup_time) so the server checks the form."]}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def leg_name(expect: dict[str, Any]) -> str | None:
    if not (expect.get("pickup") and expect.get("dropoff") and expect.get("day")):
        return None
    try:
        day = date.fromisoformat(expect["day"]).strftime("%d %b %Y")
    except ValueError:
        day = expect["day"]
    return f"{expect['pickup']} to {expect['dropoff']}, {day}"


def search_of(expect: dict[str, Any]) -> tuple[Any, str | None] | None:
    """Each leg is its own search (28 Oct 2026: the two legs were one table 'Transfers' and the same car at the same price collapsed into one row)."""
    name = leg_name(expect)
    return ((expect.get("pickup"), expect.get("dropoff"), expect.get("day"), expect.get("time")), name) if name else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the RateHawk transfers result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the RateHawk transfers script reported: {data.get('error', 'not ok')}"])
    problems: list[str] = []
    form = data.get("form") or {}
    exp = wishes.get("expect") or {}
    group = leg_name(exp) or group
    if exp:
        for key, label in (("pickup", "from"), ("dropoff", "to")):
            if exp.get(key) and form.get(label) and not place_matches(exp[key], form[label]):
                problems.append(f"the page searched {label} '{form.get(label)}', not '{exp.get(key)}': search again with the right place")
        if exp.get("time") and exp["time"] not in (form.get("when") or ""):
            problems.append(f"the page searched '{form.get('when')}', not at {exp['time']}: search again with the right time")
        if exp.get("day"):
            m = re.match(r"(\d{1,2}) ([A-Z][a-z]{2})", form.get("when") or "")
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            if m and (int(m.group(1)) != int(exp["day"][8:10]) or months[int(exp["day"][5:7]) - 1] != m.group(2)):
                problems.append(f"the page searched '{form.get('when')}', not {exp['day']}: search again with the right date")
        adults, kids = exp.get("adults"), exp.get("children", 0)
        pax = form.get("passengers") or ""
        ma, mc = re.search(r"(\d+)\s+adult", pax), re.search(r"(\d+)\s+child", pax)
        got_a, got_c = (int(ma.group(1)) if ma else None), (int(mc.group(1)) if mc else 0)
        if adults and got_a is not None and (got_a != adults or got_c != (kids or 0)):
            problems.append(f"the page searched '{pax}', not {adults} adults and {kids} children: search again")
    if exp.get("sort_tab") and data.get("sort_tab") and data["sort_tab"] != exp["sort_tab"]:
        problems.append(f"the page is on the '{data['sort_tab']}' tab, not '{exp['sort_tab']}': click that tab and run the script once more")
    if "page_ticked" in data:        # a box RateHawk kept from an earlier visit changes the list without the operator asking for it
        allowed = {"With flight tracking"} if wishes.get("flight_tracking") else set()
        extra = [f for f in data["page_ticked"] if f not in allowed]
        if extra:
            problems.append(f"RateHawk shows filters the operator did not ask for ({', '.join(extra)}): clear them on the page and run the script once more")
    offers: list[Offer] = []
    for r in data.get("rows", []):
        cancel = r.get("cancellation") or ""
        cap = int(re.sub(r"\D", "", r.get("passengers") or "") or 0)
        need = (exp.get("adults") or 0) + (exp.get("children") or 0)
        bags = int(re.sub(r"\D", "", r.get("bags") or "") or 0)
        fit = (cap >= need) if need and cap else None
        if fit is not False and wishes.get("min_bags"):
            fit = bool(bags) and bags >= int(wishes["min_bags"])
        if fit is not False and wishes.get("flight_tracking"):
            fit = bool(r.get("flight_tracking"))
        if fit is not False and wishes.get("max_total") is not None:
            fit = r.get("price") is not None and r["price"] <= float(wishes["max_total"])
        offers.append(Offer(group=group, source=SOURCE, name=f"{r.get('vehicle_class') or 'class not shown'}: {(r.get('vehicle') or 'not shown')[:60]}", price_total=r.get("price"),
                            currency=r.get("currency"), price_basis="per vehicle, one way" + (f" ({r['child_seat']})" if r.get("child_seat") else ""),
                            flexible=cancel.lower().startswith("free cancellation") or None, fits=fit, supplier="RateHawk Transfers",
                            details={"capacity": f"up to {r.get('passengers')} people / {r.get('bags')} bags", "waiting_time": (r.get("waiting") or "").strip() or None,
                                     "cancellation": cancel or None, "provider": None, "meeting_point": (r.get("meeting") or "").strip() or None,
                                     "flight_tracking": "yes" if r.get("flight_tracking") else "no"}))
    n = int(data.get("rows_read") or len(offers))
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=data.get("price_order") == "ascending",
                    extra_notes=[f"RateHawk's page showed: {form.get('from')} to {form.get('to')}, {form.get('when')}, {form.get('passengers')}."])


ASK_TRANSFERS = {"bags": "How many suitcases / bags?", "tracking": "Flight tracking needed (airport pick-up)?",
                 "vehicle": "Vehicle: cheapest, comfortable, spacious, or no preference?", "budget": "Budget for the transfer in EUR, or no preference?"}
TABS = {"cheapest": "Cheapest", "comfortable": "Comfortable", "spacious": "Spacious"}


def transfers_ask_gate(bags: int | None, flight_tracking: bool | None, vehicle: str | None, max_total: float | None, operator_answered: bool) -> dict[str, Any] | None:
    """Nothing is opened until the operator has said what they want (each answer may be 'no preference')."""
    missing = [q for q, given in ((ASK_TRANSFERS["bags"], bags is not None), (ASK_TRANSFERS["tracking"], flight_tracking is not None), (ASK_TRANSFERS["vehicle"], vehicle is not None),
                                  (ASK_TRANSFERS["budget"], max_total is not None)) if not given]
    if not missing or operator_answered:
        return None
    return {"ok": False, "ask_operator": missing, "searched": False,
            "next": "Nothing was opened. Ask the operator these questions in ONE message (add the places, the date and the pick-up TIME, and the passengers with the children's ages, only if the request did not give them), "
                    "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ratehawk_transfers_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_transfers_recipe_tool(pickup_place: str, dropoff_place: str, day: str, pickup_time: str, adults: int = 2, children_ages: list[int] | None = None,
                                             bags: int | None = None, flight_tracking: bool | None = None, vehicle: str | None = None, max_total: float | None = None,
                                             operator_answered: bool = False) -> dict[str, Any]:
        """FOR TRANSFERS ON RATEHAWK (the agency's first choice; read in the operator's own Chrome with Claude in Chrome). ASK FIRST: without `bags`, `flight_tracking` (true/false),
        `vehicle` ('cheapest' / 'comfortable' / 'spacious') and `max_total` (EUR) it opens nothing and returns `ask_operator`: ask those questions in ONE message, wait, call again with the
        answers (`operator_answered`=true for "no preference", only after the operator replied). The pick-up time is required (the trip's flight or the operator; never your own) and must be
        the same on RateHawk and Kiwitaxi. Then it returns the steps to fill RateHawk's Transfers form once and a read-only SCRIPT for the results page. The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row, with the returned `wishes`, `filters_used` and `pickup_time`."""
        asked = transfers_ask_gate(bags, flight_tracking, vehicle, max_total, operator_answered)
        if asked:
            return asked
        if vehicle not in (None, *TABS):
            raise ValueError("vehicle must be 'cheapest', 'comfortable', 'spacious' or left out")
        out = ratehawk_transfers_recipe(pickup_place, dropoff_place, day, pickup_time, adults, children_ages, TABS.get(vehicle or "cheapest"))
        out["wishes"] = {"expect": out["expect"], "min_bags": bags, "flight_tracking": bool(flight_tracking), "max_total": max_total, "vehicle": vehicle}
        out["filters_used"] = [f"{TABS[vehicle]} tab (operator)"] if vehicle else ["Cheapest tab (default)"]
        out["filters_used"] += ([f"at least {bags} bags (operator)"] if bags else []) + (["With flight tracking (operator)"] if flight_tracking else []) + \
            ([f"budget up to {max_total:g} EUR (operator)"] if max_total is not None else [])
        out["pickup_time"] = pickup_time
        return out
