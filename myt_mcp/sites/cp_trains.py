"""CP (Comboios de Portugal): train prices for ONE leg (a site module, see myt_mcp/sites/__init__.py), read in a browser from CP's own journeys service.

Site rules (found on the real pages 23 Oct 2026; the service read and compared with the page 5 Nov 2026):
* The page https://www.cp.pt/en/resultado-pesquisa?passageiros=<n>&selectedClass=<1|2>&startDate=<yyyy-mm-dd>&departureStation=94-<id>&arrivalStation=94-<id> gets its trains with ONE request:
  POST api-gateway.cp.pt/cp/services/travel-api/journeys (body: departureStationCode, arrivalStationCode, travelDate, classes [1|2], quantities [{quantity: n, type: 1}], services [train types], timeLimit, saleableOnly).
  Its keys (`travelApiKey`, `xcck`, `xccs`) are in the page's own public /fe-config.json, so the script needs no results page, no cards and no request capture: any cp.pt page will do (770 ms for 20 trains).
  The stations are GET .../travel-api/stations (460 stations: code and name; kept in cp_stations.json). The old note that this API "answers 401 without the site's token" was true only without these keys.
* A trip has the times, the duration, `transferCount` (changes), `travelSections` (the train number and service of each part), `saleableOnline` and `basePrices`: per class, priceType 1 = adult normal fare and 4 = promo fare (per person),
  100 and 104 = the same for the WHOLE group of the search (3 passengers = 3 x). The promo carries the restriction (NON_REFUNDABLE); the normal fare lists none. The page card shows the promo group price (104) when there is a
  promo, else the normal group price (100): 14 of 14 cards agreed, with the duration. Filters: `services` (IC, AP...) and `classes` work in the API; the time window and the ticket type are client-side and are judged here.
* A date CP does not sell yet answers 200 with no trips (a past date too). CP sells tickets only some weeks ahead.
* TIME FILTER (the page's Filters screen sends it): `timeLimit {startTime, endTime, limitType}`: 0 = no limit (the page's own list: 20 trains), 1 = arrivals between start and end, 2 = departures between start and end, 3 = departures from start (end ignored).
  Checked on 4 routes x 2 days (Porto Campanha - Lisboa Oriente, Lisboa Rossio - Sintra, Faro - Lisboa Oriente, Lisboa Santa Apolonia - Coimbra-B): window 2 returned departures inside the window every time, window 1 arrivals inside it, window 3
  departures from the start. A departure window sometimes adds connections the plain list lacks (1 in 4 of those cases, e.g. 12:39>16:48 on Lisboa Oriente - Porto Campanha) and they ALWAYS had changes: the plain list holds every direct
  train. So with a time wish the script sends both and joins them.
* REFUND TERMS are nowhere in the search or in the page's "See detail" panel (stops, duration, bicycle, wheelchair, the two prices); they come after Select, which is never pressed. The flags `bike` and `mobility` (wheelchair) are read.
* RETURN TRIP: `returnDate` fills `returnTrip` (the way back, 22 trains Porto Campanha - Lisboa Oriente, with its own prices: a leg is priced alone, no round-trip fare) and `returnTimeLimit` is its time window. The service does NOT
  check that the return is after the outward (a return before it, or on the same day, still answers), so this module does. One call now gives both legs.
* TRAIN TYPES: `services` takes CP's codes U (urban), R (regional), IC (intercidades), AP (alfa pendular), IN (internacionais), alone or together (IC + AP = 18 = 7 + 11 trains). It keeps only trains made of those services
  alone (a connection "IC|R|U" is dropped). The page's Filters screen names International "INT" but the trains carry `IN` (Porto Campanha - Vigo-Guixar, train 421): `INT` is an unknown code and CP then ignores the filter and returns every train,
  so only IN is sent. Every type is also judged here.
* CHILDREN: the page itself sends every passenger as `type: 1` (an adult). Passenger types 2-8 were tried: each returns the ADULT fare and no group price, so CP's search cannot show a child fare; children's and other discounts are read nowhere in it.
* `GET .../travel-api/rules` (CP's own settings): calendar_limit 60 (days ahead the calendar shows), max_tickets_qty 9, min_tickets_qty 1, dep_after_arr_limit 15 (minutes between a return's legs).
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer, mark_unconfirmed
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, server_first, with_emit

NAME = "cp_trains"
SOURCE = "CP (Comboios de Portugal)"
GROUP = "Trains"
NEEDS_WIDE_WINDOW = False
HERE = Path(__file__).parent
ALIASES = {"lisbon oriente": "94-31039", "oriente": "94-31039", "lisbon santa apolonia": "94-30007", "santa apolonia": "94-30007", "lisbon rossio": "94-59006", "rossio": "94-59006", "coimbra": "94-36004", "coimbra b": "94-36004",
           "porto": "94-2006", "porto campanha": "94-2006", "porto sao bento": "94-1008", "sao bento": "94-1008", "lisbon": "94-31039", "lisboa": "94-31039"}      # the names a request uses for CP's stations (ids as CP gives them); anything else is found in cp_stations.json
CODE = re.compile(r"(94|71)-\d{1,6}")
TRAIN_TYPES = {"urban": "U", "urbano": "U", "suburban": "U", "regional": "R", "intercidades": "IC", "intercity": "IC", "inter city": "IC", "alfa pendular": "AP", "alfa": "AP", "pendular": "AP", "international": "IN", "internacional": "IN", "internacionais": "IN",
               "u": "U", "r": "R", "ic": "IC", "ap": "AP", "in": "IN", "int": "IN"}      # what an operator says -> CP's own service codes (the page's Filters screen: urbano U, regional R, intercidades IC, alfaPendular AP, internacional INT)
SERVICE_NAMES = {"U": "Urban", "R": "Regional", "IC": "Intercidades", "AP": "Alfa Pendular", "IN": "International"}
API_FILTERED = {"U", "R", "IC", "AP", "IN"}      # the service's own filter works for all five (read live 5 Nov 2026: U on Lisboa Rossio - Sintra 60 of 60, IN on Porto Campanha - Vigo 2 of 2 and 0 on routes with none); an unknown code such as INT is ignored (all trains came back)
ASK = {"class": "Class: 2nd (tourist) or 1st?", "time": "Departure time: the earliest and/or the latest (for 'in the morning' the latest is 12:00), or any time?", "refundable": "Refundable tickets only (CP's promo fares are non-refundable), or any fare?",
       "direct": "Direct trains only, or is a change fine?"}
RESULTS = "https://www.cp.pt/en/resultado-pesquisa"


def _key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


@lru_cache(maxsize=1)
def _stored_stations() -> list[tuple[str, str]]:
    data = json.loads((HERE / "cp_stations.json").read_text(encoding="utf-8"))
    return [(c, n) for c, n in data["stations"]]


_LIVE: list[tuple[str, str]] | None = None          # CP's own list read by the server's browser when a name was not in the stored one (kept until the server restarts)
_LAST_REFRESH = 0.0
REFRESH_EVERY = 3600.0
LIVE_STATIONS_JS = """async () => { const cfg = await (await fetch('/fe-config.json')).json();
  const r = await fetch(cfg.travelApiUrl + '/stations', {headers: {'Accept': 'application/json', 'X-Api-Key': cfg.travelApiKey, 'x-cp-connect-id': cfg.xcck, 'x-cp-connect-secret': cfg.xccs}});
  const j = await r.json(); return JSON.stringify(j.map((s) => [s.code, s.designation])); }"""


def station_list() -> list[tuple[str, str]]:
    return _LIVE if _LIVE else _stored_stations()


async def refresh_stations() -> bool:
    """Read CP's current station list in the server's own browser (at most once an hour) and use it when it looks right (at least 300 stations, every code CP's own form): a station CP added after 5 Nov 2026 is then found by name."""
    global _LIVE, _LAST_REFRESH
    import time
    if time.monotonic() - _LAST_REFRESH < REFRESH_EVERY and _LAST_REFRESH:
        return False
    _LAST_REFRESH = time.monotonic()
    from myt_mcp.sites import server_eval
    raw = await server_eval("https://www.cp.pt", "https://www.cp.pt/en", LIVE_STATIONS_JS)
    try:
        rows = [(str(c), str(n)) for c, n in json.loads(raw or "[]")]
    except (TypeError, ValueError):
        return False
    if len(rows) < 300 or not all(CODE.fullmatch(c) for c, _ in rows):
        return False
    _LIVE = sorted(rows, key=lambda r: r[1].lower())
    return True


def station_matches(name: str) -> list[tuple[str, str]]:
    """CP's stations a name can mean: its own id as given; an alias; the exact name; else the stations whose name starts with it, then those that contain it (best first)."""
    text = (name or "").strip()
    if CODE.fullmatch(text):
        return [(text, next((n for c, n in station_list() if c == text), text))]
    key = _key(text)
    if not key:
        return []
    names = station_list()
    if key in ALIASES:
        code = ALIASES[key]
        return [(code, next((n for c, n in names if c == code), code))]
    exact = [(c, n) for c, n in names if _key(n) == key]
    if exact:
        return exact
    starts = [(c, n) for c, n in names if _key(n).startswith(key)]
    if starts:
        return starts
    return [(c, n) for c, n in names if key in _key(n)]


def station_id(name: str) -> str | None:
    """The one station a name means (its id as given, an alias, an exact name or the only match); None when it means none or several (the recipe then returns the candidates)."""
    found = station_matches(name)
    return found[0][0] if len(found) == 1 else None


def train_codes(types: list[str] | None) -> list[str]:
    codes: list[str] = []
    for name in types or []:
        code = TRAIN_TYPES.get(_key(name))
        if not code:
            raise ValueError(f"train type '{name}' is not one of: urban, regional, intercidades, alfa pendular, international")
        if code not in codes:
            codes.append(code)
    return codes


def cp_trains_recipe(origin: str, destination: str, day: date, passengers: int = 2, first_class: bool = False, earliest: str | None = None, refundable: bool = False, direct_only: bool = False,
                     latest: str | None = None, return_day: date | None = None, train_types: list[str] | None = None, back_earliest: str | None = None, back_latest: str | None = None) -> dict[str, Any]:
    if not 1 <= passengers <= 9:
        raise ValueError("passengers must be 1-9 (everybody who needs a ticket)")
    for label, value in (("earliest", earliest), ("latest", latest), ("back_earliest", back_earliest), ("back_latest", back_latest)):
        if value is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError(f"{label} must be a time such as 08:00")
    if return_day is not None and return_day < day:
        raise ValueError("the return day must be the same day or after the outward day")
    if (back_earliest or back_latest) and return_day is None:
        raise ValueError("back_earliest / back_latest need a return day")
    types = train_codes(train_types)
    a, b = station_id(origin), station_id(destination)
    if not a or not b:
        missing = [n for n, i in ((origin, a), (destination, b)) if not i]
        return {"needs_station_ids": missing, "station_candidates": {n: [f"{nm} ({c})" for c, nm in station_matches(n)[:8]] for n in missing},
                "steps": ["Ask the operator which CP station they mean (the candidates are listed; an empty list means CP has no station with that name), then call this tool again with the station's name or its id (such as 94-30007) as the station."]}
    url = f"{RESULTS}?passageiros={passengers}&selectedClass={1 if first_class else 2}&startDate={day.isoformat()}&departureStation={a}&arrivalStation={b}"
    expect = {"origin": origin, "destination": destination, "origin_code": a, "destination_code": b, "day": day.isoformat(), "passengers": passengers, "class": "1st" if first_class else "2nd", "earliest": earliest, "latest": latest,
              "refundable": refundable, "direct_only": direct_only, "leg": f"{origin} to {destination}, {day:%d %b %Y}", "return_day": return_day.isoformat() if return_day else None,
              "back_leg": f"{destination} to {origin}, {return_day:%d %b %Y}" if return_day else None, "back_earliest": back_earliest, "back_latest": back_latest, "train_types": types}
    request = {"origin_code": a, "destination_code": b, "day": day.isoformat(), "passengers": passengers, "first_class": first_class, "window": {"earliest": earliest, "latest": latest} if earliest or latest else None,
               "return_day": return_day.isoformat() if return_day else None, "back_window": {"earliest": back_earliest, "latest": back_latest} if back_earliest or back_latest else None, "services": [c for c in types if c in API_FILTERED]}
    return {"url": url, "script": with_emit((HERE / "cp_trains.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps(request)), "expect": expect}


def _minutes(text: str | None) -> int | None:
    m = re.match(r"^\s*(\d+)\s*h\s*(\d+)?", text or "")
    return int(m.group(1)) * 60 + int(m.group(2) or 0) if m else None


def _hhmm(text: str | None) -> str | None:
    m = re.match(r"^(\d{1,2}):(\d{2})$", (text or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


LIMIT_TEXT = {"NON_REFUNDABLE": "non refundable"}


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the CP result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the CP script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    notes: list[str] = []
    rows = data.get("rows", [])
    if data.get("no_results") and not rows:
        limit = data.get("calendar_limit_days")
        ahead = (date.fromisoformat(exp["day"]) - date.today()).days if exp.get("day") else None
        why = (f"CP sells tickets {limit} days ahead (its own rule) and this date is {ahead} days away" if limit and ahead is not None and ahead > limit else "CP sells tickets only some weeks ahead (or the stations have no train that day)")
        return SiteRows(problems=[f"CP shows no trains for this day: {why}. Put CP in not_checked with the reason 'not available: CP has no trains on sale for this date' and tell the operator to check cp.pt again closer to the date; never invent a price."])
    if exp:
        if exp.get("day") and data.get("day") and data["day"] != exp["day"]:
            problems.append(f"the service answered for {data['day']}, not {exp['day']}: run the script again")
        for key, label in (("origin_code", "from"), ("destination_code", "to")):
            got = (data.get("origin" if key == "origin_code" else "destination") or {}).get("code")
            if exp.get(key) and got and got != exp[key]:
                problems.append(f"the service answered {label} '{got}', not '{exp[key]}': run the script again")
        if (exp.get("return_day") or None) != (data.get("return_day") or None):
            problems.append(f"the service was asked for return day {data.get('return_day')}, not {exp.get('return_day')}: run the script again")
        if exp.get("passengers") and data.get("passengers") and int(data["passengers"]) != exp["passengers"]:
            problems.append(f"the service was asked for {data['passengers']} passenger(s), not {exp['passengers']}: run the script again")
        want_cls = {"1st": 1, "2nd": 2}.get(exp.get("class") or "")
        if want_cls and data.get("cls") and int(data["cls"]) != want_cls:
            problems.append(f"the service was asked for class {data['cls']}, not the {exp['class']} class: run the script again")
    offers: list[Offer] = []
    pax = (data.get("passengers") or exp.get("passengers") or "?")
    cls_name = "1st class" if str(data.get("cls") or "") == "1" else "2nd class / tourist"
    wanted_codes = [c for c in (exp.get("train_types") or []) if c]
    legs: list[tuple[str, int | None, int | None]] = []          # (leg, departure minute, arrival minute of the day; an arrival after midnight is past 1440) of each offer, in order
    for r in rows:
        promo, normal = r.get("price_promo"), r.get("price_normal")
        unpriced = promo is None and normal is None          # CP lists the train but gives no price and does not sell it online (the Celta trains Porto - Vigo: no basePrices, saleableOnline false)
        back = r.get("leg") == "back"
        earliest, latest = (exp.get("back_earliest"), exp.get("back_latest")) if back else (exp.get("earliest"), exp.get("latest"))
        dep, arr = _hhmm(r.get("dep")), _hhmm(r.get("arr"))
        limits = [LIMIT_TEXT.get(x, str(x).replace("_", " ").lower()) for x in (r.get("promo_limits") or [])]
        non_refundable = promo is not None and any("non refundable" in x for x in limits)
        full_fare = bool(exp.get("refundable")) and promo is not None and normal is not None      # refundable wanted: the full fare (CP lists no non-refundable restriction on it), not the promo
        price = None if unpriced else (normal if full_fare or promo is None else promo)
        fits: bool | None = True if exp else None
        if earliest and dep:
            fits = bool(fits) and dep >= earliest
        if latest:          # 'in the morning' = leaving by 12:00: a row whose departure is not shown cannot show that it fits
            fits = bool(fits) and bool(dep) and dep <= latest
        if wanted_codes:          # every part of the train is one of the wanted types (CP's own filter does the same, and it ignores INT)
            codes = [c for c in (r.get("codes") or []) if c]
            fits = bool(fits) and bool(codes) and all(c in wanted_codes for c in codes)
        if exp.get("refundable") and non_refundable and not full_fare:
            fits = False
        n = r.get("changes_n")
        services = [x for x in (r.get("services") or []) if x]
        changes = None
        if n is not None:
            changes = f"{int(n)} change{'s' if int(n) != 1 else ''}: {' + '.join(services) or 'services not shown'}" if int(n) else "direct (CP lists no change)"
            if int(n) and exp.get("direct_only"):
                fits = False
        if exp.get("direct_only") and n is None:
            fits = False        # CP's answer did not say: never assumed direct
        saleable = r.get("saleable")
        label = f"{' + '.join(services) or 'train'} {dep}-{arr} ({(r.get('dur') or '').replace('h', 'h ')})"
        if unpriced:
            conditions = "not sold online by CP: its search gives no price (timetable only); ask CP"
        elif full_fare:
            conditions = "full fare: CP lists no non-refundable restriction on it (the refund terms and fees are on cp.pt: open See detail)"
        elif promo is not None:
            conditions = f"promo ticket: {', '.join(limits) if limits else 'no restriction listed'}" + (f"; the fare without promotion is {normal:g} EUR" if normal is not None else "")
        else:
            conditions = "full fare: CP lists no non-refundable restriction on it (the refund terms and fees are on cp.pt: open See detail)"
        o = Offer(
            group=(exp.get("back_leg") if back else exp.get("leg")) or group, source=SOURCE, name=label, price_total=None if unpriced else float(price), currency=None if unpriced else "EUR",
            price_basis="no price in CP's search: not sold online" if unpriced else f"whole group ({pax} adults), CP's own price" + ("; full fare (the promo fare is " + f"{promo:g} EUR, {', '.join(limits) or 'restricted'})" if full_fare else (f"; promo, without promotion {normal:g} EUR" if promo is not None and normal is not None else "")),
            fits=fits, quotable=not unpriced, flexible=False if non_refundable and not full_fare else None, supplier="CP - Comboios de Portugal",
            details={"class_fare": cls_name + (" (promo)" if promo is not None and not full_fare else ""), "changes": changes or "not shown (open See detail)", "seats_left": "not shown on the list",
                     "conditions": conditions + ("" if saleable is not False else "; NOT sold online (CP's own flag): ask CP"), "per_person": (r.get("pp_normal") if (full_fare or promo is None) else r.get("pp_promo")),
                     "trains": ", ".join(str(x) for x in (r.get("trains") or [])) or None,
                     "bicycle_wheelchair": ("bicycle " + ("yes" if r.get("bike") else "no") + ", wheelchair " + ("yes" if r.get("mobility") else "no")) if r.get("bike") is not None or r.get("mobility") is not None else None})
        d_min = int(dep[:2]) * 60 + int(dep[3:]) if dep else None
        a_min = (int(arr[:2]) * 60 + int(arr[3:]) + (1440 if d_min is not None and arr < dep else 0)) if arr else None
        legs.append(("back" if back else "out", d_min, a_min))
        if unpriced:
            mark_unconfirmed(o, "price")
        if full_fare:
            mark_unconfirmed(o, "refund terms")      # the fare lists no restriction, but its refund rules are not read: never a pick on a refundable wish
        offers.append(o)
    if exp.get("return_day") and exp["return_day"] == exp.get("day") and len(legs) == len(offers):          # same day: a return train must leave at least CP's own waiting time after the earliest outward train that meets the wishes arrives
        wait = int(data.get("min_wait_minutes") or 15)
        arrivals = [a for (leg, d, a), o in zip(legs, offers) if leg == "out" and a is not None and o.fits is not False]
        earliest_arrival = min(arrivals) if arrivals else None
        for (leg, d, a), o in zip(legs, offers):
            if leg != "back" or d is None or o.fits is False:
                continue
            if earliest_arrival is None or d < earliest_arrival + wait:
                o.fits = False
                reason = "no outward train that meets the wishes arrives early enough" if earliest_arrival is None else f"it leaves before you can be back: the earliest outward train arrives {earliest_arrival // 60 % 24:02d}:{earliest_arrival % 60:02d} and CP's rule is {wait} minutes"
                o.details["conditions"] = f"{o.details.get('conditions')}; NOT a fit for a same-day return: {reason}"
    notes.append("CP's search prices every passenger at the ADULT fare (checked: every other passenger type returns the adult price), so children's and other discounts cannot be shown here: ask the operator, and say the real fare may be lower.")
    notes.append(f"CP sells tickets {data.get('calendar_limit_days') or 'only some weeks'} days ahead (its own rule): a later date shows no trains." if data.get("calendar_limit_days") else "CP sells tickets only some weeks ahead: a later date shows no trains.")
    if data.get("window_sent"):
        w = data["window_sent"]
        notes.append(f"CP's own time filter was also asked (departures {w.get('startTime')}-{w.get('endTime')}): it added {data.get('window_extra') or 0} train(s) the plain list did not have; the server still judges every departure time itself.")
    if exp.get("refundable") and any(o.price_basis.find("full fare") >= 0 for o in offers):
        notes.append("Refundable only was asked: where CP has a promo fare (non-refundable) the row shows the full fare instead, which CP lists without a non-refundable restriction; its refund terms are not read, so say they must be checked on cp.pt.")
    if any(o.price_total is None for o in offers):
        notes.append(f"CP lists {sum(1 for o in offers if o.price_total is None)} train(s) with no price: it does not sell them online (for example the international Celta trains Porto - Vigo). They are shown without a price, never a pick: ask CP for the fare.")
    if wanted_codes:
        names = ", ".join(SERVICE_NAMES.get(x, x) for x in wanted_codes)
        notes.append(f"Train types asked: {names}. CP's own filter was used (it keeps only trains made of those types alone: a connection with another type is not listed), and every train is also judged here from its own services. A train of another type does not fit.")
    if exp.get("return_day"):
        for leg_name, key, label in (("outward", "out_total", exp.get("leg")), ("return", "back_total", exp.get("back_leg"))):
            if data.get(key) == 0:
                notes.append(f"CP shows no trains for the {leg_name} leg ({label}): say so for that leg (CP sells tickets {data.get('calendar_limit_days') or 'only some weeks'} days ahead; never invent a price).")
        if exp["return_day"] == exp.get("day"):
            wait = data.get("min_wait_minutes")
            notes.append("Same-day return: CP's search does not check the order of the legs; here a return train that leaves less than " + (f"{wait} minutes" if wait else "CP's waiting time") + " after the earliest fitting outward train arrives is marked not fitting. Pair the chosen trains yourself.")
        notes.append("Each leg is priced alone (CP's search has no round-trip fare); a return is the sum of the two legs.")
    stored = len(station_list())
    if isinstance(data.get("stations_total"), int) and data["stations_total"] != stored:
        notes.append(f"CP now lists {data['stations_total']} stations and the server knows {stored}: a station added since may not be found by name yet (the server refreshes its list when a name is not found).")
    for t in (data.get("notices") or [])[:2]:
        notes.append(f"CP's own notice on this search: {str(t)[:200]}")
    if data.get("window_back_sent"):
        w = data["window_back_sent"]
        notes.append(f"CP's own time filter was also asked for the return (departures {w.get('startTime')}-{w.get('endTime')}).")
    if data.get("trips_total") is not None and len(rows) != data["trips_total"]:
        problems.append("the script's row count does not match its trips: run the script once more")
    return SiteRows(offers=offers, read=len(offers), total=len(offers), problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="cp_trains_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def cp_trains_recipe_tool(origin: str, destination: str, day: date, passengers: int = 2, first_class: bool | None = None, earliest: str | None = None, refundable: bool | None = None, direct_only: bool | None = None,
                                    operator_answered: bool = False, latest: str | None = None, return_day: date | None = None, train_types: list[str] | None = None, back_earliest: str | None = None, back_latest: str | None = None) -> dict[str, Any]:
        """FOR TRAINS IN PORTUGAL (Comboios de Portugal, CP's own prices, read from cp.pt). A return trip is ONE call: `return_day` (its times: `back_earliest`/`back_latest`);
        `train_types` only if asked (alfa pendular, intercidades, regional, urban, international). ASK FIRST: without `first_class` (false = 2nd class), `earliest` and/or `latest` (HH:MM: 'in the morning' = latest="12:00"; both
        out for any time, then `operator_answered`=true), `refundable` (true/false) and `direct_only` (true/false) it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again. `passengers` = everybody who
        needs a ticket (CP prices all as adults). cp.pt stops the operator's Chrome from sending data to the server, so THE SERVER READS CP ITSELF in its automation browser and returns a short receipt with an `ingest` id: call
        compose_answer with `runs`=[that id]; no Chrome action (ok=false: put CP in not_checked with the reason it gives). Otherwise it returns a read-only SCRIPT: run it with the javascript tool; never type a row. A far date shows no trains (the converter says so: not_checked 'not available'). If it answers `needs_station_ids`, ask which of its `station_candidates` they mean.
        A human check is never worked around."""
        asked = [q for q, given in ((ASK["class"], first_class is not None), (ASK["time"], earliest is not None or latest is not None or operator_answered), (ASK["refundable"], refundable is not None), (ASK["direct"], direct_only is not None)) if not given]
        if asked and not operator_answered:
            return {"ok": False, "ask_operator": asked, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the stations and the number of passengers only if the request did not say them), wait for the reply, then call "
                            "this tool again with the answers. For 'any' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        args = (origin, destination, day, passengers, bool(first_class), earliest, bool(refundable), bool(direct_only), latest, return_day, train_types, back_earliest, back_latest)
        out = cp_trains_recipe(*args)
        if "url" not in out and any(not v for v in (out.get("station_candidates") or {}).values()) and await refresh_stations():          # a name nothing matches: CP's own list may have a new station
            out = cp_trains_recipe(*args)
        if "url" not in out:
            return out
        out["wishes"] = {"expect": out["expect"]}
        src = lambda v: "operator" if v is not None else "default: no preference"       # noqa: E731
        out["filters_used"] = [("1st class (operator)" if first_class else f"2nd class ({src(first_class)})"), (f"Departing {'after ' + earliest if earliest else ''}{' and ' if earliest and latest else ''}{'by ' + latest if latest else ''} (operator)" if earliest or latest else "Any departure time (operator: any)"),
                               ("Refundable tickets only (operator)" if refundable else f"Any fare, promo included ({src(refundable)})"),
                               ("Direct trains only (operator; CP lists the changes)" if direct_only else f"Changes allowed ({src(direct_only)})")]
        out["filters_used"] += ([f"Train types: {', '.join(SERVICE_NAMES[c] for c in out['expect']['train_types'])} (operator)"] if out["expect"]["train_types"] else []) + ([f"Return on {return_day:%d %b %Y}" + (f", departing {'after ' + back_earliest if back_earliest else ''}{' and ' if back_earliest and back_latest else ''}{'by ' + back_latest if back_latest else ''}" if back_earliest or back_latest else "") + " (operator)"] if return_day else [])
        # cp.pt's security policy only lets the page talk to CP's own hosts, so the operator's Chrome cannot send the answer to this server: the server reads the page itself; when it cannot, the recipe comes back
        # for the operator's Chrome and its script returns the rows in parts (cp_trains is in NO_POST)
        return await server_first(NAME, "CP_READ_IN_SERVER", "https://www.cp.pt", out)
