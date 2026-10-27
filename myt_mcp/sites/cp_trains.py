"""CP (Comboios de Portugal): train prices for ONE leg (a site module, see myt_mcp/sites/__init__.py), read in the operator's own Chrome from CP's own results page.

Site rules (found on the real pages, 23 Oct 2026): https://www.cp.pt/en/resultado-pesquisa?passageiros=<n>&selectedClass=<1|2>&startDate=<yyyy-mm-dd>&departureStation=94-<id>&arrivalStation=94-<id> draws the
journey cards by itself (the date IS taken from the address, unlike the form). Each card: "3x", duration "01h52", class, Departure at / Arrival at, Service (Intercidades IC, Alfa Pendular AP, Regional...),
the price for ALL the passengers ("Price 81.30€", or a promo: "Promo price 40.50€, Price without promotion 66.60€, Promo ticket: Non refundable"). CP sells tickets only some weeks ahead: a far date answers
"No results were found for the selected filters" (March 2027 on 23 Oct 2026). The page's own API (api-gateway.cp.pt) answers 401 without the site's token and is not touched. Station ids are learned from the
address after one search on the page. Children's discounts are not read: CP's price for N passengers as the page counts them.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, server_first, with_emit

NAME = "cp_trains"
SOURCE = "CP (Comboios de Portugal)"
GROUP = "Trains"
NEEDS_WIDE_WINDOW = False
HERE = Path(__file__).parent
STATIONS = {"lisboa oriente": "94-31039", "lisbon oriente": "94-31039", "lisboa santa apolonia": "94-30007", "lisbon santa apolonia": "94-30007", "santa apolonia": "94-30007",
            "coimbra b": "94-36004", "coimbra": "94-36004", "porto campanha": "94-2006", "porto": "94-2006"}      # ids read from the address after a search, 23 Oct 2026 (Santa Apolonia 26 Oct: its id gave the Lisboa Santa Apolonia to Porto Campanha list on cp.pt)
CODE = re.compile(r"94-\d{3,6}")
ASK = {"class": "Class: 2nd (tourist) or 1st?", "time": "Departure time: the earliest and/or the latest (for 'in the morning' the latest is 12:00), or any time?", "refundable": "Refundable tickets only (CP's promo fares are non-refundable), or any fare?",
       "direct": "Direct trains only, or is a change fine?"}
RESULTS = "https://www.cp.pt/en/resultado-pesquisa"


def _key(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def station_id(name: str) -> str | None:
    """A station by name, or CP's own id ("94-30007") given as it is: the lookup steps below end with an id, and passing it must work (26 Oct 2026: the id was refused as an unknown station)."""
    if CODE.fullmatch((name or "").strip()):
        return name.strip()
    return STATIONS.get(_key(name))


def cp_trains_recipe(origin: str, destination: str, day: date, passengers: int = 2, first_class: bool = False, earliest: str | None = None, refundable: bool = False, direct_only: bool = False,
                     latest: str | None = None) -> dict[str, Any]:
    if not 1 <= passengers <= 9:
        raise ValueError("passengers must be 1-9 (everybody who needs a ticket)")
    for label, value in (("earliest", earliest), ("latest", latest)):
        if value is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError(f"{label} must be a time such as 08:00")
    a, b = station_id(origin), station_id(destination)
    if not a or not b:
        missing = [n for n, i in ((origin, a), (destination, b)) if not i]
        return {"needs_station_ids": missing, "known_stations": sorted(STATIONS), "steps": [
            "Open https://www.cp.pt/en in the operator's Chrome. In 'From' type the station and click the suggestion with the same name (the same for 'To'), then press Search (nothing is bought).",
            "On the results page run with the javascript tool: (() => new URLSearchParams(location.search).get('departureStation') + ' ' + new URLSearchParams(location.search).get('arrivalStation'))()  and tell the operator the ids "
            "then call this tool again giving each id (such as 94-30007) as the station name: an id is accepted as it is. Tell the operator the ids too, so that they are added to the tool. Without the tool, the results address is: " + RESULTS + "?passageiros=<n>&selectedClass=<1|2>&startDate=<yyyy-mm-dd>&departureStation=<id>&arrivalStation=<id>"]}
    url = f"{RESULTS}?passageiros={passengers}&selectedClass={1 if first_class else 2}&startDate={day.isoformat()}&departureStation={a}&arrivalStation={b}"
    expect = {"origin": origin, "destination": destination, "day": day.isoformat(), "passengers": passengers, "class": "1st" if first_class else "2nd", "earliest": earliest, "latest": latest, "refundable": refundable, "direct_only": direct_only,
              "leg": f"{origin} to {destination}, {day:%d %b %Y}"}
    return {"url": url, "script": with_emit((HERE / "cp_trains.js").read_text(encoding="utf-8")), "expect": expect}


def _same_place(expected: str, page: str) -> bool:
    """The page's station is the one asked for: by the first word of its name; a station given as CP's own id has no name to compare (the id is in the address the page was opened with)."""
    return bool(CODE.fullmatch((expected or "").strip())) or _key(expected).split(" ")[0] in _key(page)


def _minutes(text: str | None) -> int | None:
    m = re.match(r"^\s*(\d+)\s*h\s*(\d+)?", text or "")
    return int(m.group(1)) * 60 + int(m.group(2) or 0) if m else None


LONG_JOURNEY = 1.5       # CP's list does not show changes: a train this much slower than the fastest one almost surely changes


def _hhmm(text: str | None) -> str | None:
    m = re.match(r"^(\d{1,2}):(\d{2})$", (text or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the CP result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the CP script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    rows = data.get("rows", [])
    if data.get("no_results") and not rows:
        return SiteRows(problems=["CP shows 'No results were found' for this day: CP sells tickets only some weeks ahead (or the stations have no train). Put CP in not_checked with the reason 'not available: CP has no trains on sale for this date' and tell the operator to check cp.pt again closer to the date; never invent a price."])
    if exp:
        want = date.fromisoformat(exp["day"])
        month = want.strftime("%B")
        d = data.get("date_text") or ""
        if d and not re.search(rf"{month}\s+{want.day},\s+{want.year}", d):
            problems.append(f"the page is for '{d}', not {want:%B} {want.day}, {want.year}: open the url again (the date is in the address)")
        sides = re.split(r"\s*[›>]\s*", data.get("route") or "")
        if len(sides) == 2 and not (_same_place(exp["origin"], sides[0]) and _same_place(exp["destination"], sides[1])):
            problems.append(f"the page is for '{data.get('route')}', not {exp['origin']} to {exp['destination']}: open the url again")
        if data.get("class_text") and exp.get("class") and not str(data["class_text"]).lower().startswith(exp["class"]):
            problems.append(f"the page shows '{data['class_text']}', not the {exp['class']} class: open the url again")
    offers: list[Offer] = []
    fastest = min((m for m in (_minutes(r.get("dur")) for r in rows) if m), default=None)
    for r in rows:
        if r.get("price") is None:
            continue
        if exp and r.get("pax") and int(r["pax"]) != exp["passengers"]:
            problems.append(f"a card is priced for {r['pax']} passenger(s), not {exp['passengers']}: open the url again")
            break
        dep, arr = _hhmm(r.get("dep")), _hhmm(r.get("arr"))
        non_refundable = bool(r.get("promo")) and "non refundable" in (r.get("note") or "").lower().replace("-", " ")
        fits: bool | None = True if exp else None
        if exp.get("earliest") and dep:
            fits = bool(fits) and dep >= exp["earliest"]
        if exp.get("latest"):          # 'in the morning' = leaving by 12:00: a row whose departure is not shown cannot show that it fits
            fits = bool(fits) and bool(dep) and dep <= exp["latest"]
        if exp.get("refundable") and non_refundable:
            fits = False
        changes = r.get("changes")
        mins = _minutes(r.get("dur"))
        services = [x for x in (r.get("services") or []) if x]
        if r.get("changes_n") is not None:        # the card itself shows the changes (a lone number and one Service line per train): no guessing
            n = int(r["changes_n"])
            changes = f"{n} change{'s' if n != 1 else ''}: {' + '.join(services) or 'services not shown'}" if n else "direct (the card shows no change)"
            if n and exp.get("direct_only"):
                fits = False
        elif not changes and exp.get("direct_only") and fastest and mins:
            if mins > LONG_JOURNEY * fastest:
                changes, fits = f"probably a change: the journey takes {r.get('dur')} against {fastest // 60}h{fastest % 60:02d} for the fastest train", False
            else:
                changes = "not shown on the list; the journey time looks like a direct train"
        label = f"{' + '.join(services) or r.get('service') or 'train'} {dep}-{arr} ({(r.get('dur') or '').replace('h', 'h ')})"
        offers.append(Offer(
            group=exp.get("leg") or group, source=SOURCE, name=label, price_total=float(r["price"]), currency="EUR",
            price_basis=f"whole group ({exp.get('passengers') or r.get('pax')} passengers), CP's own price" + (f"; promo, without promotion {r['was']:g} EUR" if r.get("promo") and r.get("was") else ""),
            fits=fits, flexible=False if non_refundable else None, supplier="CP - Comboios de Portugal",
            details={"class_fare": f"{r.get('cls') or 'class not shown'}" + (" (promo)" if r.get("promo") else ""), "changes": changes or "not shown on the list (open See detail)", "seats_left": "not shown on the list",
                     "conditions": (r.get("note") or "not shown on the list (open See detail)")}))
    notes = ["CP's price is for all the passengers as the page counts them (adult fares): children's and other discounts are not read; ask the operator.",
             "CP sells tickets only some weeks ahead: a later date shows no trains."]
    if exp.get("direct_only") and any(r.get("changes_n") is None for r in rows):
        notes.append("Direct trains only was asked, but CP's list does not say which trains change: a train whose journey is much longer than the fastest is left out as 'probably a change', the others only LOOK direct. Open See detail on cp.pt to confirm before booking.")
    if data.get("cards_total") and len(rows) != data["cards_total"]:
        problems.append("the script's row count does not match its cards: run the script once more")
    return SiteRows(offers=offers, read=len(offers), total=len(offers), problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="cp_trains_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def cp_trains_recipe_tool(origin: str, destination: str, day: date, passengers: int = 2, first_class: bool | None = None, earliest: str | None = None, refundable: bool | None = None, direct_only: bool | None = None,
                                    operator_answered: bool = False, latest: str | None = None) -> dict[str, Any]:
        """FOR TRAINS IN PORTUGAL (Lisbon, Porto, Coimbra...; Comboios de Portugal, CP's own prices; read in the operator's own Chrome from cp.pt). One call per leg (a return trip is two calls with the
        stations swapped). ASK FIRST: without `first_class` (false = 2nd class), `earliest` and/or `latest` (HH:MM: for 'in the morning' give latest="12:00"; leave both out for any time, then `operator_answered`=true) and `refundable` (true/false) and `direct_only` (true = direct trains only: the card shows the number of changes, a train with a change is not a fit) it opens nothing and returns
        `ask_operator`: ask them in ONE message, wait, call again. `passengers` = everybody who needs a ticket (children included: CP's children discounts are not read). WHEN THE SERVER HAS AN AUTOMATION BROWSER (cp.pt's security policy stops the operator's Chrome from sending data to the server) THE SERVER READS THE PAGE ITSELF and returns a short receipt with an `ingest` id: call compose_answer with `runs`=[that id] and no Chrome action is needed (ok=false: put CP in not_checked with the reason it gives). Otherwise it returns the CP results url (stations,
        date, passengers and class are in the address) and a read-only SCRIPT: open the url, run the script with the javascript tool. The script sends its answer from the page to the server by itself and returns a
        short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id]; never type or pass a row. CP sells tickets only some weeks ahead: a far date shows no trains (the converter
        says so: put CP in not_checked with the reason 'not available'). If it answers `needs_station_ids`, follow its steps once. A human check is never worked around."""
        asked = [q for q, given in ((ASK["class"], first_class is not None), (ASK["time"], earliest is not None or latest is not None or operator_answered), (ASK["refundable"], refundable is not None), (ASK["direct"], direct_only is not None)) if not given]
        if asked and not operator_answered:
            return {"ok": False, "ask_operator": asked, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date, the stations and the number of passengers only if the request did not say them), wait for the reply, then call "
                            "this tool again with the answers. For 'any' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = cp_trains_recipe(origin, destination, day, passengers, bool(first_class), earliest, bool(refundable), bool(direct_only), latest)
        if "url" not in out:
            return out
        out["wishes"] = {"expect": out["expect"]}
        src = lambda v: "operator" if v is not None else "default: no preference"       # noqa: E731
        out["filters_used"] = [("1st class (operator)" if first_class else f"2nd class ({src(first_class)})"), (f"Departing {'after ' + earliest if earliest else ''}{' and ' if earliest and latest else ''}{'by ' + latest if latest else ''} (operator)" if earliest or latest else "Any departure time (operator: any)"),
                               ("Refundable tickets only (operator)" if refundable else f"Any fare, promo included ({src(refundable)})"),
                               ("Direct trains only (operator; the card shows the changes)" if direct_only else f"Changes allowed ({src(direct_only)})")]
        # cp.pt's security policy only lets the page talk to CP's own hosts, so the operator's Chrome cannot send the answer to this server: the server reads the page itself; when it cannot, the recipe comes back
        # for the operator's Chrome and its script returns the rows in parts (cp_trains is in NO_POST)
        return await server_first(NAME, "CP_READ_IN_SERVER", "https://www.cp.pt", out)
