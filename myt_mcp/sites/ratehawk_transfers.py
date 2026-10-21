"""RateHawk transfers: a read-only script for the operator's own logged-in Chrome (a site module, see myt_mcp/sites/__init__.py).

RateHawk's transfer results address holds opaque place tokens (f=..., t=...), so the search is made once through RateHawk's own form
(tested flow in the playbook); the script then reads the results page and reports what the page says it searched, and convert() checks that
against the request (places, date, time, travellers) so a wrong search is refused.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows

NAME = "ratehawk_transfers"
SOURCE = "RateHawk Transfers"
GROUP = "Transfers"
HERE = Path(__file__).parent


def ratehawk_transfers_recipe(pickup_place: str, dropoff_place: str, day: str, pickup_time: str, adults: int, children_ages: list[int] | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", pickup_time):
        raise ValueError("pickup_time must be HH:MM (from the trip's flight or the operator; never your own choice)")
    if not re.fullmatch(r"\d{4}-\d\d-\d\d", day):
        raise ValueError("day must be YYYY-MM-DD")
    if not 1 <= adults <= 16:
        raise ValueError("adults must be between 1 and 16")
    ages = children_ages or []
    return {
        "script": (HERE / "ratehawk_transfers.js").read_text(encoding="utf-8"),
        "expect": {"pickup": pickup_place, "dropoff": dropoff_place, "day": day, "time": pickup_time, "adults": adults, "children": len(ages)},
        "steps": [
            "Open https://www.ratehawk.com/ in the operator's logged-in Chrome, click the Transfers tab, keep 'One way'. The form remembers the last search: replace every field.",
            "Pick-up point and drop-off: click the field once, select all (cmd+A), type a distinctive part of the name (an airport code like FCO, a hotel name), click the suggestion, and read the label back.",
            "Date: click it, pick the month then the day. Pick-up time: a list in 15-minute steps (pick the earlier one and say so). Passengers: adults, and 'Add children' with each age.",
            "Press Search, wait about 15 seconds until the cards show, then run `script` with the javascript tool (ok=false: wait and run once more). Never read the cards by eye.",
            "Pass its answer text UNCHANGED to compose_answer as site_results [{\"site\": \"ratehawk_transfers\", \"result\": <answer>, \"url\": <the page address>}], with `expect` as `wishes` (+ pickup_time) so the server checks the form."]}


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


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
    if exp:
        for key, label in (("pickup", "from"), ("dropoff", "to")):
            want, got = _norm(exp.get(key)), _norm(form.get(label))
            if want and got and not (want in got or got in want or set(want.split()) & set(got.split())):
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
    offers: list[Offer] = []
    for r in data.get("rows", []):
        cancel = r.get("cancellation") or ""
        cap = int(re.sub(r"\D", "", r.get("passengers") or "") or 0)
        need = (exp.get("adults") or 0) + (exp.get("children") or 0)
        offers.append(Offer(group=group, source=SOURCE, name=f"{r.get('vehicle_class') or 'class not shown'}: {(r.get('vehicle') or 'not shown')[:60]}", price_total=r.get("price"),
                            currency=r.get("currency"), price_basis="per vehicle, one way" + (f" ({r['child_seat']})" if r.get("child_seat") else ""),
                            flexible=cancel.lower().startswith("free cancellation") or None, fits=(cap >= need) if need and cap else None, supplier="RateHawk Transfers",
                            details={"capacity": f"up to {r.get('passengers')} people / {r.get('bags')} bags", "waiting_time": (r.get("waiting") or "").strip() or None,
                                     "cancellation": cancel or None, "provider": None, "meeting_point": (r.get("meeting") or "").strip() or None,
                                     "flight_tracking": "yes" if r.get("flight_tracking") else "no"}))
    n = int(data.get("rows_read") or len(offers))
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=data.get("price_order") == "ascending",
                    extra_notes=[f"RateHawk's page showed: {form.get('from')} to {form.get('to')}, {form.get('when')}, {form.get('passengers')}."])


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ratehawk_transfers_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_transfers_recipe_tool(pickup_place: str, dropoff_place: str, day: str, pickup_time: str, adults: int = 2, children_ages: list[int] | None = None) -> dict[str, Any]:
        """FOR TRANSFERS ON RATEHAWK (the agency's first choice): returns the steps to fill RateHawk's Transfers form once, and a tested read-only SCRIPT for
        the results page. The pick-up time is required (the trip's flight or the operator; never your own) and must be the same on Kiwitaxi and Mozio.
        Run the script on the results page and pass its answer unchanged to compose_answer in `site_results` as {"site": "ratehawk_transfers", "result":
        <answer>, "url": <page address>}, with `wishes` = the `expect` object returned here so the server can check the page searched what was asked."""
        return ratehawk_transfers_recipe(pickup_place, dropoff_place, day, pickup_time, adults, children_ages)
