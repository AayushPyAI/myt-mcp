"""RateHawk car rental: a URL and a tested read-only script for the operator's own logged-in Chrome (a site module, see myt_mcp/sites/__init__.py)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, with_emit

NAME = "ratehawk_cars"
SOURCE = "RateHawk Car rental"
GROUP = "Cars"
HERE = Path(__file__).parent
FILTER_LABELS = {"automatic": "Automatic", "manual": "Manual", "zero_excess": "Zero excess", "full_insurance": "Full insurance", "refundable_excess": "Refundable excess",
                 "airport_in_terminal": "Airport (in the terminal)"}


def known_locations() -> dict[str, int]:
    data = json.loads((HERE / "ratehawk_locations.json").read_text(encoding="utf-8"))
    return {k: int(v) for k, v in data.items() if not k.startswith("_")}


def ratehawk_cars_recipe(pickup: str, dropoff: str | None, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, pickup_id: int | None = None,
                         dropoff_id: int | None = None, driver_age: str = "26,69", residency: str = "il", automatic: bool = False, zero_excess: bool = False,
                         airport_in_terminal: bool = False, max_cars: int = 40, manual: bool = False, offset: int = 0, limit: int | None = None) -> dict[str, Any]:
    for t in (pickup_time, dropoff_time):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise ValueError("times must be HH:MM, e.g. 10:00 (ask the operator or take it from the trip's flight: never pick one yourself)")
    for d in (pickup_date, dropoff_date):
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", d):
            raise ValueError("dates must be YYYY-MM-DD")
    if pickup_date + pickup_time >= dropoff_date + dropoff_time:
        raise ValueError("the drop-off must be after the pick-up")
    if limit is not None:      # the operator's window: cars [offset, offset + limit) of the price-sorted list
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("offset must be 0 or more and limit 1-100")
        max_cars, skip = offset + limit, offset
    else:
        skip = 0
    if not 5 <= max_cars <= 250:
        raise ValueError("max_cars must be between 5 and 250")
    ids = known_locations()
    p_id = pickup_id or ids.get(pickup.strip().lower())
    d_id = dropoff_id or (p_id if not dropoff else ids.get(dropoff.strip().lower()))
    filters = [FILTER_LABELS[k] for k, on in (("automatic", automatic), ("manual", manual), ("zero_excess", zero_excess), ("airport_in_terminal", airport_in_terminal)) if on]
    if not p_id or not d_id:
        missing = pickup if not p_id else (dropoff or pickup)
        return {"needs_location_id": missing, "steps": [
            "Open https://www.ratehawk.com/cars/ in the operator's logged-in Chrome, type the place in 'Pick-up location', choose the suggestion (an airport comes first), press Search.",
            "Read the number in `route=<id>,<id>` in the address (the tab's URL). Call this tool again with pickup_id (and dropoff_id if different). Nothing is booked."],
            "known_places": sorted(ids)}
    url = (f"https://www.ratehawk.com/cars/?route={p_id},{d_id}&date={pickup_date}T{pickup_time},{dropoff_date}T{dropoff_time}&age={driver_age}&residency={residency}")
    script = with_emit((HERE / "ratehawk_cars.js").read_text(encoding="utf-8")).replace("__MAX_CARS__", str(max_cars)).replace("__SKIP__", str(skip)).replace("__FILTERS__", json.dumps(filters))
    return {"required_next": "Your answer is the text compose_answer returns, shown unchanged: never write the table or the picks yourself. Order: task_plan -> the recipe tool -> run its script in Chrome -> compose_answer -> check_answer. The script's answer comes in parts (`part 1 of N`): run `window.__mytParts[1]`, `[2]` ... in the same tab with the javascript tool and pass EVERY part, unchanged, as its own item of site_results.", "url": url, "filters_to_tick": filters, "script": script, "expect": {"pickup": pickup, "pickup_time": pickup_time, "dropoff_time": dropoff_time},
            "steps": ["Open `url` in the operator's logged-in RateHawk tab; if it asks to log in, stop and tell the operator. Wait about 12 seconds for the cards.",
                      "Run `script` with the javascript tool (it ticks the filters, scrolls to load the cars, reads each card). ok=false means do what `error` says; never read the cards by eye.",
                      "Pass its answer text UNCHANGED to compose_answer as site_results [{\"site\": \"ratehawk_cars\", \"result\": <answer>, \"url\": <url>}]; give `pickup_time` there too (the same on every source)."]}


def _num(v: Any) -> int | float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    problems: list[str] = []
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the RateHawk cars result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the RateHawk cars script reported: {data.get('error', 'not ok')}"])
    if data.get("price_order") == "mixed":
        problems.append("the car prices are not in one order: the page may have changed while reading")
    if "page_ticked" in data:        # a filter RateHawk kept from an earlier visit would change the list without the operator asking for it
        expected = set(data.get("filters_ticked") or [])
        extra = [f for f in data["page_ticked"] if f not in expected and not re.search(r"\byears?\b", f)]
        if extra:
            problems.append(f"RateHawk shows filters the operator did not ask for ({', '.join(extra)}): clear them on the page, open the url again and run the script once more")
    offers: list[Offer] = []
    for r in data.get("rows", []):
        price, cur = r.get("price"), r.get("currency")
        cancel = r.get("cancellation") or ""
        insurance = r.get("insurance") or ""
        fits: bool | None = None
        if wishes:
            ok = True
            if wishes.get("automatic"):
                ok &= (r.get("gearbox") or "").lower() == "automatic"
            if wishes.get("manual"):
                ok &= (r.get("gearbox") or "").lower() == "manual"
            if wishes.get("min_seats"):
                seats = _num(r.get("seats"))
                ok &= seats is not None and seats >= int(wishes["min_seats"])
            if wishes.get("max_total") is not None:
                ok &= price is not None and price <= float(wishes["max_total"])
            if wishes.get("zero_excess"):
                ok &= insurance.lower() in ("zero excess", "full insurance")
            fits = ok
        seats_bags = " / ".join(x for x in (f"{r['seats']} seats" if r.get("seats") else None, f"{r['large_bags']} large + {r['small_bags']} small bags" if r.get("large_bags") is not None else None) if x) or None
        offers.append(Offer(group=group, source=SOURCE, name=f"{r.get('car') or 'not shown'} ({r.get('code_class') or 'class not shown'})", price_total=price, currency=cur,
                            price_basis="whole rental", flexible=cancel.lower().startswith("free cancellation") or None, fits=fits, supplier=r.get("company"),
                            details={"company": (r.get("company") or "not shown") + (" (from the logo's file name)" if r.get("company_from") == "logo file name" else ""),
                                     "gearbox": r.get("gearbox"), "seats_bags": seats_bags,
                                     "excess": (f"{r['excess']:,.0f} excess" if r.get("excess") is not None else None) and f"{insurance}: excess {r['excess']:,.0f}" or insurance or None,
                                     "fuel": (r.get("mileage_fuel") or "").split("•")[-1].strip() or None, "mileage": (r.get("mileage_fuel") or "").split("•")[0].strip() or None,
                                     "deposit": f"{r['deposit']:,.0f}" if r.get("deposit") is not None else None, "cancellation": cancel or None,
                                     "pickup_place": r.get("pickup_place"), "score": r.get("score")}))
    n = int(data.get("rows_read") or len(offers))
    notes = []
    if data.get("reached_cap"):
        notes.append(f"The list was cut at {int(data.get('offset') or 0) + n} cars; more cars exist on the page.")
    if data.get("offset"):
        notes.append(f"These are cars {int(data['offset']) + 1} to {int(data['offset']) + n} of the list (cheaper ones were shown before): the Cheapest here is not the cheapest overall.")
    form = data.get("form") or {}
    notes.append(f"RateHawk's form showed: pick-up '{form.get('pickup')}', drop-off '{form.get('dropoff')}', times {form.get('times')}, {form.get('dates')}, driver {form.get('age_residency')}.")
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=False, extra_notes=notes)


ASK_CARS = {"gearbox": "Gearbox: automatic, manual, or no preference?", "seats": "How many people (minimum seats), or no preference?",
            "excess": "Zero excess (full cover) needed, or no preference?", "budget": "Budget for the whole rental in EUR, or no preference?"}


def cars_ask_gate(gearbox: str | None, min_seats: int | None, zero_excess: bool | None, max_total: float | None, operator_answered: bool) -> dict[str, Any] | None:
    """Nothing is opened until the operator has said what they want (each answer may be 'no preference')."""
    missing = [q for q, given in ((ASK_CARS["gearbox"], gearbox is not None), (ASK_CARS["seats"], min_seats is not None), (ASK_CARS["excess"], zero_excess is not None),
                                  (ASK_CARS["budget"], max_total is not None)) if not given]
    if not missing or operator_answered:
        return None
    return {"ok": False, "ask_operator": missing, "searched": False,
            "next": "Nothing was opened. Ask the operator these questions in ONE message (add the pick-up / drop-off place, dates and TIMES and the driver's age only if the request did not give them), "
                    "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ratehawk_cars_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_cars_recipe_tool(pickup: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, dropoff: str | None = None,
                                        pickup_id: int | None = None, dropoff_id: int | None = None, driver_age: str = "26,69", gearbox: str | None = None,
                                        min_seats: int | None = None, zero_excess: bool | None = None, max_total: float | None = None, airport_in_terminal: bool = False,
                                        operator_answered: bool = False, offset: int = 0, limit: int = 30) -> dict[str, Any]:
        """FOR CAR RENTAL ON RATEHAWK (read in the operator's own Chrome with Claude in Chrome). ASK FIRST: without `gearbox` ('automatic' / 'manual'), `min_seats`,
        `zero_excess` (true/false) and `max_total` (EUR, whole rental) it opens nothing and returns `ask_operator`: ask those questions in ONE message, wait, call again
        with the answers (`operator_answered`=true for "no preference", only after the operator replied). Times are required (from the trip's flight or the operator; never
        your own choice) and the same on Ofran. Then it returns the results URL and a read-only SCRIPT: open the url, run the script with the javascript tool; it reads the next
        `limit` (30) cars from `offset`. Give its answer parts unchanged to compose_answer in `site_results` as {"site": "ratehawk_cars", "result": <part>, "url": <the url>} with
        the returned `wishes`, `filters_used` and `pickup_time`. For more cars call again with offset=offset+limit. If it answers `needs_location_id`, follow its steps once to learn
        RateHawk's id for the place. `pickup` is the place name ('Faro Airport'); dates YYYY-MM-DD."""
        asked = cars_ask_gate(gearbox, min_seats, zero_excess, max_total, operator_answered)
        if asked:
            return asked
        if gearbox not in (None, "automatic", "manual"):
            raise ValueError("gearbox must be 'automatic', 'manual' or left out")
        out = ratehawk_cars_recipe(pickup, dropoff, pickup_date, pickup_time, dropoff_date, dropoff_time, pickup_id, dropoff_id, driver_age, "il", gearbox == "automatic", bool(zero_excess),
                                   airport_in_terminal, 40, gearbox == "manual", offset, limit)
        if "url" in out:
            out["wishes"] = {"automatic": gearbox == "automatic", "manual": gearbox == "manual", "zero_excess": bool(zero_excess), "min_seats": min_seats, "max_total": max_total}
            out["filters_used"] = ([f"{gearbox.capitalize()} gearbox (operator)"] if gearbox else []) + (["Zero excess (operator)"] if zero_excess else []) + \
                ([f"at least {min_seats} seats (operator)"] if min_seats else []) + ([f"budget up to {max_total:g} EUR for the whole rental (operator)"] if max_total is not None else []) + \
                (["Airport (in the terminal) (operator)"] if airport_in_terminal else []) + [f"driver age {driver_age} (default: the agency's)"]
            out["pickup_time"] = pickup_time
            out["more"] = f"For the next {limit} cars call this tool again with the same values and offset={offset + limit}; say so to the operator at the end of the answer."
        return out
