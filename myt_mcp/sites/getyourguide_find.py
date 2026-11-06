"""GetYourGuide search (the LIST of activities for a query and a date; COMPARISON ONLY: the exact group price comes from getyourguide_activity_recipe), read from GetYourGuide's own list service in the server's Chrome (or the operator's).

Site rules (read live 6 Nov 2026): the search page www.getyourguide.com/s/?q=<text>&date_from=<day>&date_to=<day> draws its cards from ONE call of its own, POST travelers-api.getyourguide.com/user-interface/landing-pages/srp/blocks,
24 cards a page; its "Show more" button, every filter and the sort send the same call with a bigger `page`, a `filtersUpdated` list or a `sortingSelected`. The script replays that call with the page's own template (taken from
the page's embedded state) and the same headers, so it gets exactly the cards the page shows, with fields the old page-text reading could only guess: the exact price (starting_price, the struck-through base_price of a deal,
"per person" or "per group"), rating and reviews, duration and flags in one line ("3 hours • Private option available • Skip the line"), badges (Top pick, Top rated, New), the tour id (its page is /-t<id>/, which redirects to the
full address), and the currency (the accept-currency header: EUR, whatever the visitor's header menu says). Filters the page offers and the script sends: reviewRatingRanges (3.0 3.5 4.0 4.5), durationRanges (0 = up to 3 hours, 1 = 3-5, 2 = 5-7, 3 = 7+ ...),
languages (en nl fr de hi it pl pt ru es), services (prt private tour, hpu hotel pickup, stl skip the line, sg small group, wca wheelchair, orig originals), price ({min, max} of the displayed price: for a private tour that is the price of the
group), sort (popularity, price_asc, price_desc, rating_desc). A list has no cancellation field: a free-cancellation wish stays "not confirmed" until the activity page is read. After the relevant results GetYourGuide pads the list with
other activities of the city, so the title words of the wish decide what fits.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer, mark_unconfirmed
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, server_first, with_emit

NAME = "getyourguide_find"
SOURCE = "GetYourGuide"
GROUP = "Activities"
RESULT_MARKS = {"query_text", "results_total"}      # keys only this recipe's answers have: a display name that fits a list recipe and a page recipe is told apart by them (resolve_site_names)
HERE = Path(__file__).parent
BATCH = 48          # two pages of 24
PER_PAGE = 24
ASK = {"cancel": "Free cancellation required, or any?", "budget": "Budget: the most per person (EUR), or no limit?", "duration": "Longest acceptable duration in hours (or time of day wish), or no limit?"}
EUR = {"€", "EUR"}
STOP = {"tour", "tours", "the", "and", "of", "in", "a", "with", "to", "from", "for", "day", "trip"}
SORTS = {"popularity": "popularity", "price": "price_asc", "price_desc": "price_desc", "rating": "rating_desc"}
SERVICES = {"private_tour": "prt", "hotel_pickup": "hpu", "skip_the_line": "stl", "small_group": "sg", "wheelchair": "wca", "originals": "orig"}
FILTER_LANGUAGES = ("en", "nl", "fr", "de", "hi", "it", "pl", "pt", "ru", "es")      # the languages GetYourGuide's own filter lists (Hebrew is not one of them)
LANGUAGE_NAMES = {"english": "en", "hebrew": "he", "dutch": "nl", "french": "fr", "german": "de", "hindi": "hi", "italian": "it", "polish": "pl", "portuguese": "pt", "russian": "ru", "spanish": "es", "chinese": "zh", "japanese": "ja", "arabic": "ar"}
RATING_STEPS = (3.0, 3.5, 4.0, 4.5)
DURATION_BUCKETS = ((0, 0.0), (1, 3.0), (2, 5.0), (3, 7.0))      # (filter value, the hours the bucket starts at): 0-3 h, 3-5 h, 5-7 h, 7+ h (full day)
BADGES = {"topPick": "Top pick", "topRated": "Top rated", "newActivity": "New"}


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2]


def language_code(text: str | None) -> str | None:
    key = (text or "").strip().lower()
    if not key:
        return None
    code = LANGUAGE_NAMES.get(key, key)
    if not re.fullmatch(r"[a-z]{2,3}", code):
        raise ValueError("language must be a language name or code such as English or en")
    return code


def filter_list(max_price: float | None, min_rating: float | None, max_hours: float | None, language: str | None, features: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The filters that go to GetYourGuide's own list call (a wish it cannot filter is judged by the server from the rows) and the sentences that say so. Every value sent keeps a product that meets the wish: the exact figure is judged here."""
    out: list[dict[str, Any]] = []
    said: list[str] = []
    if min_rating is not None and min_rating >= RATING_STEPS[0]:
        step = max(s for s in RATING_STEPS if s <= min_rating)
        out.append({"filterType": "reviewRatingRanges", "value": [f"{step:.1f}"]})
        said.append(f"the rating filter {step:.1f}+ (the exact rating is judged here)")
    if max_hours is not None and max_hours < 48:
        # the bucket "0" is 0-3 hours, "1" 3-5 hours ...: every bucket that STARTS at or below the limit stays in (whether 3 hours itself is in 0 or 1 is not stated), the exact duration is judged here
        values = [str(v) for v, start in DURATION_BUCKETS if start <= max_hours]
        out.append({"filterType": "durationRanges", "value": values})
        said.append(f"the duration filter for up to {max_hours:g} hours (buckets {', '.join(values)}; the exact duration is judged here)")
    if language and language in FILTER_LANGUAGES:
        out.append({"filterType": "languages", "value": [language]})
        said.append(f"the language filter {language}")
    if features:
        out.append({"filterType": "services", "value": [SERVICES[f] for f in features]})
        said.append("the service filter " + ", ".join(f.replace("_", " ") for f in features))
    if max_price is not None:
        out.append({"filterType": "price", "value": {"min": 0, "max": int(math.ceil(max_price))}})
        said.append(f"the price filter up to {math.ceil(max_price)} EUR (it looks at the displayed price: for a private tour that is the price of the whole group)")
    return out, said


def getyourguide_find_recipe(query: str, day: date | None = None, limit: int = BATCH, offset: int = 0, title_contains: list[str] | None = None, free_cancellation: bool = False,
                             max_price: float | None = None, min_rating: float | None = None, max_hours: float | None = None, language: str | None = None, features: list[str] | None = None,
                             sort: str | None = None) -> dict[str, Any]:
    if min_rating is not None and min_rating > 5:      # the operator's "rating 9 and up" is on Booking.com's 10-point scale; this site rates on 5 points (27 Oct 2026: 9 was refused, then 4.9 was 'not 9')
        min_rating = round(min_rating / 2, 2)
    q = " ".join((query or "").split())
    if not q or len(q) > 120:
        raise ValueError("query is empty or too long (for example 'Florence golf cart tour')")
    if not 1 <= limit <= 72 or offset < 0 or (max_price is not None and max_price <= 0) or (max_hours is not None and max_hours <= 0) or (min_rating is not None and not 0 < min_rating <= 5):
        raise ValueError("limit 1-72, offset 0 or more, max_price and max_hours above 0, min_rating 0-5")
    bad = [f for f in (features or []) if f not in SERVICES]
    if bad or (sort is not None and sort not in SORTS):
        raise ValueError(f"features are among {', '.join(SERVICES)}; sort is one of {', '.join(SORTS)}")
    lang = language_code(language)
    feats = list(dict.fromkeys(features or []))
    filters, said = filter_list(max_price, min_rating, max_hours, lang, feats)
    request = {"filters": filters, "sort": SORTS.get(sort or "popularity"), "limit": limit, "skip": offset}
    params = {"q": q, **({"date_from": day.isoformat(), "date_to": day.isoformat()} if day else {})}
    url = "https://www.getyourguide.com/s/?" + urlencode(params)
    script = with_emit((HERE / "getyourguide_find.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps(request))
    must = [w.lower() for w in (title_contains or words(q))]
    expect = {"query": q, "day": day.isoformat() if day else None, "group": f"{q}, {day:%d %b %Y}" if day else q, "title_contains": must, "free_cancellation": free_cancellation, "max_price": max_price,
              "min_rating": min_rating, "max_hours": max_hours, "language": lang, "features": feats, "sort": sort or "popularity", "filters": filters}
    return {"url": url, "script": script, "expect": expect, "filter_notes": said}


def _span(meta: str | None) -> tuple[float, float] | None:
    """'1.5 hours' -> (1.5, 1.5); '2 - 2.5 hours' -> (2, 2.5); '1 hour - 90 minutes' -> (1, 1.5); '45 minutes' -> (0.75, 0.75); '2 days' -> (48, 48); no duration -> None."""
    t = (meta or "").split("•")[0].lower()
    found = re.findall(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?|days?)?", t)
    values: list[float] = []
    unit_after: list[int] = []
    for i, (n, unit) in enumerate(found):
        values.append(float(n))
        if not unit:
            unit_after.append(i)
    if not values:
        return None
    units = [u for _, u in found]
    for i in range(len(units) - 1, -1, -1):      # a number without a unit takes the unit of the next one ("2 - 2.5 hours")
        if not units[i]:
            units[i] = units[i + 1] if i + 1 < len(units) else ""
    if not all(units):
        return None
    hours = [v * {"h": 1, "m": 1 / 60, "d": 24}[u[0]] for v, u in zip(values, units)]
    return min(hours), max(hours)


def _fits_hours(meta: str | None, limit: float) -> bool | None:
    """Within the limit: True; a tour that cannot be that short: False; a range that starts under the limit and ends over it, or no duration: not known (the option chosen decides)."""
    span = _span(meta)
    if span is None:
        return None
    return True if span[1] <= limit else (False if span[0] > limit else None)


def _kind(meta: str) -> str:
    low = meta.lower()
    if "private option" in low:
        return "private option available (a group tour with a private choice)"
    return "private group" if "private" in low else ("small group" if "small group" in low else ("group" if "group" in low else "not shown on the list"))


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
    if not rows and data.get("cards_on_page") == 0:
        return SiteRows(problems=["GetYourGuide showed no activity cards (a security check page or a page that did not load): the operator must look at the page; it is not worked around"])
    if exp:
        if (data.get("query_text") or "").strip().lower() != exp["query"].lower():
            problems.append(f"the page searched '{data.get('query_text')}', not '{exp['query']}': open the url again")
        if exp.get("day") and data.get("date_from") != exp["day"]:
            problems.append(f"the page's date is '{data.get('date_from')}', not {exp['day']}: open the url again (the date is in the address)")
        if json.dumps(data.get("filters_sent") or [], sort_keys=True) != json.dumps(exp.get("filters") or [], sort_keys=True):
            problems.append("the list was read with other filters than asked: run the script again")
    offers: list[Offer] = []
    padding = 0
    filtered = {f["filterType"] for f in (exp.get("filters") or [])}
    wanted_services = {SERVICES[f] for f in exp.get("features") or []}
    group_priced = 0
    for r in rows:
        if r.get("from") is not None and (r.get("cur") or "") not in EUR:
            problems.append(f"the card '{r.get('title')}' is priced in '{r.get('cur')}', not EUR: run the script again")
            break
        meta = r.get("meta") or ""
        title = r.get("title") or "activity"
        per_group = (r.get("per") or "").startswith("group")      # "per person", "per group", "per group up to 2" (the price of a private tour for that many people)
        group_priced += per_group
        checks: list[tuple[str, bool | None]] = []
        if exp:
            if exp.get("title_contains"):
                hit = any(w in title.lower() for w in exp["title_contains"])
                if not hit:
                    padding += 1        # the site pads its list with other activities of the city: they are left out altogether (a kayak must not become "Cheapest" of a whale-watching search)
                    continue
                checks.append(("title", hit))
            if exp.get("max_price") is not None:
                p = r.get("from")
                # a price per group at or under the limit is also at or under it per person; one above it may still be under it per person (the group size decides): not known
                checks.append(("price", None if p is None else (True if p <= exp["max_price"] else (None if per_group else False))))
            if exp.get("min_rating") is not None:
                checks.append(("rating", None if r.get("rating") is None else r["rating"] >= exp["min_rating"]))
            if exp.get("max_hours") is not None:
                checks.append(("duration", _fits_hours(meta, exp["max_hours"])))
            if exp.get("free_cancellation"):
                checks.append(("free cancellation", None))      # the list has no cancellation field: the activity page says it
            if exp.get("language"):
                checks.append((f"language {exp['language']}", True if "languages" in filtered else None))      # the site's own language filter was sent: every row it returned offers that language
            low = meta.lower()
            for feat in exp.get("features") or []:
                shown = {"private_tour": "private" in low, "skip_the_line": "skip the line" in low, "small_group": "small group" in low}.get(feat)
                checks.append((feat.replace("_", " "), True if (shown or "services" in filtered) else None))
        values = [v for _, v in checks]
        fits = None if not checks else (False if False in values else (None if None in values else True))
        was = r.get("was")
        o = Offer(
            group=exp.get("group") or group, source=SOURCE, name=title, price_total=r.get("from"), currency="EUR" if r.get("from") is not None else None,
            price_basis=(f"'from' price for the whole group (GetYourGuide shows it 'per {r['per']}')" if per_group else "'from' price per person (the lowest starting price)")
            + (f", already discounted (was {was:g} EUR, {r['discount_pct']:g}% off)" if was else "") + "; the exact group price comes from getyourguide_activity_recipe",
            fits=fits, quotable=False, supplier="GetYourGuide", link=("https://www.getyourguide.com" + r["path"]) if r.get("path") else None,
            details={"duration": meta.split("•")[0].strip() or "not shown", "start_times": "check the activity page for the date", "language": ("audio guide optional" if "audio guide" in meta.lower() else "not shown on the list"),
                     "meeting_point": "not shown on the list", "cancellation": "not shown on the list (the activity page says it)", "private_or_group": _kind(meta),
                     "rating": f"{r.get('rating'):g} ({r.get('reviews'):,} reviews)" if r.get("rating") is not None and r.get("reviews") is not None else (f"{r.get('rating'):g}" if r.get("rating") is not None else "not rated yet"),
                     "badges": ", ".join(BADGES.get(b, b) for b in (r.get("badges") or [])) or None, "flags": meta.split("•", 1)[1].strip() if "•" in meta else None})
        if fits is None:
            for label, v in checks:
                if v is None:
                    mark_unconfirmed(o, label)
        offers.append(o)
    offset = int(data.get("offset") or 0)
    notes = ["GetYourGuide's list shows only the lowest starting price (EUR, exact to the cent): for the price of the whole group for a date, call getyourguide_activity_recipe for the best two or three."]
    if padding:
        notes.append(f"{padding} of these results have none of the wish's title words ({', '.join(exp.get('title_contains') or [])}): GetYourGuide pads the list with other activities of the city; they are left out of the table and the picks.")
    if offset:
        notes.append(f"These are results {offset + 1} to {offset + len(rows)} in GetYourGuide's own order.")
    if group_priced:
        notes.append(f"{group_priced} row(s) are priced per GROUP on GetYourGuide (private tours): do not compare them with per-person prices" + (" (the price filter also looks at that group price)." if exp.get("max_price") is not None else "."))
    if exp.get("sort") == "rating":
        notes.append("The list is in GetYourGuide's own 'rating' order, which is not strictly by the rating number (read live 6 Nov 2026: 4.9, 4.8, 4.7, 4.6, 4.8 ...): the server's own sorting and picks use the numbers.")
    if exp.get("sort") in ("price", "price_desc"):
        notes.append("The list is in GetYourGuide's own price order (the displayed price: a private tour's is for the whole group); a cheap activity of the city that is not the one asked for can come first: the title words decide what is shown.")
    if data.get("failed"):
        notes.append("Not every page asked for was read: " + "; ".join(str(x) for x in data["failed"]) + ".")
    if exp.get("language") and exp["language"] not in FILTER_LANGUAGES:
        notes.append(f"GetYourGuide's language filter has no '{exp['language']}' (it lists {', '.join(FILTER_LANGUAGES)}): the list does not say which languages a tour offers, so the wish is 'not confirmed' for every row; the activity page shows the guide language.")
    if exp.get("free_cancellation"):
        notes.append("GetYourGuide's list has no cancellation field: free cancellation is 'not confirmed' for every row until the activity page is read (it says 'Cancel for free until ...').")
    total = data.get("results_total")
    total = int(total) if isinstance(total, (int, float)) else (int(re.sub(r"\D", "", str(total or "")) or 0) or None)
    return SiteRows(offers=offers, read=len(rows), total=total, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="getyourguide_find_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def getyourguide_find_recipe_tool(query: str, day: date | None = None, free_cancellation: bool | None = None, max_price: float | None = None, max_hours: float | None = None,
                                            min_rating: float | None = None, title_contains: list[str] | None = None, operator_answered: bool = False, limit: int = BATCH, offset: int = 0,
                                            language: str | None = None, features: list[str] | None = None, sort: str | None = None) -> dict[str, Any]:
        """FOR GETYOURGUIDE TOURS AND ACTIVITIES (the list, read from GetYourGuide's own list service). ASK FIRST: without `free_cancellation` (true/false), `max_price` (EUR per person) and
        `max_hours` it opens nothing and returns `ask_operator`: ask them in ONE message, wait, call again with the answers (`operator_answered`=true for "no preference", only after the operator replied). Then, if the server's own browser is switched on for this site, THE SERVER READS THE LIST ITSELF and returns a short receipt with an `ingest` id: call compose_answer with `runs`=[that id] (ok=false: say the source could not be read). Otherwise the answer has a `url` and a read-only SCRIPT: open the url in a NEW tab, run the script with the javascript tool (it reads `limit` cards from `offset` in GetYourGuide's own order: title, link, duration, rating, reviews, exact price). It sends its answer to the server by itself and returns a receipt (`ingest` id): call compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. `query` = the activity as in the itinerary ("Florence golf cart tour"); `title_contains` = words a title must hold (default: the
        query's words; GetYourGuide pads the list with unrelated activities); `language`, `features` (private_tour, hotel_pickup, skip_the_line, small_group, wheelchair, originals) and `sort` (price, price_desc, rating) go to GetYourGuide's own filters. Comparison only: for the group's exact price call getyourguide_activity_recipe for the best two or three. A human check is never worked around."""
        asked = ((ASK["cancel"], free_cancellation is not None), (ASK["budget"], max_price is not None), (ASK["duration"], max_hours is not None))
        missing = [q for q, given in asked if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date and the travellers with the children's ages only if the request did not say them), wait for the reply, then call "
                            "this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = getyourguide_find_recipe(query, day, limit, offset, title_contains, bool(free_cancellation), max_price, min_rating, max_hours, language, features, sort)
        notes = out.pop("filter_notes")
        out["wishes"] = {"expect": out["expect"], **({"free_cancellation": True} if free_cancellation else {}), **({"max_price": max_price} if max_price is not None else {})}
        src = lambda v: "operator" if v is not None else "default: no preference"       # noqa: E731
        out["filters_used"] = [("Free cancellation only (operator)" if free_cancellation else f"Any cancellation ({src(free_cancellation)})"),
                               (f"At most {max_price:g} EUR per person (operator)" if max_price is not None else f"No price limit ({src(max_price)})"),
                               (f"At most {max_hours:g} hours (operator)" if max_hours is not None else f"No duration limit ({src(max_hours)})"), f"Titles holding any of: {', '.join(out['expect']['title_contains'])} (operator: the wish's own words)"]
        if min_rating is not None:
            out["filters_used"].append(f"Rating at least {min_rating:g} of 5 (operator)")
        if out["expect"]["language"]:
            out["filters_used"].append(f"Language {out['expect']['language']} (operator)")
        if out["expect"]["features"]:
            out["filters_used"].append(f"Wanted: {', '.join(f.replace('_', ' ') for f in out['expect']['features'])} (operator)")
        out["filters_used"] += [f"Applied by GetYourGuide itself: {n}" for n in notes]
        out["more"] = f"For the next {limit} results call this tool again with the same values and offset={offset + limit}."
        # getyourguide.com's security policy only lets the page talk to its own hosts: the server reads the list itself in its automation Chrome; when it cannot, the recipe comes back for the operator's Chrome (rows in parts)
        result = await server_first(NAME, "GYG_FIND_READ_IN_SERVER", "https://www.getyourguide.com", out)
        result["more"] = out["more"]
        return result
