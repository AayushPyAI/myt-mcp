"""Europcar cars (europcar.com, English site): a URL (every search value is in the address) and a tested read-only script for the operator's own Chrome (a site module).

Site rules (found on the real pages, 27 Oct 2026):
* Results address: /en-us/reservation/vehicles?vehicleType=CR&pickupLocation=<station>&dropoffLocation=<station>&pickupYear&pickupMonth&pickupDay&dropoffYear&dropoffMonth&dropoffDay&pickupHour
  &pickupMinute&dropoffHour&dropoffMinute&driverAge=<years>&countryOfResidence=<2 letters>. Stations are codes (LIST01 = Lisbon Airport), learned once from the address after a search.
* THE CURRENCY FOLLOWS THE RESIDENCY, not the site's country: the same car in Lisbon was INR 8,212.80 for India, USD 86.50 for Israel (also on europcar.pt). Israeli residents are priced in dollars:
  the SERVER converts them to euro (myt_mcp/fx.py: the Bank of Israel representative rates crossed, carried in `wishes["fx"]`; every row says the original price, the rate and its date).
  With no rate (feed down, currency not in the feed such as INR) the rows keep their currency and `compose` shows them without comparing. "$" is read as USD only because the url is the en-us site.
* The list is infinite (10 cars, 10 more after each scroll). A card has the car, class ("OR SIMILAR Compact"), icons (seats, doors, bags, gearbox A/M, A/C, minimum age), mileage, "Basic protection included",
  "PAY AT DESK", the price per day and the TOTAL. Opening "Vehicle details" gives the protection's excess; fuel policy, deposit and cancellation are not on the list; zero excess is an upgrade chosen
  after pressing Select (never pressed).
* The prices are the public ones (the form has "I have a negotiated rate"): rows are comparison only.
* Home page and results page have no Content-Security-Policy and let the page post to the server (checked after the scripts ran), so the answer goes to the server directly.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.fx import basis_note, eur_factors, to_eur
from myt_mcp.sites import SiteRows, place_matches, with_emit
from myt_mcp.sites.ratehawk_cars import cars_ask_gate

NAME = "europcar_cars"
SOURCE = "Europcar (public website price)"
GROUP = "Cars"
HERE = Path(__file__).parent
BASE = "https://www.europcar.com/en-us/reservation/vehicles"
HOME = "https://www.europcar.com/en-us"
SYMBOLS = {"$": "USD", "€": "EUR", "₪": "ILS", "£": "GBP", "₹": "INR"}
DEFAULT_AGE = 30


def stations() -> dict[str, str]:
    data = json.loads((HERE / "europcar_cars.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def results_url(pickup_code: str, dropoff_code: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, age: int, residency: str) -> str:
    p, d = pickup_date.split("-"), dropoff_date.split("-")
    return (f"{BASE}?vehicleType=CR&pickupLocation={pickup_code}&dropoffLocation={dropoff_code}&pickupYear={p[0]}&pickupMonth={p[1]}&pickupDay={p[2]}"
            f"&dropoffYear={d[0]}&dropoffMonth={d[1]}&dropoffDay={d[2]}&pickupHour={pickup_time[:2]}&pickupMinute={pickup_time[3:]}&dropoffHour={dropoff_time[:2]}&dropoffMinute={dropoff_time[3:]}"
            f"&driverAge={age}&countryOfResidence={residency}")


def europcar_cars_recipe(pickup: str, pickup_code: str, dropoff_code: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, age: int, residency: str) -> dict[str, Any]:
    for t in (pickup_time, dropoff_time):
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise ValueError("times must be HH:MM, e.g. 10:00 (ask the operator or take it from the trip's flight: never pick one yourself)")
    for d in (pickup_date, dropoff_date):
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", d):
            raise ValueError("dates must be YYYY-MM-DD")
    if pickup_date + pickup_time >= dropoff_date + dropoff_time:
        raise ValueError("the drop-off must be after the pick-up")
    if not 18 <= age <= 99:
        raise ValueError("the driver's age must be 18-99")
    if not re.fullmatch(r"[A-Z]{2}", residency):
        raise ValueError("residency is the two-letter country code, e.g. IL")
    expect = {"pickup": pickup, "pickup_when": f"{pickup_date} {pickup_time}", "dropoff_when": f"{dropoff_date} {dropoff_time}", "age": age, "residency": residency}
    script = with_emit((HERE / "europcar_cars.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps(expect))
    return {"url": results_url(pickup_code, dropoff_code, pickup_date, pickup_time, dropoff_date, dropoff_time, age, residency), "script": script, "expect": expect}


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Europcar result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Europcar script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    form = data.get("form") or {}
    problems: list[str] = []
    notes: list[str] = []
    if exp.get("pickup") and form.get("pickup_place") and not place_matches(exp["pickup"], form["pickup_place"]):
        problems.append(f"the page searched '{form.get('pickup_place')}', not '{exp['pickup']}': search again with the url the recipe gave")
    for key, label in (("pickup_when", "pick-up"), ("dropoff_when", "return")):
        if exp.get(key) and form.get(key) != exp[key]:
            problems.append(f"the page searched {label} '{form.get(key)}', not '{exp[key]}': search again with the url the recipe gave")
    if exp.get("age") and data.get("age") != exp["age"]:
        problems.append(f"the page used driver age {data.get('age')}, not {exp['age']}: search again with the url the recipe gave")
    if exp.get("residency") and data.get("residency") != exp["residency"]:
        problems.append(f"the page priced residency {data.get('residency')}, not {exp['residency']}: search again with the url the recipe gave")
    rows = data.get("rows") or []
    if not rows:
        problems.append("the Europcar page showed no cars: it could not be read (never say sold out); run the script again")
    offers: list[Offer] = []
    seen: set[str] = set()
    currencies: set[str] = set()
    converted = False
    fx = wishes.get("fx") or {}
    for r in rows:
        total = _num(r.get("total"))
        name = f"{r.get('car') or 'not shown'} ({r.get('klass') or 'class not shown'})"
        key = f"{name}|{total}"
        if total is None or key in seen:
            continue
        seen.add(key)
        cur = SYMBOLS.get(r.get("symbol") or "", None)
        if cur is None:
            problems.append(f"{name}: price symbol {r.get('symbol')!r} is not a currency the converter knows: the row was not read")
            continue
        price, shown, factor = to_eur(total, cur, fx)       # the server converts, with the rate it carried in; never the assistant
        currencies.add(cur)
        converted = converted or bool(factor)
        seats, per_day = _num(r.get("seats")), _num(r.get("per_day"))
        gear = {"A": "Automatic", "M": "Manual"}.get(str(r.get("gearbox") or "").upper(), r.get("gearbox"))
        excess_amount = _num(r.get("excess"))
        zero = excess_amount == 0
        fits: bool | None = True
        if wishes.get("automatic"):
            fits = bool(fits and gear == "Automatic")
        if wishes.get("manual"):
            fits = bool(fits and gear == "Manual")
        if wishes.get("zero_excess"):
            fits = bool(fits and zero)                       # the list shows only the basic protection's excess: zero excess is never assumed
        if wishes.get("min_seats"):
            fits = bool(fits and seats is not None and seats >= int(wishes["min_seats"]))
        if wishes.get("max_total") is not None:
            fits = bool(fits and shown == "EUR" and price <= float(wishes["max_total"]))      # the budget is in euro: a price with no euro rate cannot be judged
        days = round(total / per_day) if per_day else None
        seats_bags = " / ".join(x for x in (f"{r['seats']} seats" if r.get("seats") else None, f"{r['bags']} bags" if r.get("bags") else None, f"{r['doors']} doors" if r.get("doors") else None) if x) or None
        excess = (f"basic protection with an excess of {r['excess_text'].split(':', 1)[1].strip()} (collision damage and theft); zero excess is an upgrade after selecting the car, not priced here" if r.get("excess_text")
                  else "not shown (the details card could not be read)")
        offers.append(Offer(
            group=group, source=SOURCE, name=name, price_total=price, currency=shown,
            price_basis=(f"whole rental{f', {days} days' if days else ''}, {str(r.get('pay') or 'pay at desk').lower()}, basic protection included"
                         + (f", {basis_note(cur, total, factor, fx)}" if factor else "")),
            fits=fits, quotable=False, supplier="Europcar",
            details={"company": "Europcar", "gearbox": gear, "seats_bags": seats_bags, "excess": excess, "fuel": "not shown on the list", "mileage": r.get("mileage") or "not shown", "deposit": "not shown on the list",
                     "cancellation": "not shown on the list", "min_driver_age": r.get("min_age"), "air_conditioning": bool(r.get("ac")),
                     "original_price": f"{cur} {total:,.2f}" if factor else None}))
    notes.append("Europcar rows are the public website price (this search has no negotiated or agency rate), so they are comparison only.")
    foreign = sorted(c for c in currencies if c != "EUR")
    if foreign and converted:
        notes.append(f"Europcar priced this search in {', '.join(foreign)} (its price currency follows the driver's country of residence {data.get('residency') or '?'}): the server converted the prices to euro at the "
                     f"{fx.get('source')} of {fx.get('date')} and each row's price basis shows the original price and the rate. Do not convert them yourself.")
        if (fx.get("age_days") or 0) > 3:
            notes.append(f"The exchange rate is {fx['age_days']} days old (the bank publishes on business days): say so.")
    unconverted = sorted(c for c in foreign if not (fx.get("factors") or {}).get(c))
    if unconverted:
        notes.append(f"Europcar priced this search in {', '.join(unconverted)} (its price currency follows the driver's country of residence {data.get('residency') or '?'}) and no euro rate was available: "
                     "those rows are shown in their own currency and never compared with euro prices. Do not convert them yourself.")
    if wishes.get("min_large_bags"):
        notes.append(f"The operator needs room for {wishes['min_large_bags']} large bags: Europcar's list shows only a number of luggages without saying which are large, so no Europcar car was checked for it.")
    if wishes.get("zero_excess"):
        notes.append("Zero excess was asked: Europcar's list shows only the basic protection (with an excess); the zero-excess upgrade is priced after selecting a car, which is not done here, so no Europcar row meets it.")
    notes.append("Europcar's list does not show fuel policy, deposit or cancellation (the protection and extras come after the Select step, which is never pressed).")
    n = len(rows)
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="europcar_cars_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def europcar_cars_recipe_tool(pickup: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, gearbox: str | None = None, min_seats: int | None = None,
                                        zero_excess: bool | None = None, max_total: float | None = None, operator_answered: bool = False, driver_years: int | None = None,
                                        residency: str = "IL", station_code: str | None = None, dropoff: str | None = None, dropoff_station_code: str | None = None,
                                        min_large_bags: int | None = None) -> dict[str, Any]:
        """FOR CAR RENTAL ON EUROPCAR (europcar.com, read in the operator's own Chrome with Claude in Chrome; public website prices, comparison only), next to RateHawk and Ofran. ASK FIRST like ratehawk_cars_recipe:
        without `gearbox` ('automatic' / 'manual'), `min_seats`, `zero_excess` (true/false) and `max_total` (EUR) it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the
        answers (`operator_answered`=true for "no preference", only after the operator replied). Times are required (from the trip's flight or the operator; never your own choice) and the same on every source.
        `pickup` is the place as typed on europcar.com ('Lisbon Airport'); a place without a known station code returns `needs_station_code` with steps to learn it once. `residency` is the driver's country (IL):
        Europcar's price CURRENCY follows it (Israel is priced in dollars): the rows keep their currency and are never converted. Then it returns the results url (every value in it) and a read-only SCRIPT: open the
        url, run the script with the javascript tool; it scrolls the whole list, reads every car and sends its answer to the server by itself, then returns a short receipt (the `ingest` id): call compose_answer
        with `runs`=[that id] and this tool's `wishes` and `filters_used`. Never press Select or type a row. A check page or block is never worked around: stop and tell the operator."""
        asked = cars_ask_gate(gearbox, min_seats, zero_excess, max_total, operator_answered)
        if asked:
            return asked
        if gearbox not in (None, "automatic", "manual"):
            raise ToolError("gearbox must be 'automatic', 'manual' or left out")
        table = stations()
        pickup_code = station_code or table.get(re.sub(r"\s+", " ", pickup.strip().lower()))
        drop_name = dropoff or pickup
        drop_code = dropoff_station_code or (pickup_code if not dropoff else table.get(re.sub(r"\s+", " ", dropoff.strip().lower())))
        if not pickup_code or not drop_code:
            return {"ok": False, "searched": False, "needs_station_code": ([pickup] if not pickup_code else []) + ([drop_name] if dropoff and not drop_code else []), "known_places": sorted(table), "steps": [
                f"Open {HOME} in the operator's Chrome, type the place, pick the suggestion with the airport or station name, enter the dates and Search (never press Select on a car).",
                "On the results page run with the javascript tool: (() => new URLSearchParams(location.search).get('pickupLocation'))()  (and 'dropoffLocation' for another return place) and call this tool again with that value as station_code (dropoff_station_code)."]}
        age = driver_years or DEFAULT_AGE
        fx = await eur_factors()
        try:
            out = europcar_cars_recipe(pickup, pickup_code, drop_code, pickup_date, pickup_time, dropoff_date, dropoff_time, age, residency.upper())
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        out["wishes"] = {"expect": out["expect"], "automatic": gearbox == "automatic", "manual": gearbox == "manual", "zero_excess": bool(zero_excess), "min_seats": min_seats, "max_total": max_total, "min_large_bags": min_large_bags, "fx": fx}
        out["filters_used"] = (([f"{gearbox.capitalize()} gearbox (operator)"] if gearbox else []) + (["Zero excess (operator): not met by any Europcar list row"] if zero_excess else [])
                               + ([f"at least {min_seats} seats (operator)"] if min_seats else []) + ([f"budget up to {max_total:g} EUR for the whole rental (operator)"] if max_total is not None else [])
                               + ([f"room for {min_large_bags} large bags (operator): NOT checkable on Europcar"] if min_large_bags else [])
                               + [f"driver age {age} " + ("(operator)" if driver_years else f"(default {DEFAULT_AGE}: ask if the driver is younger or older)"), f"country of residence {residency.upper()} (trip default: it sets the price currency)"]
                               + ([f"prices in other currencies converted to EUR by the server at the {fx['source']} of {fx['date']} (USD 1 = EUR {fx['factors']['USD']:.4f})"] if fx and "USD" in fx["factors"]
                                  else ["no euro exchange rate was available: Europcar rows in another currency stay unconverted (the server never guesses a rate)"] if not fx else []))
        out["pickup_time"] = pickup_time
        return out
