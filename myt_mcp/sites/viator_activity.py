"""Viator: the EXACT price of ONE activity for a date and a group (a site module, see myt_mcp/sites/__init__.py), read in the operator's own Chrome.

Site rules (found on the real page, 22 Oct 2026): an activity page (www.viator.com/tours/<place>/<name>/d<id>-<code>) has a booking box: "From EUR 73.00 per person", Date, Travelers and Start time. The date is NOT
taken from the address (a startDate parameter is ignored): it is picked in a two-month calendar (arrows move the months). The traveller box lists age bands that differ per activity ("Adult (Age 18-70)", "Child
(Age 6-16) -32%", "Infant (Age 2-5)"; "Select up to 12 travelers"); after Apply the box shows the price of the WHOLE group (the 'From' line becomes e.g. "EUR 195.00"), the start-time list and
"Free cancellation before 9:00 AM on Mar 4, 2027 (local time)" / "Reserve now, pay nothing until Mar 3, 2027". "Price details" opens a window with "2 Adults x 73.00 = 146.00, 1 Child x 49.00 (-32%) = 49.00, Total Price".
The price follows the visitor's currency (the globe menu): it must be EUR. The script reads and may open and close the "Price details" window; it never presses Book Now or Reserve Now & Pay Later.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, group_title, with_emit

NAME = "viator_activity"
SOURCE = "Viator"
GROUP = "Activities"
RESULT_MARKS = {"url_path", "activity"}      # keys only this recipe's answers have: a display name that fits a list recipe and a page recipe is told apart by them (resolve_site_names)
HERE = Path(__file__).parent
URL = re.compile(r"^https://www\.viator\.com/tours/[^?#\s]+/d\d+-[A-Za-z0-9_.]+/?(?:[?#].*)?$")
EUR = {"€", "EUR"}


def clean_url(url: str) -> str:
    return url.split("?")[0].split("#")[0]


def viator_activity_recipe(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None) -> dict[str, Any]:
    if not URL.match(url or ""):
        raise ValueError("url must be a Viator activity link (https://www.viator.com/tours/<place>/<name>/d123-CODE): take it from the search, never guess it")
    ages = list(children_ages or [])
    if not 0 <= adults <= 15 or not 1 <= adults + len(ages) <= 15 or any(not 0 <= a <= 17 for a in ages):
        raise ValueError("travellers must be 1-15 in total, adults 0-15, children's ages 0-17")
    total = adults + len(ages)
    link = clean_url(url)
    path = "/" + link.split("viator.com/", 1)[1]
    expect = {"day": day.isoformat(), "adults": adults, "children": len(ages), "ages": ages, "total": total, "path": path, "group": group_title(activity, day)}
    steps = [f"Open {link} in the operator's Chrome. The prices must be in EUR: if the page shows another currency, open the globe menu (top right), choose EUR and reload. If a cookie banner is in the way, decline non-essential cookies.",
             f"Date: click the Date field and move the calendar with its arrow (two months are shown) to {day:%B %Y}, then click the day {day.day}. (The address cannot carry the date.)",
             f"Travelers: open the Travelers box and set {total} traveller(s): each in the age band that contains their age (the bands are listed with their ages and differ per activity; adults {adults}" + (f", children's ages {ages}" if ages else "") +
             "). Press Apply. The box then shows the price of the whole group and a start-time list; do not change the start time unless the operator asked for one.",
             "Wait until the box shows the price of the group (not 'From ... per person'). Do NOT press Book Now or Reserve Now & Pay Later.",
             "Run the script with the javascript tool (it opens and closes the 'Price details' window to read the breakdown) and The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row with the returned `wishes`."]
    return {"url": link, "steps": steps, "script": with_emit((HERE / "viator_activity.js").read_text(encoding="utf-8")), "expect": expect}


def _money(text: str | None) -> tuple[str | None, float | None]:
    m = re.match(r"^\s*([€₪$£])\s?([\d.,]+)\s*$", text or "")
    return (m.group(1), float(m.group(2).replace(",", ""))) if m else (None, None)


def _when(text: str | None) -> date | None:
    m = re.match(r"^([A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}, \d{4})", text or "")
    try:
        return datetime.strptime(m.group(1), "%a, %b %d, %Y").date() if m else None
    except ValueError:
        return None


def _count(text: str | None) -> int | None:
    found = re.findall(r"(\d+)\s+(?:Adult|Child|Infant|Senior|Youth|Student|Traveler|Traveller)", text or "")
    return sum(int(n) for n in found) if found else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Viator result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Viator script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    offers: list[Offer] = []
    rows = data.get("rows", [])
    title = data.get("activity") or "activity"
    if exp and data.get("url_path") and exp.get("path") and data["url_path"].rstrip("/") != exp["path"].rstrip("/"):
        problems.append(f"the page is {data['url_path']}, not the activity asked ({exp['path']}): open the url again")
    asked_day = date.fromisoformat(exp["day"]) if exp else None
    if asked_day and data.get("date_box") and data["date_box"] != f"{asked_day:%a}, {asked_day:%b} {asked_day.day}":
        problems.append(f"the box shows the date '{data['date_box']}', not {asked_day:%a}, {asked_day:%b} {asked_day.day}: pick the day in the calendar and run the script again")
    if exp and data.get("travellers_box") is not None and data["travellers_box"] != exp["total"]:
        problems.append(f"the box has {data['travellers_box']} traveller(s), not {exp['total']}: set the travellers (each in the age band of their age), press Apply and run the script again")
    for r in rows:
        if not r.get("priced"):
            problems.append(f"the box still shows '{r.get('from_text')}' (a price per person): set the date and the travellers (Apply) so that it shows the price of the group, then run the script again")
            continue
        sym, amount = _money(r.get("dialog_total") or r.get("price_text"))
        if sym not in EUR:
            problems.append(f"the page shows prices in '{sym}', not EUR: open the globe menu, choose EUR, set the date and travellers again and run the script again")
            continue
        when = _when(r.get("dialog_when"))
        if exp and r.get("dialog_when") is not None and (when is None or when.isoformat() != exp["day"]):
            problems.append(f"the price is for {when.isoformat() if when else r['dialog_when']}, not {exp['day']}: pick the day in the calendar and run the script again")
        n = _count(r.get("dialog_travellers")) or _count(" ".join(r.get("breakdown") or [])) or data.get("travellers_box")
        if exp and n != exp["total"]:
            problems.append(f"the price is for {n} traveller(s) ('{r.get('dialog_travellers') or '; '.join(r.get('breakdown') or []) or data.get('travellers_box')}'), not {exp['total']}: set the travellers (each in the age band of their age), press Apply and run the script again")
        if exp and not r.get("option") and r.get("dialog_when") is None and not data.get("date_box"):
            problems.append("the date of the group price could not be read ('Price details' did not open): run the script once more")
        if r.get("dialog_total") and r.get("price_text") and r["dialog_total"] != r["price_text"]:
            problems.append(f"the box says {r['price_text']} but 'Price details' says {r['dialog_total']}: run the script once more")
        times = r.get("times") or []
        start = ((f"chosen: {r['start_time']}; " if r.get("start_time") else "") + f"{len(times)} start time(s): " + ", ".join(times[:6]) + (f", ... last {times[-1]}" if len(times) > 6 else "")) if times else \
            ("select this option on the page to see its start times" if r.get("option") else "not shown")
        cancel = re.sub(r"(?i)cancellation(?=before|up to)", "cancellation ", r.get("cancellation") or "") or ("not shown until this option is selected on the page" if r.get("option") else "not shown")
        policy_free = bool(re.search(r"cancel up to \d+ (?:hours?|days?) in advance.{0,60}full refund", data.get("cancel_policy") or "", re.I))      # the page's own policy line (27 Oct 2026: it was not read as free cancellation)
        free = cancel.lower().startswith("free cancellation") or policy_free
        cancel_text = (f"Free cancellation per the page's policy: {data['cancel_policy']}" if policy_free and not cancel.lower().startswith("free cancellation")
                       else cancel + (f"; policy: {data['cancel_policy']}" if data.get("cancel_policy") else ""))
        name = f"{title} - {r['option']}" if r.get("option") else title
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=f"{name} ({(data.get('duration') or 'duration not shown').replace(' (approx.)', ' approx.')})", price_total=amount, currency="EUR",
            price_basis=f"whole group ({n} travellers; {'; '.join(r.get('breakdown') or []) or 'breakdown not shown'}), taxes and fees not stated on the page", flexible=True if free else (False if re.search(r"non-?refundable|not refundable", cancel, re.I) else None),
            supplier="Viator", details={"duration": data.get("duration") or "not shown", "start_times": start, "language": f"offered in: {data['offered_in']}" if data.get("offered_in") else "not shown",
                                         "meeting_point": data.get("meeting_text") or "not shown in the booking box (see the activity page)", "includes": data.get("included") or "not shown", "additional_info": data.get("additional") or "not shown",
                                         "cancellation": cancel_text, "private_or_group": "private" if "private" in name.lower() else "not shown",
                                         "pay": (r.get("pay_later") or "not shown"), "ticket": "mobile ticket" if data.get("mobile_ticket") else "not shown", "option_state": ("selected on the page" if r.get("selected") else "not selected on the page") if r.get("option") else "single option"}))
    return SiteRows(offers=offers, read=len(offers), total=len(rows), problems=problems, sorted_by_price=False, read_rows=True,
                    extra_notes=["Viator's exact price for this date and group (child discounts included as the page shows them); the activity's own page is the quoted source. The 'from' price in the search is only the lowest starting price."]
                    + (["This activity has several options: each has its own price; only the selected option shows its start times and cancellation terms."] if any(r.get("option") for r in rows) else []))


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="viator_activity_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def viator_activity_recipe_tool(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None, free_cancellation: bool = False) -> dict[str, Any]:
        """FOR THE EXACT PRICE OF ONE VIATOR ACTIVITY on a date for a group (read in the operator's own Chrome with Claude in Chrome): use the activity link from viator_find_recipe (never guess a link). Give
        `adults` and `children_ages` ([] if none) as the operator said (ask if not said); `activity` = the itinerary activity this answers (it names the row group); `free_cancellation` only if the operator asked
        for it. It returns the url, STEPS (pick the date in the calendar, set the travellers in the age band of each person, Apply, make sure the page shows EUR) and a read-only SCRIPT: run it when the booking box
        shows the price of the group; it reads the price, the breakdown by age band (it opens and closes 'Price details'), the start times and the cancellation terms. The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. Never press Book Now or Reserve Now & Pay Later. A human check is
        never worked around: stop and tell the operator. One call per activity."""
        out = viator_activity_recipe(url, day, adults, children_ages, activity)
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {})}
        out["filters_used"] = ["Date and group as the operator said (operator)", "Free cancellation only (operator)" if free_cancellation else "The activity's default option (default: no option filter)"]
        return out
