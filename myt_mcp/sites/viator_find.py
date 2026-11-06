"""Viator search (the LIST of activities for a query; COMPARISON ONLY: the exact group price comes from viator_activity_recipe), read in the operator's own Chrome or in the server's.

Site rules (read live 5 Nov 2026): the search is www.viator.com/searchResults/all?text=<text> for page 1 and www.viator.com/searchResults/all/<n>?text=<text> for page n (24 results a page, at most 200 results: 8 pages and
8 more). Viator renders each page with its data embedded as JSON (<script id="globalState">, pageModel.preloadedData.search.results) and the script reads THAT (the same 24 products in the same order as the cards, the same
rating, reviews, duration and free cancellation; the price is the exact from-price, the cards show it rounded), the links from the page's own card anchors. The filters are part of the page address:
  duration=<min>-<max> (minutes; a product matches when its own duration, or its range, overlaps), rating=3|4|5 (Viator's rounded star average: 4 holds every product of 4.0 and up), price=<min>-<max> (EUR per person),
  feature=<one of free_cancellation, on_sale, likely_to_sell_out, skip_the_line, private_tour, new_on_viator> (several together do NOT narrow the list: one is sent, the rest are judged here), language=<en zh nl fr de it ja pt ru es>,
  sortType=<average_review_rating_descending | duration_ascending | duration_descending | recency_descending> (Viator has no price sort). The dates and travellers set on the search page are not in the address and change
nothing in the list. The "from" price is per person for 2 adults; the prices follow the visitor's currency, which must be EUR (the rows carry their own currency).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from myt_mcp.compose import Offer, mark_unconfirmed
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
SORTS = {"featured": None, "rating": "average_review_rating_descending", "duration_short": "duration_ascending", "duration_long": "duration_descending", "newest": "recency_descending"}
FEATURES = ("free_cancellation", "on_sale", "likely_to_sell_out", "skip_the_line", "private_tour", "new_on_viator")
FILTER_LANGUAGES = ("en", "zh", "nl", "fr", "de", "it", "ja", "pt", "ru", "es")      # the languages Viator's own filter lists (Hebrew is not one of them: it is judged from each product's offered languages)
LANGUAGE_NAMES = {"english": "en", "hebrew": "he", "chinese": "zh", "dutch": "nl", "french": "fr", "german": "de", "italian": "it", "japanese": "ja", "portuguese": "pt", "russian": "ru", "spanish": "es", "arabic": "ar", "polish": "pl"}
LANGUAGE_CODES = {"he": {"he", "iw"}, "zh": {"zh", "cmn", "yue"}}      # Viator's own codes for one language
MAX_RESULTS = 200


def language_code(text: str | None) -> str | None:
    key = (text or "").strip().lower()
    if not key:
        return None
    code = LANGUAGE_NAMES.get(key, key)
    if not re.fullmatch(r"[a-z]{2,3}", code):
        raise ValueError("language must be a language name or code such as English or en")
    return code


def rating_param(min_rating: float | None) -> int | None:
    """Viator's rating filter has 3, 4 and 5 ('4.5 & up' in its menu); rating=5 returned only products rated exactly 5.0 (read live 5 Nov 2026), so it is never sent: 4 holds everything of 4.0 and up, 3 everything of 3.0 and up.
    The value sent never drops a product that meets the operator's minimum; the exact rating is judged here."""
    if min_rating is None or min_rating < 3:
        return None
    return 4 if min_rating >= 4 else 3


def filter_params(free_cancellation: bool, max_price: float | None, min_rating: float | None, max_hours: float | None, language: str | None, features: list[str] | None, sort: str | None) -> tuple[list[tuple[str, str]], list[str]]:
    """The filters that go in Viator's own address (a wish Viator cannot filter is judged by the server from the rows) and the sentences that say so."""
    params: list[tuple[str, str]] = []
    said: list[str] = []
    if max_hours is not None and max_hours < 72:
        params.append(("duration", f"0-{int(round(max_hours * 60))}"))
        said.append(f"Viator's duration filter 0-{int(round(max_hours * 60))} minutes (it also lets through products whose duration is a range that starts below the limit: those are judged here)")
    stars = rating_param(min_rating)
    if stars:
        params.append(("rating", str(stars)))
        said.append(f"Viator's rating filter {stars}+ (the exact rating is judged here)")
    if max_price is not None:
        top = int(math.ceil(max_price)) + 1      # Viator's upper bound is exclusive: a product at exactly 25.00 vanished from price=0-25 (read live 5 Nov 2026); the server judges the exact price
        params.append(("price", f"0-{top}"))
        said.append(f"Viator's price filter up to {top} EUR per person (one more than the limit: its upper bound is exclusive; the exact price is judged here)")
    wanted = list(dict.fromkeys(([("free_cancellation")] if free_cancellation else []) + [f for f in (features or []) if f in FEATURES]))
    if wanted:
        params.append(("feature", wanted[0]))
        said.append(f"Viator's own '{wanted[0]}' filter" + (f"; Viator cannot combine features, so {', '.join(wanted[1:])} are judged here from each product" if len(wanted) > 1 else ""))
    if language and language in FILTER_LANGUAGES:
        params.append(("language", language))
        said.append(f"Viator's language filter {language}")
    elif language:
        said.append(f"Viator has no language filter for '{language}': judged here from each product's offered languages")
    if sort and SORTS.get(sort):
        params.append(("sortType", SORTS[sort]))
        said.append(f"sorted by Viator's own '{SORTS[sort]}'")
    return params, said


def search_url(query: str, page: int, params: list[tuple[str, str]] | None = None) -> str:
    base = "https://www.viator.com/searchResults/all" + (f"/{page}" if page > 1 else "")
    return f"{base}?{urlencode([('text', query)] + list(params or []))}"


def viator_find_recipe(query: str, day_label: str | None = None, page: int = 1, title_contains: list[str] | None = None, free_cancellation: bool = False, max_price: float | None = None,
                       min_rating: float | None = None, max_hours: float | None = None, language: str | None = None, features: list[str] | None = None, sort: str | None = None, pages: int = 1) -> dict[str, Any]:
    if min_rating is not None and min_rating > 5:      # the operator's "rating 9 and up" is on Booking.com's 10-point scale; this site rates on 5 points (27 Oct 2026: 9 was refused, then 4.9 was 'not 9')
        min_rating = round(min_rating / 2, 2)
    q = " ".join((query or "").split())
    if not q or len(q) > 120:
        raise ValueError("query is empty or too long (for example 'Florence golf cart tour')")
    if not 1 <= page <= 9 or (max_price is not None and max_price <= 0) or (max_hours is not None and max_hours <= 0) or (min_rating is not None and not 0 < min_rating <= 5):
        raise ValueError("page 1-9, max_price and max_hours above 0, min_rating 0-5")
    if not 1 <= pages <= 9 or page + pages - 1 > 9:
        raise ValueError("pages 1-9 and page + pages - 1 at most 9 (Viator lists at most 200 results: 9 pages)")
    bad = [f for f in (features or []) if f not in FEATURES]
    if bad or (sort is not None and sort not in SORTS):
        raise ValueError(f"features are among {', '.join(FEATURES)}; sort is one of {', '.join(SORTS)}")
    free_cancellation = bool(free_cancellation or "free_cancellation" in (features or []))
    lang = language_code(language)
    script = with_emit((HERE / "viator_find.js").read_text(encoding="utf-8")).replace("__REQUEST__", json.dumps({"pages": pages}))
    must = [w.lower() for w in (title_contains or words(q))]
    # a single word that is a destination ("Lisbon") sends the page to the destination's own page (viator.com/Lisbon/d538-ttd), whose cards are laid out differently and have no search data
    # (28 Oct 2026, checked in the server's Chrome); "Lisbon tours" stays on the search page. The title words to look for stay those of the operator's own query.
    searched = f"{q} tours" if len(q.split()) == 1 else q
    params, said = filter_params(free_cancellation, max_price, min_rating, max_hours, lang, features, sort)
    wanted_features = list(dict.fromkeys(([("free_cancellation")] if free_cancellation else []) + list(features or [])))
    expect = {"query": searched, "page": page, "pages": pages, "group": f"{q}, {day_label}" if day_label else q, "title_contains": must, "free_cancellation": free_cancellation, "max_price": max_price, "min_rating": min_rating,
              "max_hours": max_hours, "language": lang, "features": [f for f in wanted_features if f != "free_cancellation"], "sort": sort or "featured", "url_filters": dict(params)}
    return {"url": search_url(searched, page, params), "script": script, "expect": expect, "filter_notes": said}


def fmt_minutes(lo: float | None, hi: float | None) -> str | None:
    def one(m: float) -> str:
        m = int(round(m))
        if m >= 1440 and m % 1440 == 0:
            return f"{m // 1440} day{'s' if m // 1440 != 1 else ''}"
        h, mi = divmod(m, 60)
        return " ".join(x for x in (f"{h} hour{'s' if h != 1 else ''}" if h else "", f"{mi} minutes" if mi else "") if x) or "0 minutes"
    if lo is None or hi is None:
        return None
    return one(lo) if lo == hi else f"{one(lo)} to {one(hi)}"


def duration_fit(lo: float | None, hi: float | None, max_hours: float) -> bool | None:
    """Within the limit: True; a product that cannot be that short: False; a range that starts under the limit and ends over it, or no duration: not known (the option chosen decides)."""
    if lo is None or hi is None:
        return None
    limit = max_hours * 60
    return True if hi <= limit else (False if lo > limit else None)


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
        sent = {str(k): str(v) for k, v in (exp.get("url_filters") or {}).items() if k != "sortType"}
        got = {str(k): str(v) for k, v in (data.get("url_filters") or {}).items() if k != "sortType"}
        if sent != got:
            problems.append(f"the page's address carries the filters {got or 'none'}, not {sent or 'none'}: open the url again")
    offers: list[Offer] = []
    padding = 0
    wanted_codes = LANGUAGE_CODES.get(exp.get("language") or "", {exp.get("language")} if exp.get("language") else set())
    for r in rows:
        if r.get("price") is not None and (r.get("cur") or "") not in EUR:
            problems.append(f"the product '{r.get('title')}' is priced in '{r.get('cur')}', not EUR: open the globe menu, choose the currency EUR, open the url again and run the script again")
            break
        title = r.get("title") or "activity"
        checks: list[tuple[str, bool | None]] = []
        if exp:
            if exp.get("title_contains"):
                hit = any(w in title.lower() for w in exp["title_contains"])
                if not hit:
                    padding += 1        # the site pads its list with other activities of the city: they are left out altogether (a kayak must not become "Cheapest" of a whale-watching search)
                    continue
                checks.append(("title", hit))
            if exp.get("max_price") is not None:
                checks.append(("price", None if r.get("price") is None else r["price"] <= exp["max_price"]))
            if exp.get("min_rating") is not None:
                checks.append(("rating", None if r.get("rating") is None else r["rating"] >= exp["min_rating"]))
            if exp.get("max_hours") is not None:
                checks.append(("duration", duration_fit(r.get("mins_from"), r.get("mins_to"), exp["max_hours"])))
            if exp.get("free_cancellation"):
                checks.append(("free cancellation", r.get("free_cancel")))
            if wanted_codes:
                langs = set(r.get("langs") or [])
                checks.append((f"language {exp.get('language')}", True if langs & wanted_codes else (False if langs else None)))
            for feat in exp.get("features") or []:
                badges = set(r.get("badges") or [])
                low = title.lower()
                if feat == "on_sale":
                    checks.append(("deal", r.get("was") is not None))
                elif feat == "likely_to_sell_out":
                    checks.append(("likely to sell out", "LIKELY_TO_SELL_OUT" in badges))
                elif feat == "new_on_viator":
                    checks.append(("new on Viator", True if "NEW_ON_VIATOR" in badges else None))
                elif feat == "private_tour":
                    checks.append(("private tour", True if "private" in low else None))
                elif feat == "skip_the_line":
                    checks.append(("skip the line", True if "skip" in low and "line" in low else None))
        values = [v for _, v in checks]
        fits = None if not checks else (False if False in values else (None if None in values else True))
        duration = fmt_minutes(r.get("mins_from"), r.get("mins_to"))
        unit = r.get("pricing_type")
        basis = ("'from' price per person (the lowest, for the default group of 2 adults)" if unit in (None, "TRAVELLER_BY_AGE_BAND") else "'from' price for the whole group (Viator prices this activity per group, a flat price, not per person)" if unit == "UNIT"
                 else f"'from' price (Viator pricing type {unit}: it may not be per person)") \
            + (f"; discounted from {r['was']:g} EUR" if r.get("was") else "") + ("; varies by group size" if r.get("varies") else "")
        rated = f"{r['rating']:g} ({r['reviews']:,} reviews)" if r.get("rating") is not None and r.get("reviews") is not None else (f"{r['rating']:g}" if r.get("rating") is not None else "not rated yet")
        o = Offer(
            group=exp.get("group") or group, source=SOURCE, name=title, price_total=r.get("price"), currency="EUR" if r.get("price") is not None else None,
            price_basis=basis + "; the exact group price comes from viator_activity_recipe", fits=fits, quotable=False, supplier="Viator",
            flexible=True if r.get("free_cancel") else None, link=("https://www.viator.com" + r["path"]) if r.get("path") else None,
            details={"duration": duration or "not shown", "start_times": "check the activity page for the date", "language": ("offered in: " + ", ".join(r["langs"])) if r.get("langs") else "not shown on the list",
                     "meeting_point": "not shown on the list", "cancellation": "Free cancellation (Viator's own flag)" if r.get("free_cancel") else ("not free (Viator's own flag)" if r.get("free_cancel") is False else "not shown on the list"),
                     "private_or_group": "private" if "private" in title.lower() else "not shown on the list", "rating": rated, "badges": ", ".join(b.replace("_", " ").lower() for b in (r.get("badges") or [])) or None})
        if fits is None:
            for label, v in checks:
                if v is None:
                    mark_unconfirmed(o, label)
        offers.append(o)
    notes = ["Viator's list shows only the lowest 'from' price per person (EUR, exact to the cent) in its own " + ("'Featured' order" if (data.get("sort") or "featured") == "featured" else f"order '{data.get('sort')}'")
             + " (it has no price sort): for the price of the whole group for a date call viator_activity_recipe for the best two or three."]
    if padding:
        notes.append(f"{padding} of these results have none of the wish's title words ({', '.join(exp.get('title_contains') or [])}): Viator pads the list with other activities; they are left out of the table and the picks.")
    if (data.get("pages_read") or 1) > 1 or data.get("page", 1) > 1:
        notes.append(f"This is result page {data.get('page', 1)}" + (f" to {data['page'] + data['pages_read'] - 1}" if (data.get("pages_read") or 1) > 1 else "") + f" ({data.get('shown_range') or 'range not shown'}) of Viator's own order.")
    if data.get("failed_pages"):
        notes.append("Not every page asked for was read: " + "; ".join(str(x) for x in data["failed_pages"]) + ".")
    total = data.get("results_total")
    total = int(total) if isinstance(total, (int, float)) else (int(re.sub(r"\D", "", str(total)) or 0) or None)
    if total and total >= MAX_RESULTS:
        notes.append(f"Viator lists at most {MAX_RESULTS} results for one search: a search that matches more shows only its first {MAX_RESULTS} in its own order.")
    if exp.get("language") and exp["language"] not in FILTER_LANGUAGES:
        notes.append(f"Viator's language filter has no '{exp['language']}' (it lists {', '.join(FILTER_LANGUAGES)}): each product was judged from its own offered languages, and the list only holds what Viator's order put in the first pages.")
    if any(f in (exp.get("features") or []) for f in ("private_tour", "skip_the_line", "new_on_viator")):
        notes.append("Viator's private tour, skip-the-line and new filters rank rather than strictly filter, and the list shows no field for them: a product that does not say so in its title is marked 'not confirmed' for that wish.")
    return SiteRows(offers=offers, read=len(rows), total=total, problems=problems, sorted_by_price=False, extra_notes=notes, read_rows=True, total_absolute=True)


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="viator_find_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def viator_find_recipe_tool(query: str, day_label: str | None = None, free_cancellation: bool | None = None, max_price: float | None = None, max_hours: float | None = None,
                                      min_rating: float | None = None, title_contains: list[str] | None = None, operator_answered: bool = False, page: int = 1, language: str | None = None,
                                      features: list[str] | None = None, sort: str | None = None, pages: int = 1) -> dict[str, Any]:
        """FOR VIATOR TOURS AND ACTIVITIES (the list, read from Viator's own page data). ASK FIRST: without `free_cancellation` (true/false), `max_price` (EUR per person) and `max_hours` it opens nothing and returns
        `ask_operator`: ask them in ONE message, wait, call again with the answers (`operator_answered`=true for "no preference", only after the operator replied). Then THE SERVER READS THE LIST ITSELF in its own browser and
        returns a short receipt with an `ingest` id: call compose_answer with `runs`=[that id] (ok=false: put Viator in not_checked with the reason it gives). Without a server browser it returns
        the search url (the filters are in it) and a read-only SCRIPT: open the url, run it; it sends its answer to the server by itself: call compose_answer with `runs`=[its `ingest` id] and the returned `wishes`;
        never type or pass a row. 24 products a page with the exact 'from' price per person; the server judges every wish itself. More: page=page+1 (up to 9) or `pages` (several
        in one read). `query` = the activity as in the itinerary ("Florence golf cart tour"); `day_label` = the date text; `title_contains` = words a title must hold (default: the query's words);
        `language` = a language wanted; `features` = free_cancellation, on_sale, likely_to_sell_out, skip_the_line, private_tour, new_on_viator; `sort` = rating, duration_short, duration_long, newest. Comparison only: for the group's exact price on the date call
        viator_activity_recipe for the best two or three. A human check is never worked around."""
        asked = ((ASK["cancel"], free_cancellation is not None), (ASK["budget"], max_price is not None), (ASK["duration"], max_hours is not None))
        missing = [q for q, given in asked if not given]
        if missing and not operator_answered:
            return {"ok": False, "ask_operator": missing, "searched": False,
                    "next": "Nothing was opened. Ask the operator these questions in ONE message (add the date and the travellers with the children's ages only if the request did not say them), wait for the reply, then call "
                            "this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true (only after the operator replied in this chat)."}
        out = viator_find_recipe(query, day_label, page, title_contains, bool(free_cancellation), max_price, min_rating, max_hours, language, features, sort, pages)
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
        out["filters_used"] += [f"Applied by Viator itself: {n}" for n in notes]
        out["more"] = f"For the next results call this tool again with the same values and page={page + pages}." if page + pages <= 9 else "Viator lists at most 200 results: this was the last page."
        # viator.com's pages carry a Content-Security-Policy in a <meta> tag that stops the page from sending data to this server (24 Oct 2026): the server reads the list itself, slowly (15 s apart, 20 an hour);
        # when it cannot (27 Oct 2026: "not a Viator search page" twice) the recipe comes back for the operator's Chrome, whose script returns the rows in parts
        result = await server_first(NAME, "VIATOR_FIND_READ_IN_SERVER", "https://www.viator.com", out)
        result["more"] = out["more"]
        return result
