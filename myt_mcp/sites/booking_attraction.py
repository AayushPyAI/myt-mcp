"""Booking.com attractions: the price of ONE activity for a date and a group (COMPARISON ONLY; a site module, see myt_mcp/sites/__init__.py), read in the operator's own Chrome.

Site rules (found on the real page, 27 Oct 2026; the data source read live 5 Nov 2026): the activity page is booking.com/attractions/<country>/<slug>.html (the site redirects to <slug>.en-gb.html); with
?date=YYYY-MM-DD&selected_currency=EUR in the address the ticket box shows that date. The box gets its tickets from ONE GraphQL request, POST accommodations.booking.com/dml/graphql, operation GetAvailability, input {date, id (the
product id from the page's own store), urlCode, includeSoldOut}: `timeslots` (start time, unitsAvailable, availabilityState, reservableUntil), each with `timeSlotOffers` (the ticket offers bookable on the date: "Ticket",
"Skip-the-line ticket" ...), each with `items`, one per kind of ticket ("Adult (age 13-64)", "Child (age 3-12)", "Senior (age 65+)", "Infant (age 0-2)": the kinds and ages differ per activity) with its price (chargeAmount),
age constraint, ticketsAvailable, min/max per booking and its cancellationPolicy ("Non-refundable", or free cancellation with the exact cut-off). The page adds the Total up in the browser from these prices ("Includes taxes and charges"):
checked live, 2 adults + 1 child on 18 Dec: the page 77.50, the service 2 x 29.90 + 17.70. A compact query for the fields needed gives the same data as the page's own query (18 time slots and 72 ticket prices equal); the CSRF token and
pageview id are optional. The product's own data (what is included, the operator, the meeting address) is in the page's Apollo store (getProduct). Each traveller goes in the kind whose age range holds their age, the adults in "Adult".
The script never presses "Next" (the first booking step). The list (booking_attractions) shows only a "from" price; this is the price to quote from. A human check is never worked around.
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
from myt_mcp.sites import SiteRows, group_title, server_first, with_emit

NAME = "booking_attraction"
SOURCE = "Booking.com attractions (public website price)"
GROUP = "Activities"
HERE = Path(__file__).parent
URL = re.compile(r"^https://www\.booking\.com/attractions/([a-z]{2})/([a-z0-9-]+?)(?:\.[a-z-]+)?\.html(?:[?#].*)?$")
MAX_TRAVELLERS = 15


def booking_attraction_recipe(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None) -> dict[str, Any]:
    m = URL.match(url or "")
    if not m:
        raise ValueError("url must be a Booking.com activity link (https://www.booking.com/attractions/pt/<slug>.html): take it from the list (booking_attractions_recipe), never guess it")
    ages = list(children_ages or [])
    if not 0 <= adults <= MAX_TRAVELLERS or not 1 <= adults + len(ages) <= MAX_TRAVELLERS or any(not 0 <= a <= 99 for a in ages):
        raise ValueError(f"travellers must be 1-{MAX_TRAVELLERS} in total, adults 0-{MAX_TRAVELLERS}, ages 0-99 (the ages of everyone who is not a plain adult: children and seniors)")
    if adults < 1 and not any(a >= 18 for a in ages):
        raise ValueError("at least one adult is needed: a child is booked with an adult (the site says so)")
    cc, slug = m.group(1), m.group(2)
    link = f"https://www.booking.com/attractions/{cc}/{slug}.html?date={day.isoformat()}&selected_currency=EUR"
    expect = {"slug": slug, "country": cc, "day": day.isoformat(), "adults": adults, "children": len(ages), "ages": ages, "total": adults + len(ages), "currency": "EUR", "group": group_title(activity, day)}
    request = {"slug": slug, "day": day.isoformat(), "adults": adults, "ages": ages}
    script = with_emit((HERE / "booking_attraction.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps(request))
    return {"url": link, "script": script, "expect": expect}


def _num(v: float | None) -> str:
    return "not shown" if v is None else f"{v:,.2f}"


def _page_link(exp: dict[str, Any], data: dict[str, Any]) -> str | None:
    """Each priced activity names its own page with the date and the euro in the address."""
    slug, cc = data.get("slug") or exp.get("slug"), data.get("country") or exp.get("country")
    if not slug or not cc or not re.fullmatch(r"[a-z]{2}", str(cc)) or not re.fullmatch(r"[a-z0-9-]+", str(slug)):
        return None
    return f"https://www.booking.com/attractions/{cc}/{slug}.html?date={exp.get('day') or data.get('day')}&selected_currency=EUR"


def _until(stamp: str | None) -> str | None:
    return stamp[:16].replace("T", " ") if stamp else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Booking.com result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Booking.com script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    if exp.get("slug") and data.get("slug") != exp["slug"]:
        problems.append(f"the page is the activity '{data.get('slug')}', not '{exp['slug']}': open the url again")
    if exp.get("day") and data.get("day") != exp["day"]:
        problems.append(f"the answer is for {data.get('day')}, not {exp['day']}: run the script again")
    asked = data.get("travellers") or {}
    if exp and (asked.get("adults") != exp.get("adults") or list(asked.get("ages") or []) != list(exp.get("ages") or [])):
        problems.append(f"the travellers sent were {asked.get('adults')} adults and ages {asked.get('ages')}, not {exp.get('adults')} adults and ages {exp.get('ages')}: run the script again")
    notes: list[str] = []
    if data.get("unavailable"):
        notes.append(f"{data['unavailable']}. It may be sold out or simply not open yet for that date: it is not a price, and never 'sold out' from this alone.")
        return SiteRows(offers=[], read=0, total=0, problems=problems, extra_notes=notes, read_rows=True)
    offers: list[Offer] = []
    pax = exp.get("total") or ((asked.get("adults") or 0) + len(asked.get("ages") or []))
    cancel_free = bool(wishes.get("free_cancellation"))
    for r in data.get("rows", []):
        label = r.get("ticket") or "ticket"
        if r.get("cur") != "EUR":
            problems.append(f"the ticket '{label}' is priced in '{r.get('cur')}', not euro: open the url again (the address asks selected_currency=EUR)")
            continue
        if r.get("unfit"):
            problems.append(f"the ticket '{label}' has no kind for: {', '.join(str(x) for x in r['unfit'])} (its kinds and ages are on the page): say it cannot be quoted for this group")
            continue
        kinds = r.get("kinds") or []
        if pax and sum(k.get("count") or 0 for k in kinds) != pax:
            problems.append(f"the ticket '{label}' was priced for {sum(k.get('count') or 0 for k in kinds)} traveller(s), not {pax}: run the script again")
            continue
        slots = r.get("slots") or []
        unpriced = [x for x in slots if x.get("bookable") and not x.get("total")]      # a time slot that gives no price for a group of priced tickets is a reading fault, never a free ticket
        if unpriced:
            problems.append(f"the ticket '{label}' gave no price for {len(unpriced)} of its time slot(s) ({', '.join(str(x.get('time')) for x in unpriced[:4])}): run the script again")
        bookable = [x for x in slots if x.get("bookable") and x.get("total")]
        if not bookable:
            why = "; ".join(dict.fromkeys(w for x in slots for w in (x.get("why") or []))) or "every time slot is sold out or closed"
            notes.append(f"The ticket '{label}' cannot take this group on {data.get('day')}: {why}.")
            continue
        total = bookable[0].get("total")
        if not total:
            problems.append(f"the ticket '{label}' shows no price for the group: say it could not be quoted")
            continue
        breakdown = "; ".join(f"{k['count']} x {k['label']} {k.get('constraint') or ''} at {k['price']:.2f} EUR".replace("  ", " ") for k in kinds if k.get("price") is not None) or "breakdown not shown"
        times = [x["time"] for x in bookable if x.get("time")]
        start = f"{len(times)} start time(s): " + ", ".join(times[:8]) + (f", ... last {times[-1]}" if len(times) > 8 else "") if times else "not listed"
        if len({x["total"] for x in bookable}) > 1:
            start += "; the price differs by time: " + ", ".join(f"{x['time']} {x['total']:g}" for x in bookable[:6]) + " EUR"
        cancel = r.get("cancel") or {}
        if cancel.get("free"):
            cancel_text = "Free cancellation" + (f" until {_until(cancel['until'])}" if cancel.get("until") else "") + (" (Booking.com's own data)" if cancel.get("until") else " (Booking.com's own flag)")
            flexible, fits = True, (True if cancel_free else None)
        else:
            cancel_text = cancel.get("label") or "not free to cancel (Booking.com's own flag)"
            nonref = bool(re.search(r"non-?refundable|not refundable", cancel_text, re.I)) or cancel.get("free") is False
            flexible, fits = (False if nonref else None), (False if cancel_free and nonref else None)
        units = bookable[0].get("units")
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=(data.get("activity") or "Booking.com activity") + f" ({label})", price_total=float(total), currency="EUR",
            price_basis=f"whole group ({pax} travellers; {breakdown}), taxes and charges included (Booking.com's total), for {data.get('day') or exp.get('day')}" + (f", the first time {times[0]}" if times else ""),
            flexible=flexible, fits=fits, quotable=False, supplier=data.get("operated_by") or "Booking.com", link=_page_link(exp, data),
            details={"duration": data.get("duration") or "none given by Booking.com (an entrance ticket has none)", "start_times": start, "language": "not shown by the ticket data", "meeting_point": data.get("meeting") or "not shown (see Location on the page)",
                     "cancellation": cancel_text, "private_or_group": "private" if re.search(r"private", f"{label} {data.get('activity') or ''}", re.I) else "not shown", "includes": r.get("includes") or data.get("includes") or "not shown",
                     "excludes": r.get("not_included") or data.get("not_included") or None, "operated_by": data.get("operated_by") or "not shown", "know_before": data.get("additional") or "not shown",
                     "seats_left": str(units) if units is not None else "not shown", "booking_rule": "an adult must be in the booking" if r.get("adult_required") else None}))
    if not data.get("rows") and not data.get("unavailable"):
        problems.append("no ticket price could be read: say it could not be read, never that the activity is sold out")
    if len(offers) > 1:
        notes.append("This activity has several ticket offers on that date: each has its own price, times and cancellation terms.")
    notes.append("Booking.com's price for this date and group: the sum of its own ticket prices, as the page's Total adds them up ('Includes taxes and charges'); the activity's page is the quoted source. The 'from' price in the list is only the lowest starting price.")
    n = len(offers)
    return SiteRows(offers=offers, read=n, total=n, problems=problems, extra_notes=notes, read_rows=True)      # one activity per run: the runs add up (27 Oct 2026: "2 of 1 read")


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="booking_attraction_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def booking_attraction_recipe_tool(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None, free_cancellation: bool = False) -> dict[str, Any]:
        """FOR THE EXACT PRICE OF ONE BOOKING.COM ACTIVITY on a date for a group (COMPARISON ONLY): use the activity link from booking_attractions_recipe (the `link` of a row; never guess a link). Give `adults` and
        `children_ages` (the ages of everyone who is not a plain adult: children, and seniors for their own ticket; [] if none) as the operator said (ask if not said); `activity` = the itinerary activity this answers (it names the row group); `free_cancellation` only if the operator asked for it. It returns the
        url (date and euro in the address) and a read-only SCRIPT: open the url, run it with the javascript tool; it asks Booking.com's own availability service for that date (every ticket offer with the group's price, each
        traveller in the kind whose age range holds their age, the time slots and the cancellation terms), sends its answer to the server by itself and returns a short receipt (`ingest` id): then call compose_answer with
        `runs`=[that id] and the returned `wishes`; never type or pass a row. If Booking.com lists no time on the date the answer says so (never 'sold out'). It never presses Next, Book, Reserve or Pay. A human check
        (captcha) is never worked around: stop and tell the operator. One call per activity. The server reads it first in its own Chrome (a short receipt with an `ingest` id: only compose_answer with `runs`=[that id]); if `server_read` says it could not, read the url in Claude in Chrome. Never retry the server's read."""
        try:
            out = booking_attraction_recipe(url, day, adults, children_ages, activity)
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {})}
        out["filters_used"] = ["Date and group as the operator said (operator)", "Free cancellation only (operator)" if free_cancellation else "All ticket options of the activity for that date (default: no option filter)",
                               "Prices in EUR (server default)"]
        return await server_first(NAME, "BOOKING_ATTRACTION_READ_IN_SERVER", "https://www.booking.com", out)
