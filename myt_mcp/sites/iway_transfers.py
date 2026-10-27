"""iWay (iway.io) transfers: the price of a whole vehicle for a route (a site module, see myt_mcp/sites/__init__.py), read in the OPERATOR'S Chrome where the agency's iWay account is logged in.

Site rules (found on the real page, 27 Oct 2026): iway.io/booking has two boxes (From, To; a typed text lists suggestions, the one chosen writes its Google place id into the address:
iway.io/booking?from=<id>&to=<id>). With both chosen, "Choose car class" lists one button.class-item per vehicle class ("Standard", "Business", "Minivan", "Minivan VIP") with the passengers and bags it holds,
the car ("Toyota Corolla and similar") and the price of the whole vehicle in the account's currency (USD for this account: the server converts it to euro like Europcar's, myt_mcp/fx.py). The list takes no date,
time or passengers: iWay asks them at its next step (behind "Order now", never pressed here), so a night or holiday surcharge or a wait can change the price there and the list price is a comparison. The "Round
trip" box and "Add address" are not used (one call per leg: swap From and To for the way back). No Content-Security-Policy, no human check seen. The agency's login lives in the operator's own Chrome, so this is
read there only (the server's Chrome is not logged in and no password is ever typed). A human check is never worked around.
"""

from __future__ import annotations

import json
import re
import unicodedata
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

NAME = "iway_transfers"
SOURCE = "iWay (the agency account, list price)"
GROUP = "Transfers"
HERE = Path(__file__).parent
URL = "https://iway.io/booking"
SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "₪": "ILS"}
CODES = {"USD", "EUR", "GBP", "ILS", "CHF"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()).strip()


def places() -> dict[str, dict[str, Any]]:
    data = json.loads((HERE / "iway_places.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def find_place(text: str) -> dict[str, Any] | None:
    """The known iWay place a name means (by its key, its name or an alias), else None: iWay's own box then finds it."""
    want = _norm(text)
    if not want:
        return None
    for key, p in places().items():
        names = {_norm(key), _norm(p["name"]), *(_norm(a) for a in p.get("aliases", []))}
        if want in names or any(len(n) > 3 and n in want for n in names):
            return p
    return None


def iway_transfers_recipe(origin: str, destination: str, day: date, time: str, adults: int = 2, children_ages: list[int] | None = None, bags: int | None = None,
                          max_total: float | None = None, from_place_id: str | None = None, to_place_id: str | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time):
        raise ValueError("time must be HH:MM, e.g. 10:00 (the flight's arrival or the operator's time: never pick one yourself)")
    ages = list(children_ages or [])
    if not 1 <= adults + len(ages) <= 16 or any(not 0 <= a <= 17 for a in ages):
        raise ValueError("travellers must be 1-16 in total, children's ages 0-17")
    if not origin.strip() or not destination.strip() or _norm(origin) == _norm(destination):
        raise ValueError("origin and destination must be two different places")
    a, b = find_place(origin), find_place(destination)
    from_id = from_place_id or (a or {}).get("id")
    to_id = to_place_id or (b or {}).get("id")
    expect = {"from": origin.strip(), "to": destination.strip(), "from_id": from_id, "to_id": to_id, "day": day.isoformat(), "time": time, "adults": adults, "children": len(ages), "ages": ages,
              "total": adults + len(ages), "bags": bags, "leg": f"{origin.strip()} to {destination.strip()}, {day:%d %b %Y} {time}"}
    url = f"{URL}?from={from_id}&to={to_id}" if from_id and to_id else URL
    steps = [] if from_id and to_id else [
        f"Open {URL}. In the From box type '{origin.strip()}' and CHOOSE the suggestion that is exactly that place; in the To box type '{destination.strip()}' and choose the exact place. The list 'Choose car class' then appears by itself.",
        "Do NOT press Order now, Add address, Round trip or anything else. Then run the script."]
    script = with_emit((HERE / "iway_transfers.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps({"from_id": from_id, "to_id": to_id}))
    out = {"url": url, "script": script, "expect": expect}
    if steps:
        out["steps"] = steps
    return out


def _num(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the iWay result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the iWay script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    form = data.get("form") or {}
    problems: list[str] = []
    notes: list[str] = []
    if data.get("unparsed"):
        problems.append(f"iWay wrote a vehicle class in a form the reader does not know ({str(data['unparsed'][0])[:80]}...): the page may have changed; read it by hand and say so")
    for key, label in (("from", "from"), ("to", "to")):
        if exp.get(f"{key}_id") and form.get(f"{label}_id") == exp[f"{key}_id"]:
            continue      # the place id in the address IS the place; iWay writes its name differently each time ("Airport Lisbon Portela", later "Humberto Delgado Airport")
        if exp.get(key) and form.get(f"{label}_name") and not place_matches(exp[key], form[f"{label}_name"]):
            problems.append(f"the page searched {label} '{form.get(f'{label}_name')}', not '{exp[key]}': choose the right place in the box and run the script once more")
    if not form.get("logged_in"):
        notes.append("iWay's page did not show the agency account as logged in: these may be public prices, not the agency's. Say so.")
    fx = wishes.get("fx") or {}
    offers: list[Offer] = []
    currencies: set[str] = set()
    converted = False
    need = exp.get("total") or 0
    for r in data.get("rows", []):
        total = _num(r.get("price"))
        cur = SYMBOLS.get(r.get("symbol") or "") or (r["symbol"] if r.get("symbol") in CODES else None)      # a currency symbol or a code the server knows: any other word is not a price
        name = f"{r.get('klass') or 'class not shown'}: {(r.get('car') or 'car not shown')[:60]}"
        if total is None or cur is None:
            problems.append(f"{name}: the price {r.get('symbol')!r} {r.get('price')!r} is not one the converter knows: the row was not read")
            continue
        price, shown, factor = to_eur(total, cur, fx)
        currencies.add(cur)
        converted = converted or bool(factor)
        pax, bags = r.get("passengers"), r.get("bags")
        fit: bool | None = (pax >= need) if need and pax else None
        if fit is not False and wishes.get("min_bags"):
            fit = bool(bags) and bags >= int(wishes["min_bags"])
        if fit is not False and wishes.get("max_total") is not None:
            fit = shown == "EUR" and price <= float(wishes["max_total"])      # the budget is in euro: a price with no euro rate cannot be judged
        offers.append(Offer(
            group=exp.get("leg") or group, source=SOURCE, name=name, price_total=price, currency=shown,
            price_basis=("per vehicle, one way, iWay's list price for the route (its date and time step was not opened: a night or holiday surcharge or a wait may change it)"
                         + (f", {basis_note(cur, total, factor, fx)}" if factor else "")),
            fits=fit, quotable=False, supplier="iWay",
            details={"capacity": f"up to {pax} people / {bags} bags" if pax else "not shown", "waiting_time": "not shown on the list", "cancellation": "not shown on the list (iWay asks at its next step)",
                     "provider": "iWay (the agency's logged-in account)", "meeting_point": "not shown on the list",
                     "route": (f"{form['route'][0]} km" + (f", about {form['route'][1]}" if form.get("route") and form["route"][1] else "")) if form.get("route") and form["route"][0] else "not shown",
                     "original_price": f"{cur} {total:,.2f}" if factor else None}))
    foreign = sorted(c for c in currencies if c != "EUR")
    if foreign and converted:
        notes.append(f"iWay priced this account in {', '.join(foreign)}: the server converted the prices to euro at the {fx.get('source')} of {fx.get('date')} and each row's price basis shows the original price and the rate. "
                     "Do not convert them yourself.")
        if (fx.get("age_days") or 0) > 3:
            notes.append(f"The exchange rate is {fx['age_days']} days old (the bank publishes on business days): say so.")
    unconverted = sorted(c for c in foreign if not (fx.get("factors") or {}).get(c))
    if unconverted:
        notes.append(f"iWay priced this account in {', '.join(unconverted)} and no euro rate was available: those rows stay in that currency, are not compared with euro rows and a euro budget cannot be judged on them.")
    notes.append("iWay's list price for this route: its date, time and passengers are asked at its next step, which was not opened, so the price can change there; it is comparison only (the price to quote is the one iWay confirms for the booking).")
    if form.get("from_id") and form.get("to_id"):
        notes.append(f"iWay place ids read: from {form['from_id']}, to {form['to_id']}.")
    n = len(offers)
    if not data.get("rows") and not problems:
        problems.append("no vehicle class could be read: say it could not be read, never that there is no transfer")
    return SiteRows(offers=offers, read=n, total=n, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="iway_transfers_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def iway_transfers_recipe_tool(origin: str, destination: str, day: date, time: str, adults: int = 2, children_ages: list[int] | None = None, bags: int | None = None,
                                         max_total: float | None = None, from_place_id: str | None = None, to_place_id: str | None = None) -> dict[str, Any]:
        """FOR AIRPORT TRANSFERS ON IWAY (iway.io; the agency's account is logged in in the operator's own Chrome: read there with Claude in Chrome ONLY, never by the server), next to RateHawk Transfers and Kiwitaxi.
        One call per leg (swap origin and destination for the way back). `origin` and `destination` are the places as the operator said them; `day` and `time` are the pick-up (the flight's arrival time or the
        operator's: never your own); `adults` and `children_ages`; `bags` and `max_total` (EUR) only if the operator gave them. iWay's list takes no date, time or passengers: it asks them at its next step, which
        is never opened, so the prices are the list price of the route (a surcharge may apply there). For a place it knows the url holds both places; for another place the answer has `steps` (type the
        place in iWay's box and choose the exact suggestion, never press Order now). Then run the script with the javascript tool: it reads every vehicle class (capacity, car, price of the whole vehicle in the
        account's currency, converted to euro by the server), sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): call compose_answer
        with `runs`=[that id], the returned `wishes` and `filters_used`; never type a row. Never press Order now or any booking button. A human check or a login page is never worked around: stop and tell the operator."""
        try:
            out = iway_transfers_recipe(origin, destination, day, time, adults, children_ages, bags, max_total, from_place_id, to_place_id)
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        fx = await eur_factors()
        out["wishes"] = {"expect": out["expect"], "min_bags": bags, "max_total": max_total, "fx": fx}
        out["filters_used"] = [f"{out['expect']['from']} to {out['expect']['to']}, {day.isoformat()} {time} (operator; iWay's list does not use the date and time)", f"{out['expect']['total']} travellers (operator)",
                               "One way, price per vehicle (iWay)"] + ([f"At least {bags} bags (operator)"] if bags else []) + ([f"Max {max_total:g} EUR (operator)"] if max_total is not None else []) + \
            (["Prices converted to EUR by the server at the Bank of Israel representative rates (server default)"] if fx else ["No euro exchange rate was available: iWay rows stay in the account's currency (server default)"])
        return out
