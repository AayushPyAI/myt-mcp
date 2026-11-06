"""GetYourGuide: the EXACT price of ONE activity for a date and a group (a site module, see myt_mcp/sites/__init__.py), read from GetYourGuide's own availability call in the operator's own Chrome.

Site rules (read live 6 Nov 2026): an activity page (www.getyourguide.com/<place>/<slug>-t<id>/) has a booking box whose options come from ONE call of the page, POST travelers-api.getyourguide.com/user-interface/
activity-details-page/blocks (two events: the date and the travellers per category id). The traveller categories and their age ranges DIFFER per activity ("Adult (Age 13-99)", "Child (Age 12 and younger)"): a traveller counts in the
category whose range holds their age; the page's embedded state lists them (id, title, ages), the script puts each traveller in the right one itself and no stepper is touched. The answer holds, per option: the card (title,
"Duration: 3 hours", "Guide: English", "Cancel for free until Dec 16", meeting point and address, "Only 4 spots left"), the languages, every START TIME with the price of the WHOLE group (read live: 2 adults 140 EUR; 2 adults and a child aged 8
175 EUR = 2 x 70 + 35, equal to the page's Total) and the price per person by category. The currency is the accept-currency header (EUR), not the visitor's header menu. Nothing is booked: the script presses no button.
"""

from __future__ import annotations

import json
import re
from datetime import date
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
GUIDE = re.compile(r"^(Audio guide|Live guide|Guide|Language|Languages|Audio|Live tour guide)\b.*:", re.I)
CANCEL = re.compile(r"^(Cancel for free|Free cancellation|Non-refundable|Not refundable|Cancellation)", re.I)
STOPPED = re.compile(r"participants are required|not available|sold out|unavailable", re.I)


def clean_url(url: str, day: date) -> str:
    base = url.split("?")[0].split("#")[0].rstrip("/") + "/"
    return f"{base}?date_from={day.isoformat()}&date_to={day.isoformat()}"


def getyourguide_activity_recipe(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None) -> dict[str, Any]:
    m = URL.match(url or "")
    if not m:
        raise ValueError("url must be a GetYourGuide activity link (https://www.getyourguide.com/<place>/<slug>-t12345/ or https://www.getyourguide.com/-t12345/): take it from the search, never guess it")
    ages = list(children_ages or [])
    if not 0 <= adults <= 15 or not 1 <= adults + len(ages) <= 15 or any(not 0 <= a <= 17 for a in ages):
        raise ValueError("travellers must be 1-15 in total, adults 0-15, children's ages 0-17")
    total = adults + len(ages)
    link = clean_url(url, day)
    path = "/" + link.split("getyourguide.com/", 1)[1].split("?")[0].rstrip("/")
    request = {"id": int(m.group(1)), "day": day.isoformat(), "adults": adults, "ages": ages}
    expect = {"day": day.isoformat(), "adults": adults, "children": len(ages), "ages": ages, "total": total, "path": path, "id": int(m.group(1)), "group": group_title(activity, day)}
    steps = [f"Open {link} in the operator's Chrome (a new tab). The script sets the date and the travellers itself (each traveller in the category whose age range holds their age) and presses nothing: do not touch the date or the traveller box.",
             "Run the script with the javascript tool. It sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. Never press Continue, Select, Book now, Add to cart or Pay."]
    return {"url": link, "steps": steps, "script": with_emit((HERE / "getyourguide_activity.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps(request)), "expect": expect}


def _kind(group_size: str | None) -> str:
    """'Private: Just your group, up to 20 people' -> 'private group (Private: Just your group, up to 20 people)'; nothing -> 'not shown'."""
    t = (group_size or "").strip()
    if not t:
        return "not shown"
    low = t.lower()
    return f"{'private group' if low.startswith('private') else 'group'} ({t})"


KINDS = ("Private", "Standard group", "Small group", "Shared", "Group")


def _option_kind(lines: list[str], fallback: str | None) -> str:
    """The option card says its own kind ("Private" / "Just your group, up to 15 people", "Standard group" / "Up to 15 people"); the page-wide group size is only for an option that does not."""
    for i, x in enumerate(lines):
        if x in KINDS:
            size = lines[i + 1] if i + 1 < len(lines) and not re.match(r"(reserve now|cancel|meeting|select|read more)", lines[i + 1], re.I) else None
            return f"{'private group' if x == 'Private' else x.lower()}" + (f" ({size})" if size else "")
    return _kind(fallback)


def _page_link(exp: dict[str, Any]) -> str | None:
    """Each priced activity names its own page, with the date (28 Oct 2026: three rows, one link in Sources)."""
    path = str((exp or {}).get("path") or "")
    day = str((exp or {}).get("day") or "")
    return f"https://www.getyourguide.com{path}/" + (f"?date_from={day}&date_to={day}" if day else "") if path.startswith("/") and "-t" in path else None


def _after(lines: list[str], head: str) -> str | None:
    for i, line in enumerate(lines):
        if line.lower() == head.lower() and i + 1 < len(lines):
            return lines[i + 1]
    return None


def _categories(cats: list[dict[str, Any]]) -> str:
    return ", ".join(f"{c.get('title')} (age {c.get('min')}-{c.get('max')})" for c in cats)


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
    if data.get("no_category_for"):
        who = ", ".join(("an adult" if x == "adult" else f"a {x}-year-old") for x in data["no_category_for"])
        return SiteRows(problems=[f"GetYourGuide has no traveller category that takes {who} for this activity (its categories: {_categories(data.get('categories') or [])}): it cannot be priced for this group; say so"])
    if exp:
        got_n = sum(int(c.get("count") or 0) for c in data.get("categories") or [])
        if got_n != exp["total"]:
            problems.append(f"the script priced {got_n} traveller(s), not {exp['total']}: run it again")
        if data.get("day_read") and data["day_read"] != exp["day"]:
            problems.append(f"GetYourGuide answered for {data['day_read']}, not {exp['day']}: run the script again")
        if exp.get("id") and data.get("id") and data["id"] != exp["id"]:
            problems.append(f"the page is the activity {data['id']}, not {exp['id']}: open the url again")
        read = {c.get("id"): c.get("count") for c in data.get("categories_read") or []}
        sent = {c.get("id"): c.get("count") for c in data.get("categories") or []}
        if read and any(read.get(k) != v for k, v in sent.items()):
            problems.append("GetYourGuide priced other traveller categories than the script sent: run the script again")
    avail = (data.get("availability") or "").lower()
    if not rows:
        notes.append(f"GetYourGuide says: {data.get('availability') or 'no option'} (for the date and group asked)" + (f"; {data['unavailable']}" if data.get("unavailable") not in (None, "[]") else "") + ": it may need another date or a larger group."
                     + (f" Its last bookable date is {data['last_available_date']}." if data.get("last_available_date") else ""))
    offers: list[Offer] = []
    pax = (exp or {}).get("total") or sum(int(c.get("count") or 0) for c in data.get("categories") or [])
    for r in rows:
        lines = [str(x) for x in r.get("lines") or []]
        if r.get("total") is None:
            stop = next((x for x in lines if STOPPED.search(x)), "no price")
            notes.append(f"Option '{r.get('title')}': {stop}")
            continue
        if (r.get("cur") or "") not in EUR:
            problems.append(f"the page prices option '{r.get('title')}' in '{r.get('cur')}', not EUR: run the script again")
            continue
        slots = r.get("slots") or []
        times = [(clock24(s.get("time")) or str(s.get("time")), s.get("price")) for s in slots]
        if r.get("totals_differ"):
            start = f"{len(times)} start time(s) with their own price: " + ", ".join(f"{t} (EUR {p:g})" for t, p in times[:6] if p is not None)
            notes.append(f"Option '{r.get('title')}': the price depends on the start time ({', '.join(f'{t} EUR {p:g}' for t, p in times[:6] if p is not None)}); the row shows the lowest.")
        else:
            start = (f"{len(times)} start time(s): " + ", ".join(t for t, _ in times[:6]) + (f", ... last {times[-1][0]}" if len(times) > 6 else "")) if times else "not shown"
        duration = next((x.split(":", 1)[1].strip() for x in lines if x.startswith("Duration:")), None)
        guide = next((x for x in lines if GUIDE.match(x)), None)
        cancel = next((x for x in lines if CANCEL.match(x)), None) or "not shown"
        free = bool(re.match(r"(cancel for free|free cancellation)", cancel, re.I))
        meet = _after(lines, "Meeting point")
        address = next((x for x in lines if x.startswith("Meet at ")), None)
        spots = next((x for x in lines if re.match(r"Only \d+ spots? left", x, re.I)), None)
        parts = "; ".join(f"{b.get('n')} {b.get('title')} x {b.get('each'):g} = {b.get('total'):g}" for b in r.get("breakdown") or [] if b.get("each") is not None and b.get("total") is not None) or "breakdown not shown"
        taxes = any(re.search(r"all taxes and fees included", x, re.I) for x in lines) or bool(data.get("taxes_included"))
        langs = ", ".join(r.get("langs") or [])
        name = f"{r.get('title')} ({duration or 'duration not shown'}{', ' + guide if guide else (', languages: ' + langs if langs else '')})"
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=name, price_total=r.get("total"), currency="EUR",
            price_basis=f"whole group ({pax} travellers; {parts}), " + ("all taxes and fees included" if taxes else "taxes not stated"),
            flexible=True if free else (False if re.match(r"(non-?refundable|not refundable)", cancel, re.I) else None), supplier="GetYourGuide", link=_page_link(exp),
            details={"duration": duration or "not shown", "start_times": start, "language": guide or (langs or "not shown"),
                     "meeting_point": (f"{meet}" + (f" ({address})" if address else "")) if meet else (address or "see the Meeting point link on the page"),
                     "cancellation": cancel, "availability": spots or "not shown", "private_or_group": _option_kind(lines, data.get("group_size")), "includes": data.get("includes") or "not shown", "group_size": data.get("group_size") or "not shown",
                     "know_before": data.get("know_before") or "not shown", "flags": ", ".join(x for x in ("Skip the line", "Wheelchair accessible", "Hotel pickup") if x in lines) or None, "pay": "reserve now, pay later" if any(re.search(r"reserve now & pay later", x, re.I) for x in lines) else "not shown"}))
    notes.append("GetYourGuide's exact price for this date and group; the activity's own page is the quoted source. The 'from' price in the search is only the lowest starting price.")
    return SiteRows(offers=offers, read=len(offers), total=len(rows), problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="getyourguide_activity_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def getyourguide_activity_recipe_tool(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None, free_cancellation: bool = False) -> dict[str, Any]:
        """FOR THE EXACT PRICE OF ONE GETYOURGUIDE ACTIVITY on a date for a group (read in the operator's own Chrome with Claude in Chrome): use the activity link from getyourguide_find_recipe (never guess
        a link). Give `adults` and `children_ages` ([] if none) as the operator said (ask if not said); `activity` = the itinerary activity this answers; `free_cancellation` only if the operator asked for it. It returns the url, STEPS and a read-only SCRIPT: open the url in a NEW tab and run the script; it puts every traveller in the category of their age by itself and presses nothing (never press Select, Book now, Add to cart or Pay). It sends its answer to the server by itself and returns a receipt (`ingest` id): call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. A human check is never worked around. One call per activity."""
        out = getyourguide_activity_recipe(url, day, adults, children_ages, activity)
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {})}
        out["filters_used"] = ["Date and group as the operator said (operator)", "Free cancellation only (operator)" if free_cancellation else "All options of the activity for that date (default: no option filter)"]
        return out
