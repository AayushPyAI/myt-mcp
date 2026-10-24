"""Ofran car rental (the agency's own logged-in Ofran): steps to make the search once and a tested read-only script for the results page, read in the operator's own Chrome (a site module).

Site rules (found on the real page, 22 Oct 2026): the results page (ofran.co.il/reservation/results) IGNORES the dates in its address and shows the last search made with the form, so the search is
made with the form and the script returns what the page says it searched (places, dates, times, driver age) for the server to check. All cars are in the page at once. Each card shows the
supplier as a logo whose alt text is the name, ACRISS code, class, car, seats, gearbox, doors, bags, excess text, the pick-up station, "price before the discount" and "price after the discount"
(the agent's price: the top bar must show the agent's name). Fuel, mileage, deposit and cancellation are not on the list. The page's own filters (gearbox, excess cancellation, inside the airport)
are ticked by the script and reported. Times are the operator's or the trip's, never a guess.
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
from myt_mcp.sites import SiteRows, place_matches, with_emit
from myt_mcp.sites.ratehawk_cars import cars_ask_gate

NAME = "ofran"
SOURCE = "Ofran"
GROUP = "Cars"
HERE = Path(__file__).parent
LABELS = {"automatic": "אוטומטית", "manual": "ידנית", "zero_excess": "ביטול השתתפות עצמית", "inside_airport": "בתוך שדה התעופה"}
BATCH = 30
HOME = "https://ofran.co.il/"


STATIONS_EN = {"תחנת איסוף בתוך שדה התעופה": "Pick-up station inside the airport", "תחנת איסוף מחוץ לשדה התעופה": "Pick-up station outside the airport (not at the terminal)"}


def station_text(text: str | None) -> str | None:
    """Ofran writes the pick-up station in Hebrew: the two wordings it uses are given in English, any other stays as the page wrote it."""
    return STATIONS_EN.get((text or "").strip(), text)


def ofran_recipe(pickup: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, automatic: bool = False, manual: bool = False, zero_excess: bool = False,
                 inside_airport: bool = False, offset: int = 0, limit: int = BATCH, driver_years: int | None = None) -> dict[str, Any]:
    for t in (pickup_time, dropoff_time):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise ValueError("times must be HH:MM, e.g. 10:00 (ask the operator or take it from the trip's flight: never pick one yourself)")
    for d in (pickup_date, dropoff_date):
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", d):
            raise ValueError("dates must be YYYY-MM-DD")
    if pickup_date + pickup_time >= dropoff_date + dropoff_time:
        raise ValueError("the drop-off must be after the pick-up")
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("offset must be 0 or more and limit 1-100")
    if automatic and manual:
        raise ValueError("choose automatic or manual, not both")
    default_age = driver_years is None or 30 <= driver_years <= 69      # the form's age box starts at 30-69; another age is picked in the box and the page's own text is then shown, not judged
    filters = [LABELS[k] for k, on in (("automatic", automatic), ("manual", manual), ("zero_excess", zero_excess), ("inside_airport", inside_airport)) if on]
    script = with_emit((HERE / "ofran.js").read_text(encoding="utf-8")).replace("__SKIP__", str(offset)).replace("__LIMIT__", str(limit)).replace("__FILTERS__", json.dumps(filters, ensure_ascii=False))
    expect = {"pickup": pickup, "pickup_date": pickup_date, "pickup_time": pickup_time, "dropoff_date": dropoff_date, "dropoff_time": dropoff_time, "filters": filters, "age": "30-69" if default_age else None, "driver_years": driver_years}
    age_step = "the driver age box stays 30-69." if default_age else f"set the driver age box to the operator's age ({driver_years}): pick {driver_years} or the band that holds it, and leave it there."
    steps = [f"Open {HOME} in the operator's logged-in Chrome (the top bar must show the agent's name; if it shows a login, stop and tell the operator). Keep 'return the car to the same station' and 'not leaving the country'; {age_step}",
             f"Pick-up and return place: click the field, type a distinctive part of '{pickup}' (for example the city) and click the suggestion with the airport or station name, then read the field back.",
             f"Dates: click 'when are you picking up' and pick {pickup_date} in the calendar, then click 'when are you returning' and pick {dropoff_date}. Times: pick-up {pickup_time}, return {dropoff_time} (the time boxes; the default is 10:00).",
             "Press the search button ('חפשו לי רכב'). Wait about 15 seconds until the cars show (the page says how many results). The results address does not carry the dates: the script reads what the page itself says it searched.",
             "Run `script` with the javascript tool on the results page. ok=false: do what `error` says. Never read the cards by eye. The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row with the returned `wishes`, `filters_used` and `pickup_time`."]
    return {"script": script, "url": HOME, "expect": expect, "steps": steps}


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ddmmyy(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[2:4]}"


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Ofran result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Ofran script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    notes: list[str] = []
    if data.get("settled") is False:
        problems.append("Ofran was still adding cars when the page was read: wait and run the script once more")
    if data.get("price_order") == "not ascending":
        problems.append("the Ofran prices are not in ascending order: the page may have changed while reading")
    form = data.get("form") or {}
    if exp:
        if exp.get("pickup") and form.get("pickup_place") and not place_matches(exp["pickup"], form["pickup_place"]):
            problems.append(f"the page searched '{form.get('pickup_place')}', not '{exp['pickup']}': make the search again with the right place")
        for which, d, t in (("pickup_when", exp.get("pickup_date"), exp.get("pickup_time")), ("dropoff_when", exp.get("dropoff_date"), exp.get("dropoff_time"))):
            want = f"{_ddmmyy(d)} | {t}" if d and t else None
            if want and form.get(which) and form[which] != want:
                problems.append(f"the page searched '{form[which]}', not '{want}': make the search again with the right dates and times")
        if exp.get("age") and form.get("age") and form["age"] != exp["age"]:
            problems.append(f"the page says the driver age is '{form['age']}', not '{exp['age']}': make the search again")
        if exp.get("driver_years") and form.get("age") == "30-69" and exp["driver_years"] < 30:
            problems.append(f"the page still says the driver age is 30-69, the operator's driver is {exp['driver_years']}: set the age box to it and make the search again")
        allowed = set(exp.get("filters") or [])
        extra = [f for f in data.get("page_ticked") or [] if f not in allowed]
        missing = [f for f in allowed if f not in (data.get("page_ticked") or [])]
        if extra or missing:
            problems.append(f"Ofran's filters are not as asked (unexpected: {', '.join(extra) or 'none'}; missing: {', '.join(missing) or 'none'}): clear them, search again and run the script once more")
    if data.get("logged_in") is False:
        problems.append("Ofran shows no logged-in agent (no 'התנתקות' in the top bar): the prices would be the public ones, not the agency's: ask the operator to log in")
    agent = bool(data.get("logged_in"))
    offers: list[Offer] = []
    for r in data.get("rows", []):
        price = _num(r.get("price"))
        excess = r.get("excess") or ""
        zero = "כולל ביטול השתתפות עצמית" in excess
        seats = _num(r.get("seats"))
        fits: bool | None = None
        if wishes:
            ok = True
            if wishes.get("automatic"):
                ok &= r.get("gearbox") in ("אוטומטית", "אוטומטי")
            if wishes.get("manual"):
                ok &= r.get("gearbox") == "ידני"
            if wishes.get("zero_excess"):
                ok &= zero
            if wishes.get("min_seats"):
                ok &= seats is not None and seats >= int(wishes["min_seats"])
            if wishes.get("max_total") is not None:
                ok &= price is not None and price <= float(wishes["max_total"])
            fits = ok
        gear = {"ידני": "Manual", "אוטומטית": "Automatic", "אוטומטי": "Automatic"}.get(r.get("gearbox") or "", r.get("gearbox"))
        seats_bags = " / ".join(x for x in (f"{r['seats']} seats" if r.get("seats") else None, f"{r['bags']} bags" if r.get("bags") else None, f"{r['doors']} doors" if r.get("doors") else None) if x) or None
        basis = f"whole rental, {r.get('days') or '?'} days, price after the agent discount (list price {r['price_before']:g})" if agent and r.get("price_before") else f"whole rental, {r.get('days') or '?'} days"
        offers.append(Offer(
            group=group, source=SOURCE, name=f"{r.get('car') or 'not shown'} ({r.get('acriss') or '?'}, {r.get('size') or 'class not shown'})", price_total=price, currency="EUR", price_basis=basis, fits=fits,
            supplier=r.get("supplier"),
            details={"company": (r.get("supplier") or "not shown") + (f" (score {r['supplier_score']})" if r.get("supplier_score") else ""), "gearbox": gear, "seats_bags": seats_bags,
                     "excess": "excess cancelled (included)" if zero else (excess or "not shown"), "fuel": "not shown on the list", "mileage": "not shown on the list", "deposit": "not shown on the list",
                     "cancellation": "not shown on the list", "pickup_place": station_text(r.get("station")), "score": r.get("supplier_score")}))
    n = len(data.get("rows", []))
    if wishes.get("min_large_bags"):
        notes.append(f"The operator needs room for {wishes['min_large_bags']} large bags: Ofran's list shows only 'x/y' bags without saying which are large, so no Ofran car was checked for it: open the car's page before quoting an Ofran car.")
    if exp.get("driver_years") and form.get("age"):
        notes.append(f"Ofran's page says the driver age is '{form['age']}' (the operator's driver is {exp['driver_years']}).")
    notes.append("Ofran's list does not show fuel policy, mileage, deposit or cancellation: they are on the car's own page after choosing it (do not press the choose button).")
    if data.get("offset"):
        notes.append(f"These are cars {int(data['offset']) + 1} to {int(data['offset']) + n} of the price-sorted list (cheaper ones were shown before): the Cheapest here is not the cheapest overall.")
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ofran_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ofran_recipe_tool(pickup: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, gearbox: str | None = None, min_seats: int | None = None,
                                zero_excess: bool | None = None, max_total: float | None = None, inside_airport: bool = False, operator_answered: bool = False,
                                offset: int = 0, limit: int = BATCH, driver_years: int | None = None, min_large_bags: int | None = None) -> dict[str, Any]:
        """FOR CAR RENTAL ON OFRAN (the agency's logged-in Ofran, read in the operator's own Chrome with Claude in Chrome; the agency's own price). ASK FIRST like ratehawk_cars_recipe: without `gearbox`
        ('automatic' / 'manual'), `min_seats`, `zero_excess` (true/false) and `max_total` (EUR, whole rental) it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with
        the answers (`operator_answered`=true for "no preference", only after the operator replied). Times are required (from the trip's flight or the operator; never your own choice) and the same on
        RateHawk. Then it returns the steps to make the search once with Ofran's form (its results address does not carry the dates) and a read-only SCRIPT for the results page; it ticks the filters,
        reads the next `limit` (30) cars from `offset` and returns what the page searched. The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row, `filters_used` and `pickup_time`. `min_large_bags` = the number of LARGE suitcases the operator said (pass it as for RateHawk; Ofran's list cannot confirm it, the answer says so). `driver_years` = the driver's age as the operator said it (under 30: the steps tell you to set Ofran's age box to it; the answer then shows the page's own age text). The price is the one AFTER the agent discount (the top bar must show the agent's name). A human
        check or a block is never worked around: stop and tell the operator. `pickup` is the place as typed in the form ('Faro Airport'); dates YYYY-MM-DD."""
        asked = cars_ask_gate(gearbox, min_seats, zero_excess, max_total, operator_answered)
        if asked:
            return asked
        if gearbox not in (None, "automatic", "manual"):
            raise ValueError("gearbox must be 'automatic', 'manual' or left out")
        out = ofran_recipe(pickup, pickup_date, pickup_time, dropoff_date, dropoff_time, gearbox == "automatic", gearbox == "manual", bool(zero_excess), inside_airport, offset, limit, driver_years)
        out["wishes"] = {"expect": out["expect"], "automatic": gearbox == "automatic", "manual": gearbox == "manual", "zero_excess": bool(zero_excess), "min_seats": min_seats, "max_total": max_total, "min_large_bags": min_large_bags}
        out["filters_used"] = ([f"{gearbox.capitalize()} gearbox (operator)"] if gearbox else []) + (["Excess cancelled / zero excess (operator)"] if zero_excess else []) + \
            ([f"at least {min_seats} seats (operator)"] if min_seats else []) + ([f"budget up to {max_total:g} EUR for the whole rental (operator)"] if max_total is not None else []) + \
            (["Inside the airport (operator)"] if inside_airport else []) + ([f"room for {min_large_bags} large bags (operator): NOT checkable on Ofran, its list shows only 'x/y' bags without saying which are large"] if min_large_bags else []) + [f"driver age {driver_years} (operator; Ofran's age box set to it)" if driver_years and not 30 <= driver_years <= 69 else "driver age 30-69 (default: the agency's)"]
        out["pickup_time"] = pickup_time
        out["login_check"] = {"run_first": "Open https://www.ofran.co.il/ and run (() => /\u05d4\u05ea\u05e0\u05ea\u05e7\u05d5\u05ea/.test(document.body.innerText))() with the javascript tool BEFORE you fill the form.",
                              "if_false": "The agency is not logged in (Ofran shows only the public prices). Stop: tell the operator to log in to Ofran in this Chrome (you never type a password), put Ofran in not_checked with the reason 'login: the agency is not logged in to Ofran', and go on with the other sources."}
        out["more"] = f"For the next {limit} cars call this tool again with the same values and offset={offset + limit}; say so to the operator at the end of the answer."
        return out
