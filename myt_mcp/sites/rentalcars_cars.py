"""Rentalcars.com (by Booking.com), a car rental broker: a URL (every search value is in the address) and a tested read-only script for the operator's own Chrome (a site module).

Site rules (found on the real pages, 27 Oct 2026):
* Results address: /search-results?intent=direct&location=&dropLocation=&locationName=<name>&locationIata=<IATA>&dropLocationName=&dropLocationIata=&coordinates=<lat,lon>&dropCoordinates=
  &driversAge=30&puDay&puMonth&puYear&puHour&puMinute&doDay&doMonth&doYear&doHour&doMinute&ftsType=A&dropFtsType=A. A place is learned once from the address after a search. `preferredCurrency` in the address does NOT
  change the currency (it follows the visitor: INR in India); the page shows its currency, the SERVER converts it to euro (myt_mcp/fx.py) and says so in every row.
* The page loads its cars with one request to its own server, GET /api/search-results?searchCriteria=...&filterCriteria={}: JSON with `matches` (up to 500 of the cars the page counts), `depots`, `suppliers`
  and `aggregates`. A match has the vehicle (make and model, ACRISS class, seats, doors, big and small suitcases, gearbox, fuel, mileage, pay when, free cancellation), its prices (`driveAwayPrice` is the total
  the card shows), `fees` (DAMAGE_EXCESS, THEFT_EXCESS, DEPOSIT and others) and the pick-up depot, whose supplier and rating are in `depots` and `suppliers`. The script reads that request again from the page.
* "Pay now" with free cancellation on most; the fuel policy in the filters of the search was like for like for every car.
* It is a broker's public price (the cars of Alamo, Sixt, Europcar and local companies): rows are comparison only. The site has no CSP limit (default-src *): the answer goes to the server directly.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.fx import basis_note, eur_factors, to_eur
from myt_mcp.sites import SiteRows, with_emit
from myt_mcp.sites.ratehawk_cars import cars_ask_gate

NAME = "rentalcars_cars"
SOURCE = "Rentalcars.com (public website price)"
GROUP = "Cars"
HERE = Path(__file__).parent
BASE = "https://www.rentalcars.com/search-results"
HOME = "https://www.rentalcars.com/"
DEFAULT_AGE = 30
PLACE_TYPES = {"IN_TERMINAL": "in the terminal", "SHUTTLE_BUS": "shuttle bus from the airport"}


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", str(text).lower()).encode("ascii", "ignore").decode()).strip()


def places() -> dict[str, dict[str, str]]:
    data = json.loads((HERE / "rentalcars_cars.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def find_place(text: str) -> dict[str, str] | None:
    """The learned place for a name as typed ('Lisbon Airport'), the site's own name ('Humberto Delgado Airport') or its airport code ('LIS')."""
    key = _plain(text)
    return next((v for k, v in places().items() if key and key in (_plain(k), _plain(v["name"]), _plain(v["iata"]))), None)


def results_url(pickup: dict[str, str], dropoff: dict[str, str], pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, age: int) -> str:
    p, d = pickup_date.split("-"), dropoff_date.split("-")
    return (f"{BASE}?intent=direct&location=&dropLocation=&locationName={quote_plus(pickup['name'])}&locationIata={pickup['iata']}&dropLocationName={quote_plus(dropoff['name'])}&dropLocationIata={dropoff['iata']}"
            f"&coordinates={quote_plus(pickup['coordinates'])}&dropCoordinates={quote_plus(dropoff['coordinates'])}&driversAge={age}&puDay={int(p[2])}&puMonth={int(p[1])}&puYear={p[0]}&puMinute={int(pickup_time[3:])}"
            f"&puHour={int(pickup_time[:2])}&doDay={int(d[2])}&doMonth={int(d[1])}&doYear={d[0]}&doMinute={int(dropoff_time[3:])}&doHour={int(dropoff_time[:2])}&ftsType={pickup.get('fts_type', 'A')}&dropFtsType={dropoff.get('fts_type', 'A')}")


def rentalcars_cars_recipe(pickup: dict[str, str], dropoff: dict[str, str], pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, age: int) -> dict[str, Any]:
    for t in (pickup_time, dropoff_time):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise ValueError("times must be HH:MM, e.g. 10:00 (ask the operator or take it from the trip's flight: never pick one yourself)")
    for d in (pickup_date, dropoff_date):
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", d):
            raise ValueError("dates must be YYYY-MM-DD")
    if pickup_date + pickup_time >= dropoff_date + dropoff_time:
        raise ValueError("the drop-off must be after the pick-up")
    if not 30 <= age <= 65:
        raise ValueError("the driver's age must be 30-65 (the site's standard band; other ages bring young- or senior-driver fees that are not tested)")
    expect = {"iata": pickup["iata"], "drop_iata": dropoff["iata"], "pickup_when": f"{pickup_date} {pickup_time}", "dropoff_when": f"{dropoff_date} {dropoff_time}", "age": age, "pickup": pickup["name"]}
    script = with_emit((HERE / "rentalcars_cars.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps({k: v for k, v in expect.items() if k != "pickup"}))
    return {"url": results_url(pickup, dropoff, pickup_date, pickup_time, dropoff_date, dropoff_time, age), "script": script, "expect": expect}


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _days(pickup: str | None, dropoff: str | None) -> int | None:
    try:
        a, b = (datetime.strptime(x, "%Y-%m-%d %H:%M") for x in (pickup or "", dropoff or ""))
    except ValueError:
        return None
    return max(1, math.ceil((b - a).total_seconds() / 86400))


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Rentalcars result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Rentalcars script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    form = data.get("form") or {}
    problems: list[str] = []
    for key, label in (("iata", "pick-up place"), ("drop_iata", "drop-off place"), ("pickup_when", "pick-up"), ("dropoff_when", "return"), ("age", "driver age")):
        if exp.get(key) and form.get(key) != exp[key]:
            problems.append(f"the page searched {label} '{form.get(key)}', not '{exp[key]}': search again with the url the recipe gave")
    rows = data.get("rows") or []
    if not rows:
        problems.append("the Rentalcars answer held no cars: it could not be read (never say sold out); run the script again")
    fx = wishes.get("fx") or {}
    days = _days(form.get("pickup_when"), form.get("dropoff_when"))
    policies = data.get("fuel_policies") or []
    fuel_policy = "like for like (return with the fuel level you started with)" if policies == ["RETURN_SAME"] else ("not shown" if not policies else ", ".join(policies))
    offers: list[Offer] = []
    seen: set[str] = set()
    currencies: set[str] = set()
    converted = False
    for r in rows:
        total, cur = _num(r.get("total")), str(r.get("cur") or "").upper()
        name = f"{r.get('car') or 'not shown'} ({r.get('klass') or 'class not shown'}) - {r.get('supplier') or 'supplier not shown'}"
        key = f"{r.get('id')}|{name}|{total}"
        if total is None or not cur or key in seen:
            continue
        seen.add(key)
        price, shown, factor = to_eur(total, cur, fx)
        currencies.add(cur)
        converted = converted or bool(factor)
        gear = {"AUTOMATIC": "Automatic", "MANUAL": "Manual"}.get(str(r.get("gearbox") or "").upper(), r.get("gearbox"))
        seats, big = _num(r.get("seats")), _num(r.get("big"))
        damage, theft, deposit = _num(r.get("damage_excess")), _num(r.get("theft_excess")), _num(r.get("deposit"))

        def money(x: float | None) -> str:
            return "not shown" if x is None else (f"{x:,.2f} {cur}" + (f" (about {x * factor:,.0f} EUR)" if factor else ""))
        fits: bool | None = True
        if wishes.get("automatic"):
            fits = bool(fits and gear == "Automatic")
        if wishes.get("manual"):
            fits = bool(fits and gear == "Manual")
        if wishes.get("zero_excess"):
            fits = bool(fits and damage == 0)                  # only a damage excess the page lists as 0 meets it; a missing fee is never assumed to be zero
        if wishes.get("min_seats"):
            fits = bool(fits and seats is not None and seats >= int(wishes["min_seats"]))
        if wishes.get("min_large_bags"):
            fits = bool(fits and big is not None and big >= int(wishes["min_large_bags"]))
        if wishes.get("max_total") is not None:
            fits = bool(fits and shown == "EUR" and price <= float(wishes["max_total"]))
        free = r.get("free_cancel")
        seats_bags = " / ".join(x for x in (f"{r['seats']} seats" if r.get("seats") else None, f"{r.get('big', '?')} large + {r.get('small', '?')} small bags" if r.get("big") is not None else None,
                                            f"{r['doors']} doors" if r.get("doors") else None) if x) or None
        offers.append(Offer(
            group=group, source=SOURCE, name=name, price_total=price, currency=shown, quotable=False, supplier=r.get("supplier"), fits=fits, flexible=True if free else None,
            price_basis=(f"whole rental{f', {days} days' if days else ''}, total of the page ({str(r.get('pay') or 'pay when').replace('_', ' ').lower()})" + (f", {basis_note(cur, total, factor, fx)}" if factor else "")),
            details={"company": (r.get("supplier") or "not shown") + (f" (rating {r['rating']}, {r['ratings']:,} reviews)" if r.get("rating") and r.get("ratings") else ""), "gearbox": gear, "seats_bags": seats_bags,
                     "excess": ("zero excess (damage excess 0)" if damage == 0 else f"damage excess {money(damage)}, theft excess {money(theft)}"), "fuel": f"{r.get('fuel') or 'not shown'}; policy {fuel_policy}",
                     "mileage": "Unlimited mileage" if str(r.get("mileage")).upper() == "UNLIMITED" else (r.get("mileage") or "not shown"), "deposit": money(deposit),
                     "cancellation": "free cancellation (the page's flag)" if free else "not shown as free: open the deal", "card_needed": r.get("card_needed"),
                     "pickup_place": f"{r.get('place') or 'not shown'} ({PLACE_TYPES.get(str(r.get('place_type')), r.get('place_type') or 'type not shown')}): {r.get('address') or 'address not shown'}",
                     "other_fees": r.get("other_fees"), "original_price": f"{cur} {total:,.2f}" if factor else None}))
    notes = ["Rentalcars rows are the broker's public website price (no negotiated or agency rate), so they are comparison only; the supplier of each car is named in its row."]
    foreign = sorted(c for c in currencies if c != "EUR")
    if foreign and converted:
        notes.append(f"Rentalcars showed its prices in {', '.join(foreign)}: the server converted them to euro at the {fx.get('source')} of {fx.get('date')} and each row's price basis shows the original price and the rate. Do not convert them yourself.")
        if (fx.get("age_days") or 0) > 3:
            notes.append(f"The exchange rate is {fx['age_days']} days old (the bank publishes on business days): say so.")
    unconverted = sorted(c for c in foreign if not (fx.get("factors") or {}).get(c))
    if unconverted:
        notes.append(f"Rentalcars showed its prices in {', '.join(unconverted)} and no euro rate was available: those rows are shown in their own currency and never compared with euro prices. Do not convert them yourself.")
    shown_total = str(data.get("cars_shown_by_page") or "").replace(",", "")
    if shown_total.isdigit() and int(shown_total) > len(rows):
        notes.append(f"The page counts {shown_total} cars; its answer holds the first {len(rows)} (recommended order): a cheaper car may be among the rest.")
    if wishes.get("zero_excess"):
        notes.append("Zero excess was asked: only the cars whose damage excess the page lists as 0 meet it.")
    n = len(rows)
    return SiteRows(offers=offers, read=n, total=int(shown_total) if shown_total.isdigit() else n, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="rentalcars_cars_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def rentalcars_cars_recipe_tool(pickup: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, gearbox: str | None = None, min_seats: int | None = None,
                                          zero_excess: bool | None = None, max_total: float | None = None, operator_answered: bool = False, driver_years: int | None = None,
                                          dropoff: str | None = None, pickup_place: dict[str, str] | None = None, dropoff_place: dict[str, str] | None = None,
                                          min_large_bags: int | None = None) -> dict[str, Any]:
        """FOR CAR RENTAL ON RENTALCARS.COM (a broker of Alamo, Sixt, Europcar and local companies, read in the operator's own Chrome with Claude in Chrome; public website prices, comparison only), next to RateHawk,
        Ofran and Europcar. ASK FIRST like ratehawk_cars_recipe: without `gearbox` ('automatic' / 'manual'), `min_seats`, `zero_excess` (true/false) and `max_total` (EUR) it opens nothing and returns
        `ask_operator`: ask them in ONE message, wait, call again with the answers (`operator_answered`=true for "no preference", only after the operator replied). Times are required (from the trip's flight or
        the operator; never your own choice) and the same on every source. `pickup` is the place as typed ('Lisbon Airport'); a place not learned yet returns `needs_place` with steps to learn it once (then pass it
        as `pickup_place`). The driver is 30-65. The page's currency follows the visitor: the SERVER converts it to euro and says so in each row; never convert a price yourself. Then it returns the results url and a
        read-only SCRIPT: open the url, run the script with the javascript tool; it reads the page's own search answer (every car with supplier, depot, fees, excess), sends it to the server by itself and
        returns a short receipt (the `ingest` id): call compose_answer with `runs`=[that id] and this tool's `wishes` and `filters_used`. Never press View deal or type a row. A check page or block is never worked
        around: stop and tell the operator."""
        asked = cars_ask_gate(gearbox, min_seats, zero_excess, max_total, operator_answered)
        if asked:
            return asked
        if gearbox not in (None, "automatic", "manual"):
            raise ToolError("gearbox must be 'automatic', 'manual' or left out")
        pick = pickup_place or find_place(pickup)
        drop = dropoff_place or (pick if not dropoff else find_place(dropoff))
        needs = ([pickup] if not pick else []) + ([dropoff] if dropoff and not drop else [])
        if needs:
            return {"ok": False, "searched": False, "needs_place": needs, "known_places": sorted(places()), "steps": [
                f"Open {HOME} in the operator's Chrome, type the place, pick the suggestion with the airport or station name, enter the dates and Search (never press View deal).",
                "On the results page run with the javascript tool: (() => { const q = new URLSearchParams(location.search); return JSON.stringify({name: q.get('locationName'), iata: q.get('locationIata'), coordinates: q.get('coordinates'), fts_type: q.get('ftsType')}); })()  "
                "and call this tool again with that object as pickup_place (dropoff_place for another return place)."]}
        age = driver_years or DEFAULT_AGE
        fx = await eur_factors()
        try:
            out = rentalcars_cars_recipe(pick, drop, pickup_date, pickup_time, dropoff_date, dropoff_time, age)
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        out["wishes"] = {"expect": out["expect"], "automatic": gearbox == "automatic", "manual": gearbox == "manual", "zero_excess": bool(zero_excess), "min_seats": min_seats, "max_total": max_total,
                         "min_large_bags": min_large_bags, "fx": fx}
        out["filters_used"] = (([f"{gearbox.capitalize()} gearbox (operator)"] if gearbox else []) + (["Zero excess (operator): only a damage excess listed as 0"] if zero_excess else [])
                               + ([f"at least {min_seats} seats (operator)"] if min_seats else []) + ([f"budget up to {max_total:g} EUR for the whole rental (operator)"] if max_total is not None else [])
                               + ([f"room for {min_large_bags} large bags (operator)"] if min_large_bags else [])
                               + [f"driver age {age} " + ("(operator)" if driver_years else f"(default {DEFAULT_AGE}: the site's 30-65 band)")]
                               + ([f"prices converted to EUR by the server at the {fx['source']} of {fx['date']}"] if fx else ["no euro exchange rate was available: Rentalcars rows in another currency stay unconverted (the server never guesses a rate)"]))
        out["pickup_time"] = pickup_time
        return out
