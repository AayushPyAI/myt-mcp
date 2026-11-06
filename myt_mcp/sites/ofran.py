"""Ofran car rental (the agency's own logged-in Ofran): a tested read-only script for any Ofran page of the operator's own Chrome (a site module).

Site rules (read live 5 Nov 2026, and 26 cars compared one by one with the cards on 4 Nov): Ofran's pages get their cars with ONE request, POST /api/get_full_dynamic_result?order_uuid=<any new uuid> (body: CountryId,
PickupIataId, PickupDate "08.03.2027", PickupHour "17:00", DropoffIataId, DropoffDate, DropoffHour, Age, GoTos; no token, only the agent's login cookie); the place ids are in GET /api/locations (1,598 places). The script sends
that request from the page, so there is no form to fill and no results page to wait for: 3.7 s for 26 cars against about 12 s of page and card reading. A result is `{contracts[], cargroup}`: the contract has the price after the
agent discount (`nettotal`), the list price (`OfflineRate`), the plan (`contractname`: "תכנית בסיס" = base plan, "תכנית ביטול השתתפות עצמית" = the plan with the excess cancelled), `CDWExcess`, `TPExcess`, `Deposit`, `OneWayFee`
(a plain number as text, e.g. "110.70", NOT in the price: 25 of 62 cars on a Lisbon to Porto search against 10 on a same-station one, and the cheapest and dearest prices were the same; no currency is given) and the optional extras with their price; the car group has the supplier, its rating, the ACRISS code (third letter M/N/C = manual, A/B/D = automatic), the adults and kids (seats = both), doors, suitcases
and handbags, and `Filters.StationType` (Airport = the card's "pick-up station inside the airport"). The site's own filter boxes work in the page only (the answer is the whole list): every wish is judged here, from the data:
zero excess = the damage and the theft excess are both 0 (the same cars as the excess-cancelled plan: 54 of 62 on a Lisbon search, in Hebrew and in English; the plan's name is "תכנית ביטול השתתפות עצמית" or "Zero Excess", so it is only shown); inside the airport = station type Airport. Errors come as HTTP 200 with `errors[]`; the age band is 21-85 (an empty age is the page's own
default; age 20 answers `errors[]` code 100 "Age is not in the standard range"; age 21 shows only 38 of 62 cars and a few dearer ones, ages 25 and 70 the same list as 30, so the real age is always sent). The station type is Airport or Off Airport. THE PAGE'S LANGUAGE CHANGES THE ANSWER'S TEXT (plan names "תכנית בסיס" / "Inclusive", "Zero Excess"; error texts) and the logout link ("התנתקות" / "Logout"): nothing is judged on a text. The script needs the agent's login cookie for the agent's price (the page's top bar then shows a logout link); without it the prices are the public ones and the answer says so. Times are the operator's or the trip's, never a guess.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer, mark_unconfirmed
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, place_matches, with_emit
from myt_mcp.sites.ratehawk_cars import cars_ask_gate

NAME = "ofran"
SOURCE = "Ofran"
GROUP = "Cars"
HERE = Path(__file__).parent
BATCH = 100          # the API answers every car at once (62 for Lisbon, 77 for Firenze): the old 30-car page cut the cheap manual cars off the front and left the fitting ones unread (5 Nov 2026 chat test)
HOME = "https://ofran.co.il/"
MIN_AGE, MAX_AGE = 21, 85
AUTOMATIC, MANUAL = set("ABD"), set("MNC")          # the third letter of the ACRISS code


def gearbox_of(acriss: str | None) -> str | None:
    letter = (acriss or "")[2:3]
    return "Automatic" if letter in AUTOMATIC else "Manual" if letter in MANUAL else None


def station_text(station_type: str | None) -> str:
    """Ofran's station type in words: 'Airport' is the card's 'pick-up station inside the airport'; any other type is not an airport station (said as outside, so a pick there is cautioned)."""
    if not station_type:
        return "not shown"
    return "Pick-up station inside the airport" if station_type == "Airport" else f"Pick-up station outside the airport (not at the terminal; Ofran's station type: {station_type})"


def ofran_recipe(pickup: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, offset: int = 0, limit: int = BATCH, driver_years: int | None = None, dropoff: str | None = None) -> dict[str, Any]:
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
    if driver_years is not None and not MIN_AGE <= driver_years <= MAX_AGE:
        raise ValueError(f"Ofran takes drivers aged {MIN_AGE}-{MAX_AGE} (its own error otherwise): tell the operator that Ofran cannot be searched for this driver")
    request = {"pickup": pickup, "dropoff": dropoff, "pickup_date": pickup_date, "pickup_time": pickup_time, "dropoff_date": dropoff_date, "dropoff_time": dropoff_time, "age": driver_years, "skip": offset, "limit": limit}
    script = with_emit((HERE / "ofran.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps(request, ensure_ascii=False))
    expect = {"pickup": pickup, "dropoff": dropoff, "pickup_date": pickup_date, "pickup_time": pickup_time, "dropoff_date": dropoff_date, "dropoff_time": dropoff_time, "driver_years": driver_years}
    steps = [f"Open {HOME} (any page of Ofran) in the operator's Chrome (the one logged in to Ofran). The login check (login_check) is optional: it only tells the operator early. The script reads Ofran either way and marks the rows itself (without the agent login they are the public prices, comparison only).",
             "Run `script` with the javascript tool on that page: it finds the place in Ofran's own list, sends Ofran's own search request and reads every car. There is no form to fill. ok=false: do what `error` says (a place it could not find: ask the operator for the airport's name). Never read cars by eye.",
             "The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row, with the returned `wishes`, `filters_used` and `pickup_time`."]
    return {"script": script, "url": HOME, "expect": expect, "steps": steps}


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ddmmyy(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[2:4]}"


def _days(pickup_date: str | None, pickup_time: str | None, dropoff_date: str | None, dropoff_time: str | None) -> int | None:
    try:
        a, b = (datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M") for d, t in ((pickup_date, pickup_time), (dropoff_date, dropoff_time)))
    except (TypeError, ValueError):
        return None
    return max(1, math.ceil((b - a).total_seconds() / 86400))


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
    form = data.get("form") or {}
    if exp:
        if exp.get("pickup") and form.get("pickup_place") and not place_matches(exp["pickup"], form["pickup_place"]):
            problems.append(f"the script searched '{form.get('pickup_place')}', not '{exp['pickup']}': ask the operator for the airport's name as Ofran writes it")
        if exp.get("dropoff") and form.get("dropoff_place") and not place_matches(exp["dropoff"], form["dropoff_place"]):
            problems.append(f"the script returned the car at '{form.get('dropoff_place')}', not '{exp['dropoff']}': ask the operator for the place's name as Ofran writes it")
        for which, d, t in (("pickup_when", exp.get("pickup_date"), exp.get("pickup_time")), ("dropoff_when", exp.get("dropoff_date"), exp.get("dropoff_time"))):
            want = f"{_ddmmyy(d)} | {t}" if d and t else None
            if want and form.get(which) and form[which] != want:
                problems.append(f"the script searched '{form[which]}', not '{want}': run the recipe again")
        if exp.get("driver_years") and form.get("age") and str(exp["driver_years"]) != str(form["age"]):
            problems.append(f"the script searched driver age '{form['age']}', not '{exp['driver_years']}': run the recipe again")
    agent = bool(data.get("logged_in"))
    if data.get("logged_in") is False:       # read anyway (the API answers without the login, with the public price): never quotable, and what the page showed is said
        d = data.get("diag") or {}
        notes.append("Ofran was read WITHOUT the agent login (no logout link on the page, Hebrew or English): these are Ofran's PUBLIC prices, higher than the agency's (about 8% on the one search compared), so they are comparison only. "
                     "Tell the operator to log in to Ofran in this Chrome and read it again for the agency price."
                     + (f" The page the script ran on: {d.get('page')} ('{d.get('title')}'), showing: {str(d.get('text_start') or '')[:120]!r}" + ("; a login link is on it" if d.get("login_link") else "") if d else ""))
    one_way = bool(exp.get("dropoff")) and not place_matches(exp.get("pickup"), form.get("dropoff_place")) if form.get("dropoff_place") else bool(exp.get("dropoff"))
    days = _days(exp.get("pickup_date"), exp.get("pickup_time"), exp.get("dropoff_date"), exp.get("dropoff_time"))
    rows = data.get("rows") or []
    offers: list[Offer] = []
    for r in rows:
        price, cur = _num(r.get("price")), str(r.get("currency") or "").upper()
        if price is None or not cur:
            continue
        fee = _num(r.get("one_way_fee"))
        if one_way and fee:         # Ofran lists the one-way fee beside the price (checked: the same prices with and without it): a one-way search adds it, so cars compare with the other sources and the budget
            price = round(price + fee, 2)
        gear = gearbox_of(r.get("acriss"))
        adults, kids = _num(r.get("seats")), _num(r.get("kids"))
        seats = None if adults is None else adults + (kids or 0)
        cdw, theft, deposit = _num(r.get("cdw_excess")), _num(r.get("theft_excess")), _num(r.get("deposit"))
        zero = cdw == 0 and theft == 0          # the same cars as the excess-cancelled plan in both languages (54 of 54 in Hebrew and in English); the plan's name is only shown, never read
        fits: bool | None = None
        seat_doubt = False
        if wishes:
            ok = True
            if wishes.get("automatic"):
                ok &= gear == "Automatic"
            if wishes.get("manual"):
                ok &= gear == "Manual"
            if wishes.get("zero_excess"):
                ok &= zero
            if wishes.get("min_seats"):
                want = int(wishes["min_seats"])
                if seats is None or seats < want - 1:
                    ok = False
                elif seats < want:
                    seat_doubt = True          # Ofran's number is its RECOMMENDED passengers: one short of the wish can still be a car with enough seats (a Citroen C4 shows 2+2 = 4 on Ofran and 5 seats on Europcar)
            if wishes.get("max_total") is not None:
                ok &= cur == "EUR" and price <= float(wishes["max_total"])
            if wishes.get("inside_airport"):
                ok &= r.get("station_type") == "Airport"
            fits = ok

        def money(x: float | None) -> str:
            return "not shown" if x is None else f"{x:,.2f} {r.get('excess_currency') or cur}"
        bags = " + ".join(x for x in (f"{r['suitcases']} suitcases" if r.get("suitcases") not in (None, "") else None, f"{r['handbags']} handbags" if r.get("handbags") not in (None, "") else None) if x) or None
        seats_bags = " / ".join(x for x in (f"{seats:g} seats (Ofran's recommended: {adults:g} adults + {kids or 0:g} kids)" if seats is not None else None, bags, f"{r['doors']} doors" if r.get("doors") else None) if x) or None
        list_price = _num(r.get("price_before")) if not (one_way and fee) else (_num(r.get("price_before")) or 0) + fee or None
        basis = (f"whole rental{f', {days} days (counted from the dates)' if days else ''}, price after the agent discount" + (f" (list price {list_price:g})" if agent and list_price and list_price > price else "")
                 if agent else f"whole rental{f', {days} days (counted from the dates)' if days else ''}, PUBLIC price (the agent is not logged in)")
        if one_way and fee:
            basis += f"; includes Ofran's one-way fee of {fee:g} added to the listed price (Ofran gives no currency for the fee: taken as {cur})"
        extras = [e for e in r.get("extras") or [] if isinstance(e, dict) and e.get("name")]
        upgrade = "; ".join(f"{e['name']} +{e.get('price')} {e.get('currency') or cur} (not in the price)" for e in extras) or None
        offers.append(Offer(
            group=group, source=SOURCE, name=f"{r.get('car') or 'not shown'} ({r.get('acriss') or '?'}, {r.get('size') or 'class not shown'})", price_total=price, currency=cur, price_basis=basis, fits=fits, supplier=r.get("supplier"), quotable=agent,
            details={"company": (r.get("supplier") or "not shown") + (f" (score {float(r['supplier_score']):g})" if _num(r.get("supplier_score")) else ""), "gearbox": gear or "not shown", "seats_bags": seats_bags,
                     "excess": ("excess cancelled (the plan includes it, excess 0)" if zero else f"damage excess {money(cdw)}, theft excess {money(theft)}"), "fuel": "not shown on the list", "mileage": "not shown on the list",
                     "deposit": money(deposit), "cancellation": "not shown on the list",
                     "pickup_place": station_text(r.get("station_type")), "score": r.get("supplier_score"),
                     "plan": r.get("package") or "not shown", "optional_extras": upgrade,
                     "one_way_fee": (f"{fee:g} {cur}, added to the price above (Ofran lists it beside the price)" if one_way and fee else f"{r['one_way_fee']} listed by Ofran, NOT added: it gives no currency and does not say when it applies (the search returns the car to the same place)" if r.get("one_way_fee") else None)}))
        if seat_doubt and fits:
            mark_unconfirmed(offers[-1], "seats")
    n = len(rows)
    if not rows:
        notes.append("Ofran answered with no cars for this search (its own answer, not an error): say that Ofran showed no car, never 'sold out'; the dates, the place or the age may be outside what Ofran rents.")
    if wishes.get("min_seats") and any("seats" in o.unconfirmed for o in offers):
        notes.append(f"Some Ofran cars show one seat fewer than the {wishes['min_seats']} asked: Ofran's number is its RECOMMENDED passengers (adults + kids), not the seats (a Citroen C4 is 2+2 = 4 on Ofran and has 5 seats on Europcar). They are marked not confirmed, never a pick: check the car on Ofran.")
    if wishes.get("min_large_bags"):
        for o in offers:
            mark_unconfirmed(o, "large bags")      # Ofran lists suitcases and handbags without saying which suitcases are large: never a pick on a wish it cannot show (28 Oct 2026: Best fit, 'meets every wish')
        notes.append(f"The operator needs room for {wishes['min_large_bags']} large bags: Ofran lists suitcases and handbags without saying which suitcases are large, so no Ofran car was checked for it: open the car's page before quoting an Ofran car.")
    if exp.get("driver_years"):
        notes.append(f"Ofran was searched with the driver's age {exp['driver_years']} (its band is {MIN_AGE}-{MAX_AGE}).")
    else:
        notes.append("No driver age was given: Ofran was searched with its own default age.")
    if any(r.get("one_way_fee") for r in rows):
        notes.append("Ofran's one-way fee is added to the price of every Ofran car that lists one on this one-way search (each row says so)." if one_way else "Some Ofran cars list a one-way fee without saying when it applies; it is NOT in their price (each row says so): mention it.")
    other = [f"{x.get('name')} ({x.get('code')})" for x in data.get("other_places") or [] if isinstance(x, dict)]
    if other:
        notes.append(f"Ofran searched {form.get('pickup_place')}; other Ofran places that also match: {', '.join(other)}: ask the operator if they meant another one.")
    notes.append("Ofran's list does not show fuel policy, mileage or cancellation: they are on the car's own page after choosing it (do not press the choose button).")
    if data.get("offset"):
        notes.append(f"These are cars {int(data['offset']) + 1} to {int(data['offset']) + n} of the price-sorted list (cheaper ones were shown before): the Cheapest here is not the cheapest overall.")
    total = data.get("cars_total") if isinstance(data.get("cars_total"), int) else n
    return SiteRows(offers=offers, read=n, total=total, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ofran_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ofran_recipe_tool(pickup: str, pickup_date: str, pickup_time: str, dropoff_date: str, dropoff_time: str, gearbox: str | None = None, min_seats: int | None = None,
                                zero_excess: bool | None = None, max_total: float | None = None, inside_airport: bool = False, operator_answered: bool = False,
                                offset: int = 0, limit: int = BATCH, driver_years: int | None = None, min_large_bags: int | None = None, dropoff: str | None = None) -> dict[str, Any]:
        """FOR CAR RENTAL ON OFRAN (the agency's logged-in Ofran, read in the operator's own Chrome with Claude in Chrome; the agency's own price). ASK FIRST like ratehawk_cars_recipe: without `gearbox`
        ('automatic' / 'manual'), `min_seats`, `zero_excess` (true/false) and `max_total` (EUR, whole rental) it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with
        the answers (`operator_answered`=true for "no preference", only after the operator replied). Times are required (from the trip's flight or the operator; never your own choice) and the same on
        RateHawk. Then it returns a read-only SCRIPT: open any page of ofran.co.il in the operator's logged-in Chrome and run it with the javascript tool; there is no form to fill. It finds the place in Ofran's own
        list, sends Ofran's own search and reads up to `limit` (100) cars from `offset`. The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is
        in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row, `filters_used` and `pickup_time`. `min_large_bags` = LARGE suitcases wanted (Ofran cannot confirm it, the answer says so). `driver_years` = age (21-85, searched as given). `dropoff` only for another return place. Run login_check first only to tell the operator: a missing login never skips Ofran (public prices, comparison only). An "Access Denied" (the VPN is needed) or a human check is never worked around: stop and tell the operator. `pickup` is the place ('Faro Airport'); dates YYYY-MM-DD."""
        asked = cars_ask_gate(gearbox, min_seats, zero_excess, max_total, operator_answered)
        if asked:
            return asked
        if gearbox not in (None, "automatic", "manual"):
            raise ValueError("gearbox must be 'automatic', 'manual' or left out")
        out = ofran_recipe(pickup, pickup_date, pickup_time, dropoff_date, dropoff_time, offset, limit, driver_years, dropoff)
        out["wishes"] = {"expect": out["expect"], "automatic": gearbox == "automatic", "manual": gearbox == "manual", "zero_excess": bool(zero_excess), "min_seats": min_seats, "max_total": max_total, "min_large_bags": min_large_bags,
                         "inside_airport": bool(inside_airport)}
        out["filters_used"] = ([f"{gearbox.capitalize()} gearbox (operator)"] if gearbox else []) + (["Excess cancelled / zero excess (operator): the excess-cancelled plan with an excess of 0"] if zero_excess else []) + \
            ([f"at least {min_seats} seats (operator; Ofran gives recommended passengers: one short is not confirmed)"] if min_seats else []) + ([f"budget up to {max_total:g} EUR for the whole rental (operator)"] if max_total is not None else []) + \
            (["Inside the airport (operator)"] if inside_airport else []) + ([f"room for {min_large_bags} large bags (operator): NOT checkable on Ofran, it lists suitcases and handbags without saying which are large"] if min_large_bags else []) + \
            [f"driver age {driver_years} (operator; searched as given)" if driver_years else "driver age: Ofran's own default (none given)"]
        out["pickup_time"] = pickup_time
        out["login_check"] = {"run_first": "OPTIONAL, to tell the operator early: open https://ofran.co.il/ (any page of Ofran) and run (async () => { for (let i = 0; i < 16; i++) { if (/\u05d4\u05ea\u05e0\u05ea\u05e7\u05d5\u05ea|log\\s?out/i.test(document.body.innerText)) return true; await new Promise((r) => setTimeout(r, 500)); } return false; })() with the javascript tool (it waits up to 8 s for the logout link).",
                              "if_false": "Do NOT stop and do NOT put Ofran in not_checked: run the script anyway. Ofran answers without the agent login too, with its public prices: the answer then marks every Ofran row 'comparison only' and says the agent was not logged in. Tell the operator to log in in this Chrome (you never type a password)."}
        out["more"] = f"For the next {limit} cars call this tool again with the same values and offset={offset + limit}; say so to the operator at the end of the answer."
        return out
