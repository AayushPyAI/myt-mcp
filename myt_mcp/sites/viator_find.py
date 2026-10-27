"""Viator search (the LIST of activities for a query; COMPARISON ONLY: the exact group price comes from viator_activity_recipe), read in the operator's own Chrome.

Site rules (found on the real page, 22 Oct 2026): the search is www.viator.com/searchResults/all?text=<text> for page 1 and www.viator.com/searchResults/all/<n>?text=<text> for page n (24 results a page, Viator's own
"Featured" order; there is no price sort in the address; "&page=" is ignored); every card is an anchor to /tours/<place>/<slug>/d<id>-<code> with lines: the title, "1 hour 40 minutes" + "Free Cancellation" (one line),
rating, (reviews), "from €73" (a discount shows the old and the new price: "from €54 €48"), sometimes "Price varies by group size" and "Special Offer". The price is per person; the search shows 2 adults by default. The
prices follow the visitor's currency (the globe menu): it must be EUR. Nothing is booked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, server_first, with_emit
from myt_mcp.sites.getyourguide_find import words

NAME = "viator_find"
SOURCE = "Viator"
GROUP = "Activities"
RESULT_MARKS = {"query_text", "results_total"}      # keys only this recipe's answers have: a display name that fits a list recipe and a page recipe is told apart by them (resolve_site_names)
HERE = Path(__file__).parent
ASK = {"cancel": "Free cancellation required, or any?", "budget": "Budget: the most per person (EUR), or no limit?", "duration": "Longest acceptable duration in hours (or time of day wish), or no limit?"}
EUR = {"€", "EUR"}


def search_url(query: str, page: int) -> str:
    base = "https://www.viator.com/searchResults/all" + (f"/{page}" if page > 1 else "")
    return f"{base}?{urlencode({'text': query})}"


def viator_find_recipe(query: str, day_label: str | None = None, page: int = 1, title_contains: list[str] | None = None, free_cancellation: bool = False, max_price: float | None = None,
                       min_rating: float | None = None, max_hours: float | None = None) -> dict[str, Any]:
    if min_rating is not None and min_rating > 5:      # the operator's "rating 9 and up" is on Booking.com's 10-point scale; this site rates on 5 points (27 Oct 2026: 9 was refused, then 4.9 was 'not 9')
        min_rating = round(min_rating / 2, 2)
    q = " ".join((query or "").split())
    if not q or len(q) > 120:
        raise ValueError("query is empty or too long (for example 'Florence golf cart tour')")
    if not 1 <= page <= 9 or (max_price is not None and max_price <= 0) or (max_hours is not None and max_hours <= 0) or (min_rating is not None and not 0 < min_rating <= 5):
        raise ValueError("page 1-9, max_price and max_hours above 0, min_rating 0-5")
    script = with_emit((HERE / "viator_find.js").read_text(encoding="utf-8"))
    must = [w.lower() for w in (title_contains or words(q))]
    expect = {"query": q, "page": page, "group": f"{q}, {day_label}" if day_label else q, "title_contains": must, "free_cancellation": free_cancellation, "max_price": max_price, "min_rating": min_rating, "max_hours": max_hours}
    return {"url": search_url(q, page), "script": script, "expect": expect}


def hours(duration: str | None) -> float | None:
    """'1 hour 2 minutes to 1 hour 38 minutes' -> 1.63; '1 hour 40 minutes' -> 1.67; '2 hours' -> 2; '3 days' -> 72; nothing readable -> None."""
    best = None
    for part in re.split(r"\s+to\s+|\s+-\s+", (duration or "").lower()):
        h = sum(float(n) * {"day": 24, "hour": 1, "hr": 1, "minute": 1 / 60, "min": 1 / 60}[u] for n, u in re.findall(r"(\d+(?:\.\d+)?)\s*(day|hour|hr|minute|min)", part))
        best = max(best or 0, h) if h else best
    return best


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the Viator result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the Viator script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    rows = data.get("rows", [])
    if exp:
        if (data.get("query_text") or "").strip().lower() != exp["query"].lower():
            problems.append(f"the page searched '{data.get('query_text')}', not '{exp['query']}': open the url again")
        if data.get("page") != exp["page"]:
            problems.append(f"the page is result page {data.get('page')}, not {exp['page']}: open the url again")
    offers: list[Offer] = []
    padding = 0
    for r in rows:
        if r.get("from") is not None and r.get("symbol") not in EUR:
            problems.append(f"the card '{r.get('title')}' shows '{r.get('symbol')}' prices, not EUR: open the globe menu, choose the currency EUR, open the url again and run the script again")
            break
        title = r.get("title") or "activity"
        checks: list[bool | None] = []
        if exp:
            if exp.get("title_contains"):
                hit = any(w in title.lower() for w in exp["title_contains"])
                if not hit:
                    padding += 1        # the site pads its list with other activities of the city: they are left out altogether (a kayak must not become "Cheapest" of a whale-watching search)
                    continue
                checks.append(hit)
            if exp.get("max_price") is not None:
                checks.append(None if r.get("from") is None else r["from"] <= exp["max_price"])
            if exp.get("min_rating") is not None:
                checks.append(None if r.get("rating") is None else r["rating"] >= exp["min_rating"])
            if exp.get("max_hours") is not None:
                h = hours(r.get("duration"))
                checks.append(None if h is None else h <= exp["max_hours"])
            if exp.get("free_cancellation"):
                checks.append(bool(r.get("free_cancel")))
        fits = None if not checks else (False if False in checks else (None if None in checks else True))
        basis = "'from' price per person (the lowest, for the default group of 2 adults)" + (f"; discounted from {r['was']:g} EUR" if r.get("was") else "") + ("; varies by group size" if r.get("varies") else "")
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=title, price_total=r.get("from"), currency="EUR" if r.get("from") is not None else None,
            price_basis=basis + "; the exact group price comes from viator_activity_recipe", fits=fits, quotable=False, supplier="Viator",
            flexible=True if r.get("free_cancel") else None, link=("https://www.viator.com" + r["path"]) if r.get("path") else None,
            details={"duration": r.get("duration") or "not shown", "start_times": "check the activity page for the date", "language": "not shown on the list", "meeting_point": "not shown on the list",
                     "cancellation": "Free Cancellation (tag on the card)" if r.get("free_cancel") else "not shown on the list", "private_or_group": "private" if "private" in title.lower() else "not shown on the list",
                     "rating": f"{r.get('rating')} ({r.get('reviews'):,} reviews)" if r.get("rating") is not None and r.get("reviews") is not None else (f"{r.get('rating')}" if r.get("rating") is not None else "not shown"),
                     "badges": ", ".join(r.get("tags") or []) or None}))
    notes = ["Viator's list shows only the lowest 'from' price per person (EUR) in its own 'Featured' order (no price sort): for the price of the whole group for a date call viator_activity_recipe for the best two or three."]
    if padding:
        notes.append(f"{padding} of these results have none of the wish's title words ({', '.join(exp.get('title_contains') or [])}): Viator pads the list with other activities; they are left out of the table and the picks.")
    if data.get("page", 1) > 1:
        notes.append(f"This is result page {data['page']} ({data.get('shown_range') or 'range not shown'}) of Viator's own order.")
    total = int(re.sub(r"\D", "", data.get("results_total") or "") or 0) or None
    return SiteRows(offers=offers, read=len(rows), total=total, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="viator_find_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def viator_find_recipe_tool(query: str, day_label: str | None = None, free_cancellation: bool | None = None, max_price: float | None = None, max_hours: float | None = None,
                                      min_rating: float | None = None, title_contains: list[str] | None = None, operator_answered: bool = False, page: int = 1) -> dict[str, Any]:
        """FOR VIATOR TOURS AND ACTIVITIES (the list; read in the operator's own Chrome with Claude in Chrome). ASK FIRST: without `free_cancellation` (true/false), `max_price` (EUR per person) and `max_hours`
        it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers (`operator_answered`=true for "no preference", only after the operator replied). Then THE SERVER READS THE LIST ITSELF in its own browser (viator.com's pages stop the operator's Chrome from sending data to the server) and returns a short receipt with an `ingest` id: call compose_answer with `runs`=[that id]; no Chrome action is needed (ok=false: put Viator in not_checked with the reason it gives). Without a server browser it returns the search url and a read-only SCRIPT: open the url, run the script with the javascript tool (it reads the 24 cards of that result page in Viator's own 'Featured' order: title, link, duration, Free
        Cancellation tag, rating, reviews, the 'from' price per person). For more call again with page=page+1 (up to 9). The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. `query` = the activity as in the itinerary ("Florence golf cart tour"); `day_label` = the date text
        for the row group ("5 Mar 2027"); `title_contains` = words a title must hold (default: the query's words; Viator pads the list). The page must show EUR (the script says if it does not). These rows are
        comparison only: for the exact price of the group on the date call viator_activity_recipe for the best two or three. A human check is never worked around: stop and tell the operator."""
        asked = ((ASK["cancel"], free_cancellation is not None), (ASK["budget"], max_price is not None), (ASK["duration"], max_hours is not None))
        missing = [q for q, given in asked if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date and the travellers with the children's ages only if the request did not say them), wait for the reply, then call "
                            "this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = viator_find_recipe(query, day_label, page, title_contains, bool(free_cancellation), max_price, min_rating, max_hours)
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {}), **({"max_price": max_price} if max_price is not None else {})}
        src = lambda v: "operator" if v is not None else "default: no preference"       # noqa: E731
        out["filters_used"] = [("Free cancellation only (operator)" if free_cancellation else f"Any cancellation ({src(free_cancellation)})"),
                               (f"At most {max_price:g} EUR per person (operator)" if max_price is not None else f"No price limit ({src(max_price)})"),
                               (f"At most {max_hours:g} hours (operator)" if max_hours is not None else f"No duration limit ({src(max_hours)})"), f"Titles holding any of: {', '.join(out['expect']['title_contains'])} (the wish's own words)"]
        out["more"] = f"For the next 24 results call this tool again with the same values and page={page + 1}."
        # viator.com's pages carry a Content-Security-Policy in a <meta> tag that stops the page from sending data to this server (24 Oct 2026): the server reads the list itself, slowly (15 s apart, 20 an hour);
        # when it cannot (27 Oct 2026: "not a Viator search page" twice) the recipe comes back for the operator's Chrome, whose script returns the rows in parts
        result = await server_first(NAME, "VIATOR_FIND_READ_IN_SERVER", "https://www.viator.com", out)
        result["more"] = out["more"]
        return result
