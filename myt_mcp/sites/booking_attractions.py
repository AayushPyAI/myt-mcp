"""Booking.com attractions (the LIST of a city's activities for a day; COMPARISON ONLY: the price for a date and a group is on the activity's own page), read in the operator's own Chrome (a site module).

Site rules (found on the real page, 27 Oct 2026): the address is booking.com/attractions/searchresults/<country>/<city>.html?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&adults=N&selected_currency=EUR (the site
redirects to <city>.en-gb.html and keeps these values; sort_by in the address is not honoured, the order stays "Our top picks"); 15 cards load first and 15 more with each scroll (45 after two); the page does
not say how many exist; a card has the title, the review score and count, "Duration: 9 hours" (not on every card), "Free cancellation available" (not on every card), "#1 Best seller", and the LOWEST starting
price per person ("From", with the discounted "Current price from" when there is one). No connect-src in the page's CSP, no human check seen. A place is the <country>/<city> part of the address; only Lisbon is
known here. A human check is never worked around.
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
from myt_mcp.sites import SiteRows, with_emit

NAME = "booking_attractions"
SOURCE = "Booking.com attractions (public website price)"
GROUP = "Activities"
HERE = Path(__file__).parent
BATCH = 30
PAGE_KEYS = ("place", "day", "day_to", "adults", "currency")      # what the script checks in the page's own address


def places() -> dict[str, dict[str, str]]:
    data = json.loads((HERE / "booking_attractions.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def booking_attractions_recipe(place_path: str, place_name: str, day: date, adults: int = 2, limit: int = BATCH, title_contains: list[str] | None = None, free_cancellation: bool = False,
                               max_price: float | None = None, min_rating: float | None = None) -> dict[str, Any]:
    place_path = place_path.strip().lower()
    if not re.fullmatch(r"[a-z]{2}/[a-z0-9-]+", place_path):
        raise ValueError("the place is '<country code>/<city>' as in the site's address (pt/lisbon)")
    if not 1 <= adults <= 8 or not 1 <= limit <= 60:
        raise ValueError("adults must be 1-8 and limit 1-60")
    words = [w.lower() for w in (title_contains or []) if w.strip()]
    expect = {"place": place_path, "day": day.isoformat(), "day_to": day.isoformat(), "adults": adults, "currency": "EUR", "title_contains": words, "free_cancellation": free_cancellation,
              "max_price": max_price, "min_rating": min_rating, "group": f"Booking.com attractions in {place_name}, {day:%d %b %Y}"}
    url = f"https://www.booking.com/attractions/searchresults/{place_path}.html?date_from={day.isoformat()}&date_to={day.isoformat()}&adults={adults}&selected_currency=EUR"
    script = with_emit((HERE / "booking_attractions.js").read_text(encoding="utf-8")).replace("__EXPECT__", json.dumps({k: expect[k] for k in PAGE_KEYS})).replace("__LIMIT__", str(limit))
    return {"url": url, "script": script, "expect": expect}


def _hours(text: str | None) -> float | None:
    if not text:
        return None
    h = re.search(r"(\d+(?:\.\d+)?)\s*hours?", text, re.I)
    m = re.search(r"(\d+)\s*minutes?", text, re.I)
    return (float(h.group(1)) if h else 0.0) + (int(m.group(1)) / 60 if m else 0.0) if (h or m) else None


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Booking.com result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Booking.com script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    if data.get("unparsed"):
        problems.append(f"Booking.com wrote an activity card in a form the reader does not know ({str(data['unparsed'][0])[:80]}...): the page may have changed; read it by hand and say so")
    form = data.get("form") or {}
    for k in PAGE_KEYS:
        if exp.get(k) is not None and form.get(k) != exp[k]:
            problems.append(f"the page searched {k} {form.get(k)} instead of {exp[k]}: open the url again")
    offers: list[Offer] = []
    padding = 0
    for r in data.get("rows", []):
        if r.get("cur") != "€":
            problems.append(f"a Booking.com price is in '{r.get('cur')}', not euro: open the url again (the address asks selected_currency=EUR)")
            continue
        title = r.get("title") or ""
        checks: list[bool | None] = []
        if exp:
            if exp.get("title_contains"):
                if not any(w in title.lower() for w in exp["title_contains"]):
                    padding += 1        # the list is the whole city's, in the site's own order: a card without the wish's words is left out altogether
                    continue
                checks.append(True)
            if exp.get("max_price") is not None:
                checks.append(None if r.get("from") is None else r["from"] <= exp["max_price"])
            if exp.get("min_rating") is not None:
                checks.append(None if r.get("rating") is None else r["rating"] >= exp["min_rating"])
            if exp.get("free_cancellation"):
                checks.append(True if r.get("free_cancel") else None)
        fits = None if not checks else (False if False in checks else (None if None in checks else True))
        rating = f"{r['rating']:g} ({r['reviews']:,} reviews)" if r.get("rating") is not None and r.get("reviews") is not None else (f"{r['rating']:g}" if r.get("rating") is not None else "not shown")
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=title, price_total=r.get("from"), currency="EUR",
            price_basis="'from' price = the lowest starting price per person in the list (not for the date and the group: that is on the activity's page)" + (f"; was EUR {r['was']:g} before the discount" if r.get("was") and r["was"] != r.get("from") else ""),
            fits=fits, quotable=False, supplier="Booking.com", link=("https://www.booking.com" + r["path"]) if r.get("path") and r["path"].startswith("/") else r.get("path"),
            details={"duration": r.get("duration") or "not shown on the card", "start_times": "check the activity page for the date", "language": "not shown on the list", "meeting_point": "not shown on the list",
                     "cancellation": "Free cancellation (tag on the card)" if r.get("free_cancel") else "not shown on the list", "private_or_group": "not shown on the list", "rating": rating,
                     "badges": ", ".join(x for x in (f"#{r['best_seller']} Best seller" if r.get("best_seller") else None, r.get("available_from")) if x) or None}))
    notes = ["Booking.com's list shows only the lowest starting price per person: for the price for the date and the group open the activity's page for the best two or three. The list is in the site's own order (Our top picks), not by price."]
    notes.append("The page does not say how many activities exist for this search, so 'N of N' counts only the cards read by scrolling.")
    if padding:
        notes.append(f"{padding} of these cards have none of the wish's title words ({', '.join(exp.get('title_contains') or [])}): the list is the whole city's, so they are left out of the table and the picks.")
    if not data.get("rows") and not problems:
        problems.append("no activity card could be read: say it could not be read, never that there are none")
    count = len(data.get("rows", []))
    return SiteRows(offers=offers, read=count, total=count, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="booking_attractions_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def booking_attractions_recipe_tool(place: str, day: date, adults: int = 2, title_contains: list[str] | None = None, free_cancellation: bool | None = None, max_price: float | None = None,
                                              min_rating: float | None = None, place_path: str | None = None, limit: int = BATCH) -> dict[str, Any]:
        """FOR BOOKING.COM ATTRACTIONS (COMPARISON ONLY; the LIST of a city's activities for one day; read in the operator's own Chrome with Claude in Chrome), next to GetYourGuide and Viator. `place` is the
        city (Lisbon is known; for another city give `place_path` as in the site's address, '<country code>/<city>', e.g. pt/porto, learned by searching it once on the site). Optional wishes: `title_contains`
        (words that must be in the title, e.g. ["sintra"], the list is the whole city's), `free_cancellation`, `max_price` (EUR per person), `min_rating`. It returns the results url (day, adults and
        euro in it) and a read-only SCRIPT: open the url, run the script with the javascript tool; it scrolls to load up to `limit` activities and sends its whole answer from the page to the server by itself,
        and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. The price is the lowest starting
        price per person: for the group price of a date open the activity's page for the best two or three. A human check (captcha) is never worked around: stop and tell the operator."""
        known = places().get(place.strip().lower())
        if place_path:
            path, name = place_path, place.strip() or place_path
        elif known:
            path, name = known["path"], known["name"]
        else:
            return {"ok": False, "searched": False, "known_places": [v["name"] for v in places().values()],
                    "next": "Nothing was opened. That city is not known yet: search it once on booking.com/attractions in Claude in Chrome, read '<country code>/<city>' from the results address "
                            "(booking.com/attractions/searchresults/pt/porto.html is pt/porto), then call this tool again with place_path."}
        try:
            out = booking_attractions_recipe(path, name, day, adults, limit, title_contains, bool(free_cancellation), max_price, min_rating)
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        out["wishes"] = {"expect": out["expect"]}
        out["filters_used"] = [f"Day {day.isoformat()} and {adults} adults (operator)", "Prices in EUR (server default)"] + \
            ([f"Title has one of: {', '.join(out['expect']['title_contains'])} (operator)"] if out["expect"]["title_contains"] else []) + \
            (["Free cancellation (operator)"] if free_cancellation else []) + ([f"Max {max_price:g} EUR per person (operator)"] if max_price is not None else []) + \
            ([f"Rating {min_rating:g} or more (operator)"] if min_rating is not None else [])
        return out
