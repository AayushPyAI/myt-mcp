"""GetYourGuide search (the LIST of activities for a query and a date; COMPARISON ONLY: the exact group price comes from getyourguide_activity_recipe), read in the operator's own Chrome.

Site rules (found on the real page, 22 Oct 2026): the search is www.getyourguide.com/s/?q=<text>&date_from=<day>&date_to=<day>; 24 cards a page in GetYourGuide's own order, a "Show more" button adds the next 24;
after the relevant results the list is padded with other activities of the city (a "Pasta Cooking Class" under "golf cart tour"), so the title words of the wish decide what fits; every card is an anchor to
.../<slug>-t<id>/ with lines: badges (Top pick, Top rated, Certified by GetYourGuide...), CITY, title, "1.5 hours • Private group • Optional audio guide", rating, (reviews), "From", price. The price shown
is the LOWEST starting price in the currency of the header menu (EN/ILS for an Israeli browser); it must be EUR. The card does not say whether the price is per person or per group.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, read_in_server_browser, server_reads, with_emit

NAME = "getyourguide_find"
SOURCE = "GetYourGuide"
GROUP = "Activities"
HERE = Path(__file__).parent
BATCH = 48          # the first 24 and, after "Show more", the next 24
ASK = {"cancel": "Free cancellation required, or any?", "budget": "Budget: the most per person (EUR), or no limit?", "duration": "Longest acceptable duration in hours (or time of day wish), or no limit?"}
EUR = {"€", "EUR"}
STOP = {"tour", "tours", "the", "and", "of", "in", "a", "with", "to", "from", "for", "day", "trip"}


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2]


def getyourguide_find_recipe(query: str, day: date | None = None, limit: int = BATCH, offset: int = 0, title_contains: list[str] | None = None, free_cancellation: bool = False,
                             max_price: float | None = None, min_rating: float | None = None, max_hours: float | None = None) -> dict[str, Any]:
    q = " ".join((query or "").split())
    if not q or len(q) > 120:
        raise ValueError("query is empty or too long (for example 'Florence golf cart tour')")
    if not 1 <= limit <= 72 or offset < 0 or (max_price is not None and max_price <= 0) or (max_hours is not None and max_hours <= 0) or (min_rating is not None and not 0 < min_rating <= 5):
        raise ValueError("limit 1-72, offset 0 or more, max_price and max_hours above 0, min_rating 0-5")
    params = {"q": q, **({"date_from": day.isoformat(), "date_to": day.isoformat()} if day else {})}
    url = "https://www.getyourguide.com/s/?" + urlencode(params)
    script = with_emit((HERE / "getyourguide_find.js").read_text(encoding="utf-8")).replace("__LIMIT__", str(limit)).replace("__SKIP__", str(offset))
    must = [w.lower() for w in (title_contains or words(q))]
    expect = {"query": q, "day": day.isoformat() if day else None, "group": f"{q}, {day:%d %b %Y}" if day else q, "title_contains": must, "free_cancellation": free_cancellation,
              "max_price": max_price, "min_rating": min_rating, "max_hours": max_hours}
    return {"url": url, "script": script, "expect": expect}


def _hours(meta: str | None) -> float | None:
    """'1.5 hours - 105 minutes' -> the longest number it names, in hours; '2 - 2.5 hours' -> 2.5; '45 minutes' -> 0.75."""
    t = (meta or "").split("•")[0].lower()
    nums = [(float(n), unit) for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(hour|hr|minute|min|day)", t)]
    if not nums:
        m = re.findall(r"\d+(?:\.\d+)?", t)
        return max(float(x) for x in m) if m and "hour" in t else None
    return max(n * {"hour": 1, "hr": 1, "minute": 1 / 60, "min": 1 / 60, "day": 24}[unit] for n, unit in nums)


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    try:
        data = json.loads(result_json)
    except (TypeError, ValueError):
        return SiteRows(problems=["the GetYourGuide result is not the script's JSON text: pass its answer unchanged"])
    if not data.get("ok"):
        return SiteRows(problems=[f"the GetYourGuide script reported: {data.get('error', 'not ok')}"])
    exp = wishes.get("expect") or {}
    problems: list[str] = []
    rows = data.get("rows", [])
    if exp:
        if (data.get("query_text") or "").strip().lower() != exp["query"].lower():
            problems.append(f"the page searched '{data.get('query_text')}', not '{exp['query']}': open the url again")
        if exp.get("day"):
            d = date.fromisoformat(exp["day"])
            if data.get("date_chip") != f"{d:%b} {d.day}":
                problems.append(f"the page's date is '{data.get('date_chip')}', not {d:%b} {d.day}: open the url again (the date is in the address)")
    if rows and (data.get("header_currency") not in (None, "EUR")):
        problems.append(f"the page shows prices in {data['header_currency']}, not EUR: open the header menu (EN/...), choose Euro (EUR), open the url again and run the script again")
    offers: list[Offer] = []
    padding = 0
    for r in rows:
        if r.get("from") is not None and r.get("symbol") not in EUR:
            problems.append(f"the card '{r.get('title')}' shows '{r.get('symbol')}' prices, not EUR: set the header menu to Euro and run the script again")
            break
        meta = r.get("meta") or ""
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
                h = _hours(meta)
                checks.append(None if h is None else h <= exp["max_hours"])
            if exp.get("free_cancellation"):
                checks.append(True if "Free cancellation" in (r.get("tags") or []) else None)
        fits = None if not checks else (False if False in checks else (None if None in checks else True))
        kind = "private group" if "private" in meta.lower() else ("small group" if "small group" in meta.lower() else ("group" if "group" in meta.lower() else "not shown on the list"))
        offers.append(Offer(
            group=exp.get("group") or group, source=SOURCE, name=title, price_total=r.get("from"), currency="EUR" if r.get("from") is not None else None,
            price_basis="'from' price = the lowest starting price in the list (the card does not say per person or per group); the exact group price comes from getyourguide_activity_recipe",
            fits=fits, quotable=False, supplier="GetYourGuide", link=("https://www.getyourguide.com" + r["path"]) if r.get("path") else None,
            details={"duration": meta.split("•")[0].strip() or "not shown", "start_times": "check the activity page for the date", "language": ("audio guide optional" if "audio guide" in meta.lower() else "not shown on the list"),
                     "meeting_point": "not shown on the list", "cancellation": "Free cancellation (tag on the card)" if "Free cancellation" in (r.get("tags") or []) else "not shown on the list", "private_or_group": kind,
                     "rating": f"{r.get('rating')} ({r.get('reviews'):,} reviews)" if r.get("rating") is not None and r.get("reviews") is not None else (f"{r.get('rating')}" if r.get("rating") is not None else "not shown"),
                     "badges": ", ".join(r.get("tags") or []) or None}))
    offset = int(data.get("offset") or 0)
    notes = ["GetYourGuide's list shows only the lowest starting price (EUR): for the price of the whole group for a date, call getyourguide_activity_recipe for the best two or three."]
    if padding:
        notes.append(f"{padding} of these results have none of the wish's title words ({', '.join(exp.get('title_contains') or [])}): GetYourGuide pads the list with other activities of the city; they are left out of the table and the picks.")
    if offset:
        notes.append(f"These are results {offset + 1} to {offset + len(rows)} in GetYourGuide's own order.")
    total = int(re.sub(r"\D", "", data.get("results_total") or "") or 0) or None
    return SiteRows(offers=offers, read=len(rows), total=total, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="getyourguide_find_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def getyourguide_find_recipe_tool(query: str, day: date | None = None, free_cancellation: bool | None = None, max_price: float | None = None, max_hours: float | None = None,
                                            min_rating: float | None = None, title_contains: list[str] | None = None, operator_answered: bool = False, limit: int = BATCH,
                                            offset: int = 0) -> dict[str, Any]:
        """FOR GETYOURGUIDE TOURS AND ACTIVITIES (the list; read in the operator's own Chrome with Claude in Chrome). ASK FIRST: without `free_cancellation` (true/false), `max_price` (EUR per person) and
        `max_hours` it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers (`operator_answered`=true for "no preference", only after the operator replied). Then THE SERVER READS THE LIST ITSELF in its own browser (getyourguide.com's security policy stops the operator's Chrome from sending data to the server) and returns a short receipt with an `ingest` id: call compose_answer with `runs`=[that id]; no Chrome action is needed (ok=false: say the source could not be read). Without a server browser it returns the search url (query and date in the address) and a read-only SCRIPT: open the url, run the script with the javascript tool (it reads `limit` cards from `offset` in GetYourGuide's own order,
        pressing "Show more" if needed; title, link, duration, rating, reviews, the "from" price). The script sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. `query` = the activity as in the itinerary ("Florence golf cart tour"); `title_contains` = words a title must hold (default: the
        query's words; GetYourGuide pads the list with unrelated activities). The header menu must show EUR (the script says if it does not). These rows are comparison only: for the exact price of the
        group on the date call getyourguide_activity_recipe for the best two or three (it needs their links). A human check is never worked around: stop and tell the operator."""
        asked = ((ASK["cancel"], free_cancellation is not None), (ASK["budget"], max_price is not None), (ASK["duration"], max_hours is not None))
        missing = [q for q, given in asked if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date and the travellers with the children's ages only if the request did not say them), wait for the reply, then call "
                            "this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = getyourguide_find_recipe(query, day, limit, offset, title_contains, bool(free_cancellation), max_price, min_rating, max_hours)
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {}), **({"max_price": max_price} if max_price is not None else {})}
        src = lambda v: "operator" if v is not None else "default: no preference"       # noqa: E731
        out["filters_used"] = [("Free cancellation only (operator)" if free_cancellation else f"Any cancellation ({src(free_cancellation)})"),
                               (f"At most {max_price:g} EUR per person (operator)" if max_price is not None else f"No price limit ({src(max_price)})"),
                               (f"At most {max_hours:g} hours (operator)" if max_hours is not None else f"No duration limit ({src(max_hours)})"), f"Titles holding any of: {', '.join(out['expect']['title_contains'])} (the wish's own words)"]
        out["more"] = f"For the next {limit} results call this tool again with the same values and offset={offset + limit}."
        if server_reads("GYG_FIND_READ_IN_SERVER"):
            # getyourguide.com's security policy only lets the page talk to its own hosts: the server reads the list itself in its automation Chrome
            result = await read_in_server_browser(NAME, "https://www.getyourguide.com", out["url"], out)
            result["more"] = out["more"]
            return result
        return out
