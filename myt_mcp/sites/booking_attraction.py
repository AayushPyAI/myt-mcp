"""Booking.com attractions: the price of ONE activity for a date and a group (COMPARISON ONLY; a site module, see myt_mcp/sites/__init__.py), read in the operator's own Chrome.

Site rules (found on the real page, 27 Oct 2026): the activity page is booking.com/attractions/<country>/<slug>.html (the site redirects to <slug>.en-gb.html); with ?date=YYYY-MM-DD&selected_currency=EUR in the
address the ticket box (data-testid inline-ticket-config) shows that date (the chosen one has aria-pressed="true"), or "Your selected date is unavailable, please choose another one" and no tickets. The box
has the "Select time" radios (data-testid timeslot-option, "Show more" doubles them), "Ticket" with the ticket's own wording ("Non-refundable"), one stepper per kind of ticket ("Adult (age 13-64)", "Child
(age 3-12)", "Senior (age 65+)", "Infant (age 0-2)": the kinds and age ranges differ per activity) with its price and an <input type=range> that holds the count, and the site's own "Total ... Includes taxes
and charges" for the whole group. The script sets the counts (each traveller in the kind whose age range holds the age; the adults in "Adult"), reads that Total, and never presses "Next" (the first booking step).
The list (booking_attractions) shows only a "from" price; this is the price to quote from. No connect-src in the page's CSP, no human check seen. A human check is never worked around.
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
from myt_mcp.sites import SiteRows, clock24, server_first, with_emit

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
    if not 0 <= adults <= MAX_TRAVELLERS or not 1 <= adults + len(ages) <= MAX_TRAVELLERS or any(not 0 <= a <= 17 for a in ages):
        raise ValueError(f"travellers must be 1-{MAX_TRAVELLERS} in total, adults 0-{MAX_TRAVELLERS}, children's ages 0-17")
    if adults < 1:
        raise ValueError("at least one adult is needed: a child is booked with an adult (the site says so)")
    cc, slug = m.group(1), m.group(2)
    link = f"https://www.booking.com/attractions/{cc}/{slug}.html?date={day.isoformat()}&selected_currency=EUR"
    expect = {"slug": slug, "day": day.isoformat(), "day_label": f"{day:%a} {day.day} {day:%b}", "adults": adults, "children": len(ages), "ages": ages, "total": adults + len(ages), "currency": "EUR",
              "group": f"{(activity or 'Activity').strip()}, {day:%d %b %Y}"}
    page_expect = {k: expect[k] for k in ("slug", "day_label", "adults", "ages")}
    script = with_emit((HERE / "booking_attraction.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps(page_expect))
    return {"url": link, "script": script, "expect": expect}


def _num(v: float | None) -> str:
    return "not shown" if v is None else f"{v:,.2f}"


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Booking.com result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Booking.com script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    form = data.get("form") or {}
    if exp.get("slug") and form.get("slug") != exp["slug"]:
        problems.append(f"the page is the activity '{form.get('slug')}', not '{exp['slug']}': open the url again")
    if exp.get("currency") and form.get("currency") != exp["currency"]:
        problems.append(f"the page's currency in the address is {form.get('currency')}, not {exp['currency']}: open the url again")
    notes: list[str] = []
    if data.get("unavailable"):
        notes.append(f"Booking.com says for {exp.get('day', 'the date asked')}: {data['unavailable']}. It may be sold out or simply not open yet for that date: it is not a price, and never 'sold out' from this alone.")
        return SiteRows(offers=[], read=0, total=0, problems=problems, extra_notes=notes, read_rows=True, total_absolute=True)
    offers: list[Offer] = []
    for r in data.get("rows", []):
        if r.get("symbol") != "€":
            problems.append(f"the page shows the total in '{r.get('symbol')}', not euro: open the url again (the address asks selected_currency=EUR)")
            continue
        if r.get("total") in (None, 0):
            problems.append("the page shows no total for the group: the tickets could not be set; say it could not be quoted")
            continue
        kinds = r.get("kinds") or []
        wrong = [k for k in kinds if k.get("count") != k.get("wanted")]
        if wrong:
            problems.append("the ticket counts on the page are not the group asked (" + ", ".join(f"{k.get('label')}: {k.get('count')} instead of {k.get('wanted')}" for k in wrong) + "): set them and run the script once more")
            continue
        used = [k for k in kinds if k.get("count")]
        breakdown = "; ".join(f"{k['count']} x {k['label']} at {_num(k.get('price'))}" for k in used) or "breakdown not shown"
        computed = r.get("computed")
        if computed is not None and abs(computed - r["total"]) > 0.015:
            notes.append(f"The page's total ({_num(r['total'])} EUR) differs from the tickets added up ({_num(computed)} EUR): the page's own total is shown.")
        ticket = r.get("ticket") or "not shown"
        free = bool(re.match(r"free cancellation|cancel for free", ticket, re.I))
        nonref = bool(re.search(r"non-?refundable|not refundable", ticket, re.I))
        times = [clock24(t) for t in (r.get("times") or [])]      # "10:00 AM" in the server's Chrome, "10:00" in the operator's: the same clock for both
        chosen_time = clock24(r.get("time_chosen")) if r.get("time_chosen") else None
        start = (f"{len(times)} start time(s): " + ", ".join(times[:6]) + (f", ... last {times[-1]}" if len(times) > 6 else "")) if times else "not shown"
        pax = exp.get("total") or sum(k.get("count") or 0 for k in kinds)
        fits = None
        if wishes.get("free_cancellation"):
            fits = True if free else (False if nonref else None)
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=(data.get("title") or "Booking.com activity") + (f" ({ticket})" if ticket != "not shown" else ""), price_total=r["total"], currency="EUR",
            price_basis=f"whole group ({pax} travellers; {breakdown}), " + ("taxes and charges included (the page says so)" if r.get("taxes") else "taxes not stated") + f", for {exp.get('day', 'the date asked')}",
            flexible=True if free else (False if nonref else None), fits=fits, quotable=False, supplier=data.get("operated_by") or "Booking.com",
            details={"duration": "not shown on the ticket box", "start_times": start + (f" (first chosen: {chosen_time}; the price is for the chosen time)" if chosen_time else ""), "language": "not shown on the ticket box",
                     "meeting_point": "not shown on the ticket box (see Location on the page)", "cancellation": ticket, "private_or_group": "not shown", "includes": data.get("includes") or "not shown",
                     "operated_by": data.get("operated_by") or "not shown", "know_before": data.get("additional") or "not shown"}))
    if not data.get("rows") and not data.get("unavailable"):
        problems.append("no ticket price could be read: say it could not be read, never that the activity is sold out")
    notes.append("Booking.com's price for this date and group, as the page's own Total; the activity's page is the quoted source. The 'from' price in the list is only the lowest starting price.")
    n = len(offers)
    return SiteRows(offers=offers, read=n, total=n, problems=problems, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="booking_attraction_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def booking_attraction_recipe_tool(url: str, day: date, adults: int, children_ages: list[int], activity: str | None = None, free_cancellation: bool = False) -> dict[str, Any]:
        """FOR THE EXACT PRICE OF ONE BOOKING.COM ACTIVITY on a date for a group (COMPARISON ONLY; read in the operator's own Chrome with Claude in Chrome): use the activity link from
        booking_attractions_recipe (the `link` of a row; never guess a link). Give `adults` and `children_ages` ([] if none) as the operator said (ask if not said); `activity` = the itinerary activity this answers
        (it names the row group); `free_cancellation` only if the operator asked for it. It returns the url (date and euro in the address) and a read-only SCRIPT: open the url, run the script with the javascript tool;
        it sets the number of tickets of each kind (each traveller in the kind whose age range holds the age) and reads the page's own Total for the group, the start times and the ticket's cancellation wording, and
        sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never
        type or pass a row. If the page says the date is unavailable the answer says so (never 'sold out'). It never presses Next, Book, Reserve or Pay. A human check (captcha) is never worked around: stop and tell
        the operator. One call per activity. SERVER FIRST: the server first reads this page itself in its own automation Chrome (the same script); then the answer is a short receipt with an `ingest` id and you only call compose_answer with `runs`=[that id]. If it could not (the answer then has `server_read` with the reason, and the url and script below), read the page in Claude in Chrome as described here. Never retry the server's read."""
        try:
            out = booking_attraction_recipe(url, day, adults, children_ages, activity)
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {})}
        out["filters_used"] = ["Date and group as the operator said (operator)", "Free cancellation only (operator)" if free_cancellation else "All ticket options of the activity for that date (default: no option filter)",
                               "Prices in EUR (server default)"]
        return await server_first(NAME, "BOOKING_ATTRACTION_READ_IN_SERVER", "https://www.booking.com", out)
