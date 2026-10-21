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
from myt_mcp.sites import SiteRows

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
                         airport_in_terminal: bool = False, max_cars: int = 40) -> dict[str, Any]:
    for t in (pickup_time, dropoff_time):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise ValueError("times must be HH:MM, e.g. 10:00 (ask the operator or take it from the trip's flight: never pick one yourself)")
    for d in (pickup_date, dropoff_date):
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", d):
            raise ValueError("dates must be YYYY-MM-DD")
    if pickup_date + pickup_time >= dropoff_date + dropoff_time:
        raise ValueError("the drop-off must be after the pick-up")
    if not 5 <= max_cars <= 150:
        raise ValueError("max_cars must be between 5 and 150")
    ids = known_locations()
    p_id = pickup_id or ids.get(pickup.strip().lower())
    d_id = dropoff_id or (p_id if not dropoff else ids.get(dropoff.strip().lower()))
    filters = [FILTER_LABELS[k] for k, on in (("automatic", automatic), ("zero_excess", zero_excess), ("airport_in_terminal", airport_in_terminal)) if on]
    if not p_id or not d_id:
        missing = pickup if not p_id else (dropoff or pickup)
        return {"needs_location_id": missing, "steps": [
            "Open https://www.ratehawk.com/cars/ in the operator's logged-in Chrome, type the place in 'Pick-up location', choose the suggestion (an airport comes first), press Search.",
            "Read the number in `route=<id>,<id>` in the address (the tab's URL). Call this tool again with pickup_id (and dropoff_id if different). Nothing is booked."],
            "known_places": sorted(ids)}
    url = (f"https://www.ratehawk.com/cars/?route={p_id},{d_id}&date={pickup_date}T{pickup_time},{dropoff_date}T{dropoff_time}&age={driver_age}&residency={residency}")
    script = (HERE / "ratehawk_cars.js").read_text(encoding="utf-8").replace("__MAX_CARS__", str(max_cars)).replace("__FILTERS__", json.dumps(filters))
    return {"url": url, "filters_to_tick": filters, "script": script, "expect": {"pickup": pickup, "pickup_time": pickup_time, "dropoff_time": dropoff_time},
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
        notes.append(f"The list was cut at {n} cars (the cap); more cars exist on the page.")
    form = data.get("form") or {}
    notes.append(f"RateHawk's form showed: pick-up '{form.get('pickup')}', drop-off '{form.get('dropoff')}', times {form.get('times')}, {form.get('dates')}, driver {form.get('age_residency')}.")
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=False, extra_notes=notes)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ratehawk_cars_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_cars_recipe_tool(pickup: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, dropoff: str | None = None,
                                        pickup_id: int | None = None, dropoff_id: int | None = None, driver_age: str = "26,69", automatic: bool = False,
                                        zero_excess: bool = False, airport_in_terminal: bool = False, max_cars: int = 40) -> dict[str, Any]:
        """FOR CAR RENTAL ON RATEHAWK: returns the exact results URL and a tested read-only SCRIPT for the operator's logged-in Chrome. Times are required
        (from the trip's flight or the operator; never your own choice) and must be the same on Ofran. Open the url, run the script with the javascript
        tool, pass its answer unchanged to compose_answer in `site_results` as {"site": "ratehawk_cars", "result": <answer>, "url": <url>}. If it answers
        `needs_location_id`, follow its steps once to learn RateHawk's id for the place. `pickup` is the place name ('Faro Airport'); dates YYYY-MM-DD."""
        return ratehawk_cars_recipe(pickup, dropoff, pickup_date, pickup_time, dropoff_date, dropoff_time, pickup_id, dropoff_id, driver_age, "il", automatic, zero_excess, airport_in_terminal, max_cars)
