"""Booking.com attractions (the LIST of a city's activities for a day; COMPARISON ONLY: the price for a date and a group is on the activity's own page, see booking_attraction), read in the operator's own Chrome.

Site rules (found on the real page, 27 Oct 2026; the data source read live 5 Nov 2026): the address is booking.com/attractions/searchresults/<country>/<city>.html?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&adults=N&selected_currency=EUR
[&sort_by=trending|highest_weighted_rating|lowest_price][&filter_by_label[]=free_cancellation|skip_the_line][&filter_by_min_rating[]=4.5|4.0|3.5|3.0][&filter_by_language[]=en]; the site redirects to <city>.en-gb.html and keeps these values.
The page's data is Booking.com's own Apollo store (<script data-capla-store-data="apollo">): attractionsProduct.searchProducts with the first 15 products (id, slug, name, duration, cancellationPolicy with the exact cut-off, reviewsStats on
a 5-point scale, representativePrice = the exact lowest price per person, labels, flags), `filterStats` (activities matching, activities in the city: 12 of 4,128 for free cancellation + skip the line + 4.5 up in Lisbon) and
`pagination.hasNextPage`. The page loads 15 more with each scroll from POST accommodations.booking.com/dml/graphql, operation SearchResultsProducts, input {ufi, limit: 15, page, source: "search_results", sortBy, filterByLabel,
filterByMinRating, filterBySupportedLanguage}; a compact query for the fields needed gives the same products (15 of 15 equal to the embedded page 1) and the CSRF token, pageview id and tracking headers are optional. Verified live: free
cancellation gives only free-cancellation products, min rating 4.5 only 4.5 and up, lowest_price ascending across pages, highest_weighted_rating by weighted score. Skip the line is the site's own filter: the data flags it
(aiBadgesSkipTheLine) on only some of the results, so each row is marked from its own flag. The page shows the rating on 10 points (the 5-point average times two) and the price rounded up to whole euros. A card shows no
sort of "how many exist": the service does. A place is the <country>/<city> part of the address; only Lisbon is known here. Our top picks and Best reviewed are read together (the agency's rule). A human check is never worked around.
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

from myt_mcp.compose import Offer, mark_unconfirmed
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, server_first, with_emit

NAME = "booking_attractions"
SOURCE = "Booking.com attractions (public website price)"
GROUP = "Activities"
HERE = Path(__file__).parent
BATCH = 30      # cards per sort
SORTS = [["Our top picks", "trending"], ["Best reviewed", "highest_weighted_rating"]]
TAB_NAMES = {"Our top picks": "Top picks", "Best reviewed": "Best reviewed"}
PAGE_KEYS = ("place", "day", "day_to", "adults", "currency")      # what the script echoes of the page's own address
RATING_BUCKETS = ((9.0, "4.5"), (8.0, "4.0"), (7.0, "3.5"), (6.0, "3.0"))      # the site's "9 up" ... "6 up" boxes: its 5-point value for a 10-point score
LANGUAGES = {"en", "pt", "es", "fr", "it", "de", "ru", "uk", "nl"}


def places() -> dict[str, dict[str, str]]:
    data = json.loads((HERE / "booking_attractions.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def booking_attractions_recipe(place_path: str, place_name: str, day: date, adults: int = 2, limit: int = BATCH, title_contains: list[str] | None = None, free_cancellation: bool = False,
                               max_price: float | None = None, min_rating: float | None = None, skip_the_line: bool = False, language: str | None = None) -> dict[str, Any]:
    place_path = place_path.strip().lower()
    if not re.fullmatch(r"[a-z]{2}/[a-z0-9-]+", place_path):
        raise ValueError("the place is '<country code>/<city>' as in the site's address (pt/lisbon)")
    if not 1 <= adults <= 8 or not 1 <= limit <= 60:
        raise ValueError("adults must be 1-8 and limit 1-60 (cards per sort)")
    if language is not None and language.lower() not in LANGUAGES:
        raise ValueError(f"language must be one of {sorted(LANGUAGES)} (the site's own language filter)")
    words = [w.lower() for w in (title_contains or []) if w.strip()]
    labels = sorted(x for x, on in (("free_cancellation", free_cancellation), ("skip_the_line", skip_the_line)) if on)
    bucket = next((b for threshold, b in RATING_BUCKETS if min_rating is not None and min_rating >= threshold), None)      # the site's box at or under the wish; the exact wish is judged on the cards
    expect = {"place": place_path, "day": day.isoformat(), "day_to": day.isoformat(), "adults": adults, "currency": "EUR", "sort": None, "labels": labels, "min_rating": [bucket] if bucket else [],
              "language": [language.lower()] if language else [], "time_of_day": [], "title_contains": words, "free_cancellation": free_cancellation, "max_price": max_price, "min_rating_wish": min_rating,
              "group": f"Booking.com attractions in {place_name}, {day:%d %b %Y}"}
    url = (f"https://www.booking.com/attractions/searchresults/{place_path}.html?date_from={day.isoformat()}&date_to={day.isoformat()}&adults={adults}&selected_currency=EUR"
           + "".join(f"&filter_by_label[]={x}" for x in labels) + (f"&filter_by_min_rating[]={bucket}" if bucket else "") + (f"&filter_by_language[]={language.lower()}" if language else ""))
    filters = {"filterByLabel": labels, "filterByMinRating": [bucket] if bucket else [], "filterBySupportedLanguage": [language.lower()] if language else []}
    expect["filters"] = filters
    request = {"filters": filters, "limit": limit, "sorts": [{"label": label, "key": key} for label, key in SORTS]}
    script = with_emit((HERE / "booking_attractions.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps(request))
    return {"url": url, "script": script, "expect": expect}


FLAG_TEXT = {"aiBadgesSkipTheLine": "skip the line", "aiBadgesAdmissionIncluded": "admission included", "aiBadgesExpertGuide": "expert guide", "aiBadgesAudio": "audio guide"}


def _expected_filters(exp: dict[str, Any]) -> list[str]:
    return sorted([f"filter_by_label={x}" for x in exp.get("labels") or []] + [f"filter_by_min_rating={x}" for x in exp.get("min_rating") or []] + [f"filter_by_language={x}" for x in exp.get("language") or []])


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
    searched = data.get("searched") or {}
    for k in PAGE_KEYS:
        if k in exp and searched.get(k) != exp[k]:
            problems.append(f"the page searched {k} {searched.get(k)} instead of {exp[k]}: open the url again")
    if exp.get("filters") is not None and searched.get("filters") != exp["filters"]:
        problems.append(f"the request carried the filters {searched.get('filters')} instead of {exp['filters']}: run the script again")
    sorts = {s.get("sort"): s for s in data.get("sorts") or []}
    if exp and not {"Our top picks", "Best reviewed"} <= set(sorts):
        problems.append("both the Our top picks and the Best reviewed sorts must be read: run the script again")
    for name, srt in sorts.items():
        if not srt.get("read"):
            problems.append(f"no activity of the {name} sort was read ({'; '.join(data.get('failed') or []) or 'no reason given'}): run the script again")
    country = data.get("country") or (exp.get("place") or "").split("/")[0]
    merged: dict[tuple, dict[str, Any]] = {}
    padding = 0
    for r in data.get("rows", []):
        if r.get("cur") != "EUR":
            problems.append(f"a Booking.com price is in '{r.get('cur')}', not euro: open the url again (the address asks selected_currency=EUR)")
            continue
        title = r.get("title") or ""
        if exp.get("title_contains") and not any(w in title.lower() for w in exp["title_contains"]):
            padding += 1        # the list is the whole city's, in the site's own order: a card without the wish's words is left out altogether
            continue
        key = (r.get("id") or title, r.get("from"))
        if key in merged:      # the same activity in both sorts is one row with both labels
            tab = TAB_NAMES.get(r.get("sort"), r.get("sort"))
            if tab not in merged[key]["tabs"]:
                merged[key]["tabs"].append(tab)
            continue
        merged[key] = {"row": r, "tabs": [TAB_NAMES.get(r.get("sort"), r.get("sort"))]}
    offers: list[Offer] = []
    for item in merged.values():
        r, title = item["row"], item["row"].get("title") or ""
        rating10 = round(r["rating5"] * 2, 1) if r.get("rating5") is not None else None      # the page shows 9.2 for the 5-point average 4.6
        flags = set(r.get("flags") or [])
        checks: list[tuple[str, bool | None]] = []
        if exp:
            if exp.get("title_contains"):
                checks.append(("title", True))
            if exp.get("max_price") is not None:
                checks.append(("price", None if r.get("from") is None else r["from"] <= exp["max_price"]))
            if exp.get("min_rating_wish") is not None:
                checks.append(("rating", None if rating10 is None else rating10 >= exp["min_rating_wish"]))
            if exp.get("free_cancellation"):
                checks.append(("free cancellation", bool(r.get("free_cancel"))))
            if "skip_the_line" in (exp.get("labels") or []):
                checks.append(("skip the line", True if "aiBadgesSkipTheLine" in flags else None))
        values = [v for _, v in checks]
        fits = None if not checks else (False if False in values else (None if None in values else True))
        rating = f"{rating10:g} ({r['reviews']:,} reviews)" if rating10 is not None and r.get("reviews") is not None else (f"{rating10:g}" if rating10 is not None else "not rated yet")
        badges = [x for x in (r.get("best_seller_text") or (f"#{r['best_seller']:g} Best seller" if r.get("best_seller") else None), *[FLAG_TEXT[f] for f in r.get("flags") or [] if f in FLAG_TEXT]) if x]
        guide, audio = r.get("guide_langs") or [], r.get("audio_langs") or []
        langs = "; ".join(x for x in (f"guide in {', '.join(guide)}" if guide else None, f"audio in {', '.join(audio)}" if audio else None) if x) or ("filtered by Booking.com for " + ", ".join(exp["language"]) if exp.get("language") else "not shown")
        cancel = (f"Free cancellation until {_until(r['cancel_until'])} (Booking.com's own data)" if r.get("cancel_until") else "Free cancellation (Booking.com's own flag)") if r.get("free_cancel") else ("not free (Booking.com's own flag)" if r.get("free_cancel") is False else "not shown on the list")
        o = Offer(
            group=exp.get("group") or group, source=SOURCE, name=title, price_total=r.get("from"), currency="EUR",
            price_basis="'from' price = the lowest starting price per person, exact (the page shows it rounded up); not for the date and the group: that is on the activity's page" + (f"; discounted from EUR {r['public_from']:g}" if r.get("discounted") and r.get("public_from") and r["public_from"] != r.get("from") else ""),
            fits=fits, quotable=False, supplier="Booking.com", link=f"https://www.booking.com/attractions/{country}/{r['slug']}.en-gb.html" if r.get("slug") and country else None,
            flexible=True if r.get("free_cancel") else None,
            details={"duration": r.get("duration") or "not shown", "start_times": "check the activity page for the date", "language": langs,
                     "meeting_point": "not shown on the list", "cancellation": cancel, "private_or_group": "private" if "private" in title.lower() else "not shown on the list", "rating": rating,
                     "badges": ", ".join(badges) or None, "available_from": (f"bookable from {r['available_from']}" + (f" (up to {r['booking_window_days']} days ahead)" if r.get("booking_window_days") else "")) if r.get("available_from") else None, "from_tab": " and ".join(item["tabs"])})
        if fits is None:
            for label, v in checks:
                if v is None:
                    mark_unconfirmed(o, label)
        offers.append(o)
    seen = ", ".join(f"{name}: {srt.get('read')} activities" for name, srt in sorts.items())
    notes = ["Booking.com's list shows only the lowest starting price per person: for the price for the date and the group open the activity's page for the best two or three (booking_attraction_recipe). Top picks and Best reviewed were read together; an activity in both is one row (column from tab).",
             f"Read: {seen}."]
    if data.get("results_matching") is not None:
        notes.append(f"Booking.com says {data['results_matching']:,} activities match this search" + (f" (of {data['results_in_city']:,} in the city)" if data.get("results_in_city") else "") + "; only the first ones of each sort were read.")
    site_filters = _expected_filters(exp)
    if site_filters:
        notes.append("Booking.com's own filters were sent with the request: " + ", ".join(site_filters) + ".")
    if "skip_the_line" in (exp.get("labels") or []):
        notes.append("Skip the line is Booking.com's own filter; its data flags skip-the-line on only some of the results, so a row without the flag is marked 'not confirmed' for it.")
    if padding:
        notes.append(f"{padding} of these results have none of the wish's title words ({', '.join(exp.get('title_contains') or [])}): the list is the whole city's, so they are left out of the table and the picks.")
    if data.get("failed"):
        notes.append("Not every page asked for was read: " + "; ".join(str(x) for x in data["failed"]) + ".")
    if not data.get("rows") and not problems:
        problems.append("no activity could be read: say it could not be read, never that there are none")
    count = len(merged) + padding
    total = data.get("results_matching")
    return SiteRows(offers=offers, read=count, total=max(total or 0, count) if total is not None else count, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="booking_attractions_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def booking_attractions_recipe_tool(place: str, day: date, adults: int = 2, title_contains: list[str] | None = None, free_cancellation: bool | None = None, max_price: float | None = None,
                                              min_rating: float | None = None, skip_the_line: bool | None = None, language: str | None = None, place_path: str | None = None, limit: int = BATCH) -> dict[str, Any]:
        """FOR BOOKING.COM ATTRACTIONS (COMPARISON ONLY; the LIST of a city's activities for one day; read in the operator's own Chrome with Claude in Chrome), next to GetYourGuide and Viator. `place` is the
        city (Lisbon is known; for another city give `place_path` as in the site's address, '<country code>/<city>', e.g. pt/porto, learned by searching it once on the site). Optional wishes, applied with the
        SITE'S OWN FILTERS in the address: `free_cancellation`, `skip_the_line`, `min_rating` (on the 10-point scale: 9, 8, 7 or 6 and up), `language` ('en', 'pt', 'es', 'fr', 'it', 'de', 'ru', 'uk', 'nl'); also
        `title_contains` (REQUIRED: 1-3 words the title must contain, e.g. ["sintra"]) and `max_price` (EUR per person), which the server judges on the cards read. It returns the results url (day, adults, euro and the filters in
        it) and a read-only SCRIPT: open the url, run the script with the javascript tool. The script reads the first `limit` cards (default 30, scrolling to load them) of 'Our top picks', then picks 'Best reviewed' in the page's sort box and
        reads the first `limit` of that (both are read together, the agency's rule), and sends its whole answer from the page to the server by itself and returns a short receipt (the recipe's `ingest` id is in it): then call
        compose_answer with `runs`=[that id] and the returned `wishes`; never type or pass a row. The price is the lowest starting price per person: for the group price of a date call booking_attraction_recipe for the
        best two or three. A human check (captcha) is never worked around: stop and tell the operator. The server reads it first in its own Chrome (a short receipt with an `ingest` id: only compose_answer with `runs`=[that id]); if `server_read` says it could not, read the url in Claude in Chrome. Never retry the server's read."""
        if not [w for w in (title_contains or []) if str(w).strip()]:
            raise ToolError("title_contains is needed: Booking.com's list is the WHOLE city's activities (on 29 Oct 2026 57 of 60 cards were off-topic). Give 1-3 words that the wanted activity's title must contain, "
                            "taken from what the operator asked for (for example [\"food\", \"tour\"] or [\"sintra\"]); the server leaves out the cards without them.")
        known = places().get(place.strip().lower())
        if place_path:
            path, name = place_path, place.strip() or place_path
        elif known:
            path, name = known["path"], known["name"]
        else:
            return {"ok": False, "searched": False, "known_places": list(dict.fromkeys(v["name"] for v in places().values())),
                    "next": "Nothing was opened. That city is not known yet: search it once on booking.com/attractions in Claude in Chrome, read '<country code>/<city>' from the results address "
                            "(booking.com/attractions/searchresults/pt/porto.html is pt/porto), then call this tool again with place_path."}
        try:
            out = booking_attractions_recipe(path, name, day, adults, limit, title_contains, bool(free_cancellation), max_price, min_rating, bool(skip_the_line), language)
        except ValueError as e:      # a refusal the assistant must read and act on, not an 'unexpected error'
            raise ToolError(str(e)) from None
        exp = out["expect"]
        out["wishes"] = {"expect": exp}
        out["filters_used"] = [f"Day {day.isoformat()} and {adults} adults (operator)", "Prices in EUR (server default)", "Our top picks and Best reviewed sorts read together (agency rule)"] + \
            ([f"Title has one of: {', '.join(exp['title_contains'])} (operator)"] if exp["title_contains"] else []) + (["Free cancellation (operator; the site's own filter)"] if free_cancellation else []) + \
            (["Skip the line (operator; the site's own filter)"] if skip_the_line else []) + ([f"Max {max_price:g} EUR per person (operator)"] if max_price is not None else []) + \
            ([f"Rating {min_rating:g} or more (operator; the site's '{exp['min_rating'][0]} up' box is the nearest below, the exact wish is judged on the cards)"] if min_rating is not None and exp["min_rating"] else
             ([f"Rating {min_rating:g} or more (operator; judged on the cards, the site has no box that low)"] if min_rating is not None else [])) + ([f"Language {language.lower()} (operator; the site's own filter)"] if language else [])
        return await server_first(NAME, "BOOKING_ATTRACTIONS_READ_IN_SERVER", "https://www.booking.com", out)
