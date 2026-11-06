"""Booking.com flights (one way, one leg per call, COMPARISON ONLY): a URL and a tested read-only script for the operator's own Chrome (a site module, see myt_mcp/sites/__init__.py).

Site rules (found on the real page, 27 Oct 2026; the data source read live 5 Nov 2026): the address is flights.booking.com/flights/<FROM>.AIRPORT-<TO>.AIRPORT/?type=ONEWAY&adults=N[&children=8,10]&cabinClass=ECONOMY&from=<FROM>.AIRPORT&to=<TO>.AIRPORT
&depart=YYYY-MM-DD&sort=BEST&currency=EUR[&stops=0]. The results page gets its flights from GET /api/flights/ with the same parameters plus enableVI=1&search_source=user (the page's AWS WAF cookies travel with a request made from the page;
a plain HTTP client is not used): `flightOffers` (15 a page, `page=N`), `aggregation` (totalCount, filteredTotalCount, stops, airlines, baggage counts), `searchId`. Verified live against the API itself: stops=0 gives exactly the direct flights,
airlines=TP only TAP, depTimeInt=06-11 only departures 06-11, includedBaggage=CHECKIN only fares with a checked bag, children=8 adds a traveller and its price, cabinClass=BUSINESS only business, page=11 holds the last 5 of 155. Each offer has
the legs (flight numbers, marketing and operating carrier, cabin, technical stops), the price of the whole group (`priceBreakdown.total`, `totalWithoutDiscount` = the list price, base fare, tax, fee), `travellerPrices`, `includedProducts`
(personal item, hand baggage with weight and size, checked baggage with pieces and weight) and `extraProducts` (checkedInBaggage, flexibleTicket: offered, not priced here). The list does not give a fare name or refund terms.
Booking.com only compares: the price to quote comes from the airline's own page, so its rows are never a pick. Airport codes only (a city code needs another address that was not tested). Best and Cheapest are read together (the agency's rule).
A human check is never worked around.
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
from myt_mcp.sites import SiteRows, server_first, with_emit

NAME = "booking_flights"
SOURCE = "Booking.com flights (public website price)"
GROUP = "Flights"
HERE = Path(__file__).parent
PER_PAGE = 15
DEFAULT_PAGES = 2       # pages of each sort: 30 flights of Best and 30 of Cheapest
MAX_PAGES = 5      # 4 page changes took 8 s live (27 Oct 2026), so 2 sorts x 5 pages stay well inside the browser tool's 45 s
SORTS = ["Best", "Cheapest"]
CABINS = {"economy": ("ECONOMY", "Economy"), "premium": ("PREMIUM_ECONOMY", "Premium economy"), "business": ("BUSINESS", "Business"), "first": ("FIRST", "First class")}
ASK = {"stops": "Direct only, or connections allowed?", "cabin": "Cabin: economy, premium, business or first?"}
PAGE_KEYS = ("type", "origin", "destination", "day", "adults", "children", "cabin", "currency", "sort", "stops", "airlines", "dep_hours", "max_hours", "checked_bag")      # what the script checks in the page's own address


def booking_flights_recipe(origin: str, destination: str, day: date, adults: int = 2, direct_only: bool = False, cabin: str = "economy", pages: int = DEFAULT_PAGES, children_ages: list[int] | None = None, airlines: list[str] | None = None, departure_hours: str | None = None, max_hours: float | None = None,
                           checked_bag: bool = False, details: int = 5) -> dict[str, Any]:
    origin, destination = origin.strip().upper(), destination.strip().upper()
    if not (re.fullmatch(r"[A-Z]{3}", origin) and re.fullmatch(r"[A-Z]{3}", destination)) or origin == destination:
        raise ValueError("origin and destination must be two different 3-letter AIRPORT codes (TLV, LIS)")
    ages = list(children_ages or [])
    if cabin not in CABINS or not 1 <= adults <= 8 or not 1 <= pages <= MAX_PAGES or adults + len(ages) > 8 or any(not 0 <= a <= 17 for a in ages):
        raise ValueError(f"cabin must be one of {sorted(CABINS)}, adults 1-8 (adults + children at most 8, children aged 0-17), pages 1-{MAX_PAGES} (15 flights a page, read for Best and for Cheapest)")
    if not 0 <= details <= 10:
        raise ValueError("details is how many of the cheapest flights get their fare details read (0-10)")
    carriers = sorted({a.strip().upper() for a in (airlines or []) if a.strip()})
    if any(not re.fullmatch(r"[A-Z0-9]{2}", a) for a in carriers):
        raise ValueError("airlines are 2-character airline codes such as TP, FR, KL")
    hours = None
    if departure_hours:
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", departure_hours.strip())
        if not m or not 0 <= int(m.group(1)) <= int(m.group(2)) <= 23:
            raise ValueError("departure_hours is a range of hours such as 06-11 (departures from 06:00 to 11:59)")
        hours = f"{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    if max_hours is not None and not 1 <= max_hours <= 48:
        raise ValueError("max_hours is the longest total journey in hours, 1-48")
    max_h = int(-(-max_hours // 1)) if max_hours is not None else None      # the site's own filter takes whole hours (rounded up: the exact limit is judged here)
    code, cabin_name = CABINS[cabin]
    expect = {"type": "ONEWAY", "origin": origin, "destination": destination, "day": day.isoformat(), "adults": adults, "children": len(ages), "ages": ages, "cabin": code, "currency": "EUR", "sort": "BEST",
              "stops": "0" if direct_only else None, "direct_only": direct_only, "cabin_name": cabin_name, "pages": pages, "leg": f"{origin} to {destination}, {day:%d %b %Y}", "airlines": carriers, "dep_hours": hours,
              "max_hours": max_h, "max_hours_wish": max_hours, "checked_bag": bool(checked_bag)}
    url = (f"https://flights.booking.com/flights/{origin}.AIRPORT-{destination}.AIRPORT/?type=ONEWAY&adults={adults}" + (f"&children={','.join(str(a) for a in ages)}" if ages else "") + f"&cabinClass={code}&from={origin}.AIRPORT&to={destination}.AIRPORT"
           f"&depart={day.isoformat()}&sort=BEST&currency=EUR" + ("&stops=0" if direct_only else "") + (f"&airlines={','.join(carriers)}" if carriers else "") + (f"&depTimeInt={hours}" if hours else "") + (f"&duration={max_h}" if max_h else "") + ("&includedBaggage=CHECKIN" if checked_bag else ""))
    request = {"origin": origin, "destination": destination, "day": day.isoformat(), "adults": adults, "children_ages": ages, "cabin": code, "currency": "EUR", "stops": 0 if direct_only else None, "pages": pages, "airlines": carriers, "dep_hours": hours, "max_hours": max_h, "checked_bag": bool(checked_bag), "details": details,
               "sorts": [{"key": key, "label": label} for key, label in (("BEST", "Best"), ("CHEAPEST", "Cheapest"))]}
    script = with_emit((HERE / "booking_flights.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps(request))
    return {"url": url, "script": script, "expect": expect}


def _bag_text(r: dict[str, Any]) -> tuple[str, str]:
    """(cabin baggage, checked baggage) as the offer's own `includedProducts` says; a checked bag that is not included may be offered as an extra (not priced in the list)."""
    cabin = []
    if r.get("personal_item"):
        cabin.append("personal item")
    if r.get("hand"):
        h = r["hand"]
        cabin.append("hand bag" + (f" up to {h['kg']:g} kg" if h.get("kg") else "") + (f", {h['per_pax']} per traveller" if h.get("per_pax") else ""))
    checked = r.get("checked")
    checked_text = (f"yes: {checked.get('per_pax') or 1} bag(s) per traveller" + (f" up to {checked['kg']:g} kg" if checked.get("kg") else "")) if checked else ("no" + ("; a checked bag is offered as a paid extra (price not in the list)" if "checkedInBaggage" in (r.get("extras") or []) else ""))
    return (", ".join(cabin) or "no cabin bag listed"), checked_text


FEATURE_TEXT = {"PERSONAL_BAGGAGE": "personal item", "CABIN_BAGGAGE": "cabin bag", "CHECK_BAGGAGE": "checked bag", "REFUNDABLE_TICKET": "refundable", "CHANGEABLE_TICKET": "changeable", "PREMIUM_SEAT": "premium seat", "FAST_TRACK": "fast track",
                "PRIORITY_CHECK_IN": "priority check-in"}


def _fare_text(d: dict[str, Any]) -> tuple[str, str, str | None, bool | None]:
    """(fare, refund and change terms, the whole fare ladder, refundable?) from the offer's own details (GET /api/flight/<token>, read live 5 Nov 2026)."""
    change, cancel = d.get("change"), d.get("cancel")
    terms = "; ".join((("change before departure allowed (a fee may apply)" if change else ("no change allowed" if change is False else "change not stated")),
                       ("cancel before departure allowed" if cancel else ("no refund if you cancel" if cancel is False else "cancel not stated")))) + f" (Booking.com's own fare rules, fare {d.get('fare') or 'not named'})"
    included = [FEATURE_TEXT.get(f["n"], str(f["n"]).replace("_", " ").lower()) for f in d.get("features") or [] if f.get("a") == "INCLUDED"]
    fare = f"{d.get('fare') or 'fare not named'}: " + (", ".join(included) if included else "no extras listed")
    def positives(o: dict[str, Any]) -> str:      # only what the fare option itself lists: its feature list is less complete than the flight's own rules, so a missing entry is never read as "no"
        got = [t for t, on in (("checked bag", o.get("checked_bag")), ("refundable", o.get("refundable")), ("changeable", o.get("changeable")), ("premium seat", o.get("seat")), ("fast track", o.get("fast_track"))) if on]
        return f" ({', '.join(got)})" if got else ""
    ladder = " / ".join(f"{o['name']} {o['total']:g} EUR{positives(o)}" for o in d.get("options") or [] if o.get("name") and o.get("total") is not None) or None
    refundable = True if cancel else (False if cancel is False else (True if any(f["n"] == "REFUNDABLE_TICKET" and f.get("a") == "INCLUDED" for f in d.get("features") or []) else None))
    return fare, terms, ladder, refundable


def _hm(stamp: str | None) -> str:
    return (stamp or "")[11:16] or "?"


def _dur(mins: int | None) -> str:
    return f"{mins // 60}h {mins % 60:02d}" if isinstance(mins, int) else "duration not shown"


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Booking.com result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Booking.com script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    searched = data.get("searched") or {}
    for k in PAGE_KEYS:
        if k != "sort" and k in exp and searched.get(k) != exp[k]:
            problems.append(f"the request searched {k} {searched.get(k)} instead of {exp[k]}: run the script again")
    sorts = {s.get("sort"): s for s in data.get("sorts") or []}
    if exp and not {"Best", "Cheapest"} <= set(sorts):
        problems.append("both the Best and the Cheapest sorts must be read: run the script again")
    for name, s in sorts.items():
        if not s.get("pages_read"):
            problems.append(f"no page of the {name} sort was read ({'; '.join(data.get('failed') or []) or 'no reason given'}): run the script again")
    if exp and data.get("cabin_back") and data["cabin_back"] != exp.get("cabin"):
        problems.append(f"Booking.com answered for the cabin {data['cabin_back']}, not {exp.get('cabin')}: run the script again")
    pax = (exp.get("adults") or 0) + (exp.get("children") or 0)
    merged: dict[tuple, dict[str, Any]] = {}
    for r in data.get("rows", []):
        legs = r.get("legs") or []
        if len(legs) != 1:
            problems.append(f"a Booking.com flight has {len(legs)} legs, not one: this recipe reads one way only; run the script again")
            continue
        if r.get("cur") != "EUR":
            problems.append(f"a Booking.com price is in '{r.get('cur')}', not euro: run the script again (the request asks currency=EUR)")
            continue
        if pax and len(r.get("trav") or []) != pax:
            problems.append(f"a Booking.com price is for {len(r.get('trav') or [])} traveller(s), not {pax}: run the script again")
            continue
        leg = legs[0]
        key = (tuple(leg.get("flights") or []), leg.get("dep"), leg.get("arr"), r.get("total"))
        if key in merged:      # the same flight in the Best list and in the Cheapest list is one row with both labels
            if r.get("sort") not in merged[key]["tabs"]:
                merged[key]["tabs"].append(r.get("sort"))
            continue
        merged[key] = {"row": r, "leg": leg, "tabs": [r.get("sort")]}
    offers: list[Offer] = []
    for item in merged.values():
        r, leg = item["row"], item["leg"]
        direct = leg.get("stops") == 0
        arrives = f" (arrives {leg['arr'][8:10]}/{leg['arr'][5:7]})" if leg.get("arr") and (leg["arr"] or "")[:10] != (leg.get("dep") or "")[:10] else ""
        numbers = " + ".join(leg.get("flights") or []) or "flight number not shown"
        name = f"{r.get('carriers') or 'airline not shown'} {numbers} {_hm(leg.get('dep'))}-{_hm(leg.get('arr'))}{arrives} ({_dur(leg.get('mins'))})"
        cabin_bag, checked_bag = _bag_text(r)
        det = r.get("detail")
        fare_text, terms, ladder, refundable = _fare_text(det) if det else (None, None, None, None)
        trav = r.get("trav") or []
        wrong_cabin = bool(exp.get("cabin")) and bool(leg.get("cabins")) and exp["cabin"] not in leg["cabins"]
        codes = {f[:2] for f in leg.get("flights") or []} | set(leg.get("ops") or [])
        hour = int(leg["dep"][11:13]) if (leg.get("dep") or "")[11:13].isdigit() else None
        lo_hi = [int(x) for x in exp["dep_hours"].split("-")] if exp.get("dep_hours") else None
        conds = [direct or not exp.get("direct_only"), not wrong_cabin,
                 not exp.get("airlines") or (bool(codes) and codes <= set(exp["airlines"])),
                 not lo_hi or (hour is not None and lo_hi[0] <= hour <= lo_hi[1]),
                 exp.get("max_hours_wish") is None or (leg.get("mins") is not None and leg["mins"] <= exp["max_hours_wish"] * 60),
                 not exp.get("checked_bag") or bool(r.get("checked"))]
        saved = (r["list_total"] - r["total"]) if r.get("list_total") and r.get("total") and r["list_total"] > r["total"] else None
        offers.append(Offer(
            group=exp.get("leg") or group, source=SOURCE, name=name, price_total=r.get("total"), currency="EUR",
            price_basis=(f"whole group ({pax} travellers), the total Booking.com's flights service gives" if pax else "whole group, the total Booking.com's flights service gives")
            + (f"; list price {r['list_total']:g} EUR, Booking.com's discount {saved:g} EUR" if saved else "") + "; the airline's own page has the price to quote",
            fits=None if not exp else all(conds),
            flexible=refundable, quotable=False, connecting=not direct, supplier=(r.get("carriers") or "").split(",")[0].strip() or None,
            details={"cabin": " + ".join(c.replace("_", " ").lower() for c in leg.get("cabins") or []) or "not shown", "stops": "Direct" if direct else f"{leg.get('stops')} stop(s)" + (f" via {', '.join(leg['via'])}" if leg.get("via") else "") + (f", {leg['tech_stops']} technical stop(s)" if leg.get("tech_stops") else ""),
                     "fare": fare_text or ("flexible ticket offered as a paid extra (price not in the list)" if r.get("flexible_upgrade") else "fare name not read for this flight (only the cheapest flights' details are read)"),
                     "cabin_bag": cabin_bag, "checked_bag": checked_bag, "refund_change": terms or "not read for this flight (only the cheapest flights' details are read)", "fare_options": ladder,
                     "per_person": " / ".join(f"{t.get('type') or 'traveller'} {t['total']:g} EUR" for t in trav if t.get("total") is not None) or "not shown",
                     "price_parts": (f"base fare {r['base']:g} EUR, taxes {r['tax']:g} EUR" + (f", fees {r['fee']:g} EUR" if r.get("fee") else "")) if r.get("base") is not None and r.get("tax") is not None else "not shown",
                     "operated_by": ", ".join(leg.get("ops") or []) or "not shown", "from_tab": " and ".join(item["tabs"])}))
    n = len(offers)
    seen = ", ".join(f"{name} {s.get('pages_read')} of {s.get('pages_seen')} page(s)" for name, s in sorts.items())
    notes = ["Booking.com only compares: the price to quote comes from the airline's own page. Best and Cheapest were read together; a flight in both lists is one row (column from tab).",
             f"Pages read: {seen}" + (f" (the site lists {PER_PAGE} flights a page)." if any((s.get("pages_seen") or 1) > 1 for s in sorts.values()) else ".")]
    if data.get("results_total"):
        notes.append(f"Booking.com says it found {data['results_total']} flight options for this search; only the first pages of each sort were read, so a flight further down was not seen.")
    if data.get("failed"):
        notes.append("Not every page asked for was read: " + "; ".join(str(x) for x in data["failed"]) + ".")
    if data.get("no_direct_notice") and exp.get("direct_only"):
        notes.append("Booking.com has no direct flight for this search (it ignored its own direct-only filter and lists other options): none of these rows meets the direct-only wish.")
    elif exp.get("direct_only"):
        notes.append("Booking.com's own direct-only filter (stops=0) was sent in the request.")
    if data.get("details_read"):
        notes.append(f"The fare details (fare name, refund and change rules, the fare's features and every fare option of the flight with its price) were read for the {data['details_read']} cheapest flight(s) from Booking.com's own flight-details service; the other rows say 'not read'.")
    if data.get("details_failed"):
        notes.append("Some fare details could not be read: " + "; ".join(str(x) for x in data["details_failed"]) + ".")
    sent = [x for x in (f"airlines {', '.join(exp['airlines'])}" if exp.get("airlines") else None, f"departures {exp['dep_hours'].replace('-', ':00 to ')}:59" if exp.get("dep_hours") else None,
                        f"at most {exp['max_hours']} hours (whole hours: the exact limit {exp['max_hours_wish']:g} h is judged here)" if exp.get("max_hours") else None, "a checked bag included" if exp.get("checked_bag") else None) if x]
    if sent:
        notes.append("Booking.com's own filters were sent with the request: " + "; ".join(sent) + ". The server also judges each flight itself.")
    if exp.get("children"):
        notes.append(f"The {exp['children']} child(ren) (ages {', '.join(str(a) for a in exp.get('ages') or [])}) were sent to Booking.com, which prices each traveller (see per person).")
    return SiteRows(offers=offers, read=n, total=max(data.get("results_total") or 0, n), problems=problems, sorted_by_price=("Cheapest" in sorts and bool(sorts["Cheapest"].get("pages_read"))), extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="booking_flights_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def booking_flights_recipe_tool(origin: str, destination: str, day: date, adults: int = 2, children_ages: list[int] | None = None, direct_only: bool | None = None, cabin: str | None = None,
                                          operator_answered: bool = False, pages: int = DEFAULT_PAGES, airlines: list[str] | None = None, departure_hours: str | None = None, max_hours: float | None = None,
                                          checked_bag: bool | None = None) -> dict[str, Any]:
        """FOR BOOKING.COM FLIGHTS (COMPARISON ONLY; one leg, one way). ASK FIRST: without
        `direct_only` (true/false) and `cabin` ('economy' / 'premium' / 'business' / 'first') it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers
        (`operator_answered`=true for "no preference", only after the operator replied). Then it returns the results url (the filters are in it)
        and a read-only SCRIPT: open the url, run the script with the javascript tool. The script asks Booking.com's own flights service for the first `pages` pages (15 flights each, default 2, at most 5) of the Best sort and of the
        Cheapest sort (read together, the agency's rule), with price breakdown, baggage and flight numbers, sends its answer to the server by itself: then call compose_answer with `runs`=[its `ingest` id] and the returned `wishes`; never type or pass a row. `origin` / `destination` are 3-letter AIRPORT
        codes. `children_ages` are priced too; optional wishes: `airlines` (codes), `departure_hours` ('06-11'), `max_hours`, `checked_bag`. Booking.com rows are comparison only: the price to quote comes from the airline's page. A human check (captcha) is never worked
        around: stop and tell the operator. One call per leg. The server reads it first in its own Chrome (a short receipt with an `ingest` id: only compose_answer with `runs`=[that id]); if `server_read` says it could not, read the url in Claude in Chrome as above. Never retry the server's read."""
        missing = [q for q, given in ((ASK["stops"], direct_only is not None), (ASK["cabin"], cabin is not None)) if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the airports and the travellers only if the request did not say them), "
                            "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        try:
            out = booking_flights_recipe(origin, destination, day, adults, bool(direct_only), cabin or "economy", pages, children_ages, airlines, departure_hours, max_hours, bool(checked_bag))
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        out["wishes"] = {"expect": out["expect"]}
        out["filters_used"] = [("Direct flights only (operator; the site's own stops filter)" if direct_only else "Connections allowed (" + ("operator" if direct_only is not None else "default: no preference") + ")"),
                               f"{out['expect']['cabin_name']} cabin (" + ("operator" if cabin else "default") + ")", "Best and Cheapest sorts read together (agency rule)", "Prices in EUR (server default)"]
        ex = out["expect"]
        out["filters_used"] += ([f"Airlines {', '.join(ex['airlines'])} only (operator)"] if ex["airlines"] else []) + ([f"Departures {ex['dep_hours']} o'clock (operator)"] if ex["dep_hours"] else []) + \
            ([f"At most {max_hours:g} hours (operator)"] if max_hours else []) + (["A checked bag included (operator)"] if checked_bag else [])
        return await server_first(NAME, "BOOKING_FLIGHTS_READ_IN_SERVER", "https://flights.booking.com", out)
