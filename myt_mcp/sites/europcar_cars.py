"""Europcar cars (europcar.com, English site): a URL (every search value is in the address) and a tested read-only script for the operator's own Chrome (a site module).

Site rules (found on the real pages 27 Oct 2026; the offers service read and compared 5 Nov 2026):
* Results address: /en-us/reservation/vehicles?vehicleType=CR&pickupLocation=<station>&dropoffLocation=<station>&pickupYear&pickupMonth&pickupDay&dropoffYear&dropoffMonth&dropoffDay&pickupHour
  &pickupMinute&dropoffHour&dropoffMinute&driverAge=<years>&countryOfResidence=<2 letters>. Stations are codes (LIST01 = Lisbon Airport), learned once from the address after a search.
* The page gets its cars with ONE request to Europcar's own offers service: GET api.aws.emobg.io/group-direct-channel-context/v1/offers?apikey=<the page's key>&origin=...&vehicle-types=CAR,LUXURY
  &country-of-residence=IL&pickup-station-code=LIST01&drop-off-station-code=LIST01&pickup-date=2027-03-08T10:00&drop-off-date=2027-03-11T10:00&driver-age=30&sort=-recommendation,price&limit=10&offset=0
  [&filter=feature:contains:AUTOMATIC,seats:gte:5]. The script finds that request in the page's own network log and sends it again from the page with limit=50 (32 cars in 1.2 s; no scrolling, no cards). The key is
  the page's own and never leaves it (a station search has another key). Filters checked live (the count equals the page's): `feature:contains:AUTOMATIC`, `segment:contains:SUV`, `seats:gte:N`, joined with commas;
  `sort=price` is ascending. NOT sent: luggage (the page's luggage number is not "large bags"), budget, zero excess. An unknown filter is not checked, so the server judges every wish itself (`fits`).
* An offer has the car (model, ACRISS, category, seats, luggages, doors, A/C, automatic, fuel, segments, features such as PREMIUM and MODEL_CHOICE) and a rate with the price IN THE STATION'S CURRENCY (EUR for Lisbon)
  AND in the driver's (USD for Israel): the server uses the station's own price, so no exchange rate is needed. Also the basic protection with its excess in both currencies (BASIC, level 1: no zero-excess
  option is offered in the list), the fuel policy (full-to-full), the mileage (unlimited, or 900 Km included on 2 of 32 cars), cancellation fees (none listed), the booking confirmation (instant, or on request on
  1 of 32), the minimum driver age (19 or 25) and `meta.youngDriverSurchargeApplied` (true at age 22: 22 cars; false at 30: 32 cars). Errors are clean: 409 MINIMUM_DRIVER_AGE (age 18), 400 for a past date.
* Pay at the desk, basic protection included. The prices are the public ones (the form has "I have a negotiated rate"): rows are comparison only.
* The offers answer needs no cookie choice: with the cookie banner open the cards are not drawn (0 cards) and the offers request is still made and answered.
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

from myt_mcp.compose import Offer, mark_unconfirmed
from myt_mcp.errors import tool_errors
from myt_mcp.fx import basis_note, eur_factors, to_eur
from myt_mcp.sites import SiteRows, server_first, place_matches, with_emit
from myt_mcp.sites.ratehawk_cars import cars_ask_gate

NAME = "europcar_cars"
SOURCE = "Europcar (public website price)"
GROUP = "Cars"
HERE = Path(__file__).parent
BASE = "https://www.europcar.com/en-us/reservation/vehicles"
HOME = "https://www.europcar.com/en-us"
DEFAULT_AGE = 30


def stations() -> dict[str, str]:
    data = json.loads((HERE / "europcar_cars.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def results_url(pickup_code: str, dropoff_code: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, age: int, residency: str) -> str:
    p, d = pickup_date.split("-"), dropoff_date.split("-")
    return (f"{BASE}?vehicleType=CR&pickupLocation={pickup_code}&dropoffLocation={dropoff_code}&pickupYear={p[0]}&pickupMonth={p[1]}&pickupDay={p[2]}"
            f"&dropoffYear={d[0]}&dropoffMonth={d[1]}&dropoffDay={d[2]}&pickupHour={pickup_time[:2]}&pickupMinute={pickup_time[3:]}&dropoffHour={dropoff_time[:2]}&dropoffMinute={dropoff_time[3:]}"
            f"&driverAge={age}&countryOfResidence={residency}")


def site_filter(gearbox: str | None, min_seats: int | None) -> str:
    """The wishes Europcar's own filter can narrow (checked live): automatic and a number of seats. Manual, bags, zero excess and the budget are judged by the server."""
    parts = (["feature:contains:AUTOMATIC"] if gearbox == "automatic" else []) + ([f"seats:gte:{int(min_seats)}"] if min_seats and min_seats >= 2 else [])
    return ",".join(parts)


def europcar_cars_recipe(pickup: str, pickup_code: str, dropoff_code: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, age: int, residency: str, filter_text: str = "") -> dict[str, Any]:
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
    expect = {"pickup": pickup, "pickup_station": pickup_code, "dropoff_station": dropoff_code, "pickup_when": f"{pickup_date} {pickup_time}", "dropoff_when": f"{dropoff_date} {dropoff_time}", "age": age, "residency": residency}
    script = with_emit((HERE / "europcar_cars.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps({**expect, "filter": filter_text}))
    return {"url": results_url(pickup_code, dropoff_code, pickup_date, pickup_time, dropoff_date, dropoff_time, age, residency), "script": script, "expect": expect, "site_filter": filter_text}


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _money(v: Any) -> str:
    return f"{v:,.2f}"


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Europcar result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        if data.get("code") == "MINIMUM_DRIVER_AGE":
            return SiteRows(problems=[f"Europcar does not rent to a driver of this age (its own answer: {data.get('error')}): put Europcar in not_checked with the reason 'not available: the driver is under Europcar's minimum age'; never say sold out"])
        return SiteRows(problems=[f"the Europcar script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    form = data.get("form") or {}
    problems: list[str] = []
    notes: list[str] = []
    for key, label in (("pickup_station", "pick-up station"), ("dropoff_station", "return station"), ("pickup_when", "pick-up"), ("dropoff_when", "return")):
        if exp.get(key) and form.get(key) != exp[key]:
            problems.append(f"the page searched {label} '{form.get(key)}', not '{exp[key]}': search again with the url the recipe gave")
    if exp.get("age") and data.get("age") != exp["age"]:
        problems.append(f"the page used driver age {data.get('age')}, not {exp['age']}: search again with the url the recipe gave")
    if exp.get("residency") and data.get("residency") != exp["residency"]:
        problems.append(f"the page priced residency {data.get('residency')}, not {exp['residency']}: search again with the url the recipe gave")
    rows = data.get("rows") or []
    sent = data.get("filter_sent")
    if not rows and not (sent and data.get("total") == 0):
        problems.append("the Europcar answer held no cars: it could not be read (never say sold out); run the script again")
    offers: list[Offer] = []
    seen: set[str] = set()
    currencies: set[str] = set()
    converted = False
    fx = wishes.get("fx") or {}
    days = data.get("days")
    for r in rows:
        total, cur = _num(r.get("total")), str(r.get("cur") or "").upper()
        name = f"{r.get('car') or 'not shown'} ({r.get('category') or r.get('acriss') or 'class not shown'})"
        key = f"{r.get('acriss')}|{name}|{total}"
        if total is None or not cur or key in seen:
            continue
        seen.add(key)
        price, shown, factor = to_eur(total, cur, fx)       # Europcar's own price is in the station's currency (EUR for Portugal): converted only for another currency, by the server
        currencies.add(cur)
        converted = converted or bool(factor)
        seats, per_day = _num(r.get("seats")), _num(r.get("per_day"))
        gear = "Automatic" if r.get("automatic") is True else "Manual" if r.get("automatic") is False else None
        pkgs = [x for x in r.get("packages") or [] if isinstance(x, dict)]
        excess_amounts = [_num(x.get("excess")) for x in pkgs]
        zero = any(x == 0 for x in excess_amounts)
        fits: bool | None = True
        if wishes.get("automatic"):
            fits = bool(fits and gear == "Automatic")
        if wishes.get("manual"):
            fits = bool(fits and gear == "Manual")
        if wishes.get("zero_excess"):
            fits = bool(fits and zero)                       # only a package the offer lists with an excess of 0: none of the 32 cars had one, and a missing excess is never assumed to be zero
        if wishes.get("min_seats"):
            fits = bool(fits and seats is not None and seats >= int(wishes["min_seats"]))
        if wishes.get("max_total") is not None:
            fits = bool(fits and shown == "EUR" and price <= float(wishes["max_total"]))      # the budget is in euro: a price with no euro rate cannot be judged
        seats_bags = " / ".join(x for x in (f"{r['seats']} seats" if r.get("seats") is not None else None, f"{r['bags']} bags" if r.get("bags") is not None else None, f"{r['doors']} doors" if r.get("doors") else None) if x) or None
        cust = f"{r['cur_customer']} {_money(r['total_customer'])}" if r.get("cur_customer") and _num(r.get("total_customer")) is not None and r.get("cur_customer") != cur else None
        def excess_text(x: dict[str, Any]) -> str:
            amount = _num(x.get("excess"))
            if amount is None:
                return f"{x.get('code')} (excess not shown)"
            money = f"{x.get('excess_cur') or cur} {_money(amount)}"
            if factor and amount:
                money = f"EUR {_money(round(amount * factor, 2))} (converted from {money})"
            return f"{x.get('code')} with an excess of {money}"
        excess = ("; ".join(excess_text(x) for x in pkgs) + "; no zero-excess option is offered in the list" if pkgs and not zero else "; ".join(excess_text(x) for x in pkgs) if pkgs else "not shown")
        mileage = "Unlimited mileage" if r.get("mileage_unlimited") else (f"{r['mileage_included']:g} {r.get('mileage_unit') or 'km'} included" if _num(r.get("mileage_included")) else "limited mileage (the allowance is not shown)")
        fuel_policy = str(r.get("fuel_policy") or "").replace("-", " ")
        cancel = ("no cancellation fee listed in the offer (open the booking page for the terms)" if not r.get("cancellation_fees") else f"{r['cancellation_fees']} cancellation fee rule(s) listed: open the booking page")
        confirm = None if r.get("confirmation") in (None, "instant") else f"booking confirmation: {str(r['confirmation']).replace('-', ' ')} (not instant)"
        offers.append(Offer(
            group=group, source=SOURCE, name=name, price_total=price, currency=shown,
            price_basis=(f"whole rental{f', {days} days' if days else ''}, {str(r.get('pay') or 'PAY_ON_ARRIVAL').replace('_', ' ').lower()}, basic protection included, Europcar's own price in the station's currency"
                         + (f", {basis_note(cur, total, factor, fx)}" if factor else "")),
            fits=fits, quotable=False, supplier="Europcar",
            details={"company": "Europcar", "gearbox": gear or "not shown", "seats_bags": seats_bags, "excess": excess, "fuel": f"{r.get('fuel_type') or 'not shown'}; policy {fuel_policy or 'not shown'}", "mileage": mileage,
                     "deposit": "not shown on the list", "cancellation": cancel, "min_driver_age": r.get("min_age"), "air_conditioning": bool(r.get("ac")), "booking_confirmation": confirm,
                     "price_in_driver_currency": cust, "original_price": f"{cur} {_money(total)}" if factor else None,
                     "badges": ", ".join(x for x in (r.get("features") or []) if x in ("PREMIUM", "MODEL_CHOICE")) or None}))
    notes.append("Europcar rows are the public website price (this search has no negotiated or agency rate), so they are comparison only.")
    foreign = sorted(c for c in currencies if c != "EUR")
    if foreign and converted:
        notes.append(f"Europcar's own price for this station is in {', '.join(foreign)}: the server converted it to euro at the {fx.get('source')} of {fx.get('date')} and each row's price basis shows the original price and the rate. Do not convert them yourself.")
        if (fx.get("age_days") or 0) > 3:
            notes.append(f"The exchange rate is {fx['age_days']} days old (the bank publishes on business days): say so.")
    unconverted = sorted(c for c in foreign if not (fx.get("factors") or {}).get(c))
    if unconverted:
        notes.append(f"Europcar's own price for this station is in {', '.join(unconverted)} and no euro rate was available: those rows are shown in their own currency and never compared with euro prices. Do not convert them yourself.")
    if any(o.details.get("price_in_driver_currency") for o in offers):
        notes.append(f"Each row also names Europcar's price in the driver's currency (residency {data.get('residency') or '?'}): the euro price is the station's own price, the other is Europcar's conversion.")
    if data.get("young_driver_fee"):
        notes.append("Europcar says a young-driver surcharge is included in these prices (its own flag): say so.")
    if sent:
        notes.append(f"Europcar itself narrowed the list ({sent}): {data.get('total')} of {data.get('unfiltered_total') or '?'} cars. The other wishes were judged by the server on these cars.")
        if not rows:
            notes.append("Europcar found no car for the wishes sent to it (without them it had cars): say that no car matches, never sold out; offer to relax a wish.")
    if data.get("complete") is False:
        notes.append(f"Europcar counted more cars than were read ({data.get('cars_read')} read): a cheaper car may be among the rest.")
    if wishes.get("min_large_bags"):
        for o in offers:
            mark_unconfirmed(o, "large bags")
        notes.append(f"The operator needs room for {wishes['min_large_bags']} large bags: Europcar shows only a number of luggages without saying which are large, so no Europcar car was checked for it.")
    if wishes.get("zero_excess"):
        notes.append("Zero excess was asked: Europcar's list offers only the basic protection (with an excess) and no zero-excess package, so no Europcar row meets it unless a row says an excess of 0.")
    notes.append("Europcar's list does not show a deposit (the protection and extras come after the Select step, which is never pressed).")
    n = len(rows)
    total_cars = data.get("total") if isinstance(data.get("total"), int) else n
    return SiteRows(offers=offers, read=n, total=total_cars, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


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
        prices are Europcar's own, in the station's currency; never convert one yourself. Then it returns the results url (every value in it) and a read-only SCRIPT: open the
        url, run the script with the javascript tool; it reads every car from Europcar's own offers service (no scrolling) and sends its answer to the server by itself, then returns a short receipt (the `ingest` id): call compose_answer
        with `runs`=[that id] and this tool's `wishes` and `filters_used`. Never press Select or type a row. A check page or block is never worked around: stop and tell the operator. SERVER FIRST: the server first reads this page itself in its own automation Chrome (the same script); then the answer is a short receipt with an `ingest` id and you only call compose_answer with `runs`=[that id]. If it could not (the answer then has `server_read` with the reason, and the url and script below), read the page in Claude in Chrome as described here. Never retry the server's read."""
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
            out = europcar_cars_recipe(pickup, pickup_code, drop_code, pickup_date, pickup_time, dropoff_date, dropoff_time, age, residency.upper(), site_filter(gearbox, min_seats))
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        out["wishes"] = {"expect": out["expect"], "automatic": gearbox == "automatic", "manual": gearbox == "manual", "zero_excess": bool(zero_excess), "min_seats": min_seats, "max_total": max_total, "min_large_bags": min_large_bags, "fx": fx}
        out["filters_used"] = (([f"{gearbox.capitalize()} gearbox (operator)"] if gearbox else []) + (["Zero excess (operator): only a row listing an excess of 0 meets it (Europcar's list has none)"] if zero_excess else [])
                               + ([f"at least {min_seats} seats (operator)"] if min_seats else []) + ([f"sent to Europcar's own filter: {out['site_filter']}; the other wishes are judged by the server"] if out["site_filter"] else []) + ([f"budget up to {max_total:g} EUR for the whole rental (operator)"] if max_total is not None else [])
                               + ([f"room for {min_large_bags} large bags (operator): NOT checkable on Europcar"] if min_large_bags else [])
                               + [f"driver age {age} " + ("(operator)" if driver_years else f"(default {DEFAULT_AGE}: ask if the driver is younger or older)"), f"country of residence {residency.upper()} (trip default: it sets the price currency)"]
                               + ([f"prices in other currencies converted to EUR by the server at the {fx['source']} of {fx['date']} (USD 1 = EUR {fx['factors']['USD']:.4f})"] if fx and "USD" in fx["factors"]
                                  else ["no euro exchange rate was available: Europcar rows in another currency stay unconverted (the server never guesses a rate)"] if not fx else []))
        out["pickup_time"] = pickup_time
        return await server_first(NAME, "EUROPCAR_READ_IN_SERVER", "https://www.europcar.com", out)
