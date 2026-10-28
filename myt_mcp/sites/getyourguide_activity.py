"""GetYourGuide: the EXACT price of ONE activity for a date and a group (a site module, see myt_mcp/sites/__init__.py), read in the operator's own Chrome.

Site rules (found on the real page, 22 Oct 2026): an activity page (www.getyourguide.com/<place>/<slug>-t<id>/) has a booking box: "From X per person", a traveller box (categories with age ranges that
DIFFER per activity, for example "Adult (Age 3-99)" and "Child (Age 2 and younger)": a traveller counts in the category whose range holds their age), a date and a language. With the date in the address
(?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD) and the group set, the page shows "N option(s) available" (or "Not available for your selection", for example "At least 2 participants are required"), and per option:
duration, guide language, "Cancel for free until <day>", a meeting point link, a start-time list, the price of the WHOLE group ("EUR 717" with "3 Adult x 239") and "All taxes and fees included". Setting the group
changes the address (_pc=<category>,<count>). The page shows the prices in the currency of the visitor's header menu (EN/ILS for an Israeli browser): it must be EUR. Nothing is booked: the script never presses Continue.
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
from myt_mcp.sites import SiteRows, clock24, group_title, with_emit

NAME = "getyourguide_activity"
SOURCE = "GetYourGuide"
GROUP = "Activities"
RESULT_MARKS = {"url_path", "activity"}      # keys only this recipe's answers have: a display name that fits a list recipe and a page recipe is told apart by them (resolve_site_names)
HERE = Path(__file__).parent
URL = re.compile(r"^https://www\.getyourguide\.com/[^?#\s]*-t(\d+)/?(?:[?#].*)?$")
EUR = {"€", "EUR"}


def clean_url(url: str, day: date) -> str:
    base = url.split("?")[0].split("#")[0].rstrip("/") + "/"
    return f"{base}?date_from={day.isoformat()}&date_to={day.isoformat()}"


def getyourguide_activity_recipe(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None) -> dict[str, Any]:
    if not URL.match(url or ""):
        raise ValueError("url must be a GetYourGuide activity link (https://www.getyourguide.com/<place>/<slug>-t12345/): take it from the search, never guess it")
    ages = list(children_ages or [])
    if not 0 <= adults <= 15 or not 1 <= adults + len(ages) <= 15 or any(not 0 <= a <= 17 for a in ages):
        raise ValueError("travellers must be 1-15 in total, adults 0-15, children's ages 0-17")
    total = adults + len(ages)
    link = clean_url(url, day)
    path = "/" + link.split("getyourguide.com/", 1)[1].split("?")[0].rstrip("/")
    expect = {"day": day.isoformat(), "adults": adults, "children": len(ages), "ages": ages, "total": total, "path": path, "group": group_title(activity, day)}
    steps = [f"Open {link} in the operator's Chrome. The header menu (EN/...) must show EUR; if it shows another currency (for example ILS), open it, choose Euro (EUR), save, and open the url again (this only changes the display currency). "
             "If a cookie banner is in the way, decline non-essential cookies.",
             f"Open the traveller box and set {total} traveller(s): put each traveller in the category whose age range contains their age (ages: adults {adults}" + (f", children {ages}" if ages else "") +
             "; the categories and their age ranges are listed in the box and differ per activity). Press Continue in that box. If the date is not Mar/the day asked, set it to " + f"{day:%d %b %Y}" + ".",
             "Wait until the page says 'N option(s) available' (or 'Not available for your selection' and why). Do NOT press Continue on an option, Book, Reserve or Pay.",
             "Run the script with the javascript tool and The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row with the returned `wishes`."]
    return {"url": link, "steps": steps, "script": with_emit((HERE / "getyourguide_activity.js").read_text(encoding="utf-8")), "expect": expect}


def _day(text: str | None) -> date | None:
    try:
        return datetime.strptime((text or "").strip(), "%A, %B %d, %Y").date()
    except ValueError:
        return None


def _kind(group_size: str | None) -> str:
    """'Private: Just your group, up to 20 people' -> 'private group (Private: Just your group, up to 20 people)'; nothing -> 'not shown'."""
    t = (group_size or "").strip()
    if not t:
        return "not shown"
    low = t.lower()
    return f"{'private group' if low.startswith('private') else 'group'} ({t})"


def _travellers(label: str | None) -> int | None:
    found = re.findall(r"[x×]\s?(\d+)", label or "")
    return sum(int(n) for n in found) if found else None


def _page_link(exp: dict[str, Any]) -> str | None:
    """Each priced activity names its own page, with the date (28 Oct 2026: three rows, one link in Sources)."""
    path = str((exp or {}).get("path") or "")
    day = str((exp or {}).get("day") or "")
    return f"https://www.getyourguide.com{path}/" + (f"?date_from={day}&date_to={day}" if day else "") if path.startswith("/") and "-t" in path else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the GetYourGuide result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the GetYourGuide script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    notes: list[str] = []
    rows = data.get("rows", [])
    if exp:
        got_n = _travellers(data.get("travellers"))
        if got_n is not None and got_n != exp["total"]:
            problems.append(f"the page has {got_n} traveller(s) selected ('{data.get('travellers')}'), not {exp['total']}: set the travellers (each in the category of their age) and run the script again")
        if got_n is None and rows:
            problems.append("the traveller selection could not be read from the page: open the traveller box, set the group, press Continue and run the script again")
    avail = (data.get("availability") or "").lower()
    if not rows and avail:
        notes.append(f"GetYourGuide says: {data['availability']} (for the date and group asked): " + ("it may need another date or a larger group." if "not available" in avail else "nothing to quote."))
    offers: list[Offer] = []
    for r in rows:
        if r.get("unavailable") and r.get("price") is None:
            notes.append(f"Option '{r.get('title')}': {r['unavailable']}")
            continue
        sym = r.get("price_symbol")
        if sym not in EUR:
            problems.append(f"the page shows prices in '{sym}', not EUR: open the header menu (EN/...), choose Euro (EUR), open the url again and run the script again")
            continue
        d = _day(r.get("day"))
        if exp and d and d.isoformat() != exp["day"]:
            problems.append(f"option '{r.get('title')}' is for {d.isoformat()}, not {exp['day']}: set the date and run the script again")
            continue
        times = [clock24(t) or t for t in (r.get("times") or [])]      # one 24-hour clock for every source
        start = (f"{len(times)} start time(s): " + ", ".join(times[:6]) + (f", ... last {times[-1]}" if len(times) > 6 else "")) if times else "not shown"
        cancel = r.get("cancel") or "not shown"
        free = bool(re.match(r"(cancel for free|free cancellation)", cancel, re.I))
        pax = exp.get("total") or _travellers(data.get("travellers")) or 0
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=f"{r.get('title')} ({r.get('duration') or 'duration not shown'}{', ' + r['guide'] if r.get('guide') else ''})", price_total=r.get("price"), currency="EUR",
            price_basis=f"whole group ({pax} travellers; {'; '.join(r.get('breakdown') or []) or 'breakdown not shown'}), " + ("all taxes and fees included" if r.get("taxes_included") else "taxes not stated"),
            flexible=True if free else (False if re.match(r"(non-?refundable|not refundable)", cancel, re.I) else None), supplier="GetYourGuide", link=_page_link(exp),
            details={"duration": r.get("duration") or "not shown", "start_times": start, "language": r.get("guide") or "not shown",
                     "meeting_point": (("page says: " + data["meeting_page"]) if data.get("meeting_page") else "see the Meeting point link on the page") if r.get("meeting_point") or data.get("meeting_page") else "not shown",
                     "cancellation": cancel, "availability": r.get("spots") or "not shown", "private_or_group": _kind(data.get("group_size")), "includes": data.get("includes") or "not shown", "group_size": data.get("group_size") or "not shown", "know_before": data.get("know_before") or "not shown",
                     "pay": "reserve now, pay later" if r.get("pay_later") else "not shown"}))
    notes.append("GetYourGuide's exact price for this date and group; the activity's own page is the quoted source. The 'from' price in the search is only the lowest starting price.")
    return SiteRows(offers=offers, read=len(offers), total=len(rows), problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="getyourguide_activity_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def getyourguide_activity_recipe_tool(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None, free_cancellation: bool = False) -> dict[str, Any]:
        """FOR THE EXACT PRICE OF ONE GETYOURGUIDE ACTIVITY on a date for a group (read in the operator's own Chrome with Claude in Chrome): use the activity link from getyourguide_find_recipe (never guess
        a link). Give `adults` and `children_ages` ([] if none) as the operator said (ask if not said); `activity` = the itinerary activity this answers (it names the row group); `free_cancellation` only if the
        operator asked for it. It returns the url (date in the address), STEPS to set the travellers (each in the category of their age: categories differ per activity) and to make sure the header shows EUR, and a
        read-only SCRIPT: run it after the page says "N options available"; it reads each option (duration, guide language, cancellation, start times, the price of the whole group, taxes). The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. Never press Continue on an option, Book,
        Reserve or Pay. A human check is never worked around: stop and tell the operator. One call per activity."""
        out = getyourguide_activity_recipe(url, day, adults, children_ages, activity)
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {})}
        out["filters_used"] = ["Date and group as the operator said (operator)", "Free cancellation only (operator)" if free_cancellation else "All options of the activity for that date (default: no option filter)"]
        return out
