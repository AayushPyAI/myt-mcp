"""RateHawk hotels: a URL and a script that the operator's own logged-in Chrome runs through Claude in Chrome (a site module, see myt_mcp/sites/__init__.py).

The server cannot drive the operator's Chrome, but it can hand Claude a tested script that READS a results page the same way every time
(instead of Claude clicking and reading by eye). The script returns structured rows; compose_answer turns them into the answer.
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

from myt_mcp.compose import Offer, SourceRead, meets_limits
from myt_mcp.errors import tool_errors
from myt_mcp.sites import SiteRows, read_in_server_browser, server_reads, with_emit

NAME = "ratehawk_hotels"
SOURCE = "RateHawk"
NEEDS_WIDE_WINDOW = True       # a narrow window shows the mobile layout, which the script cannot read
GROUP = "Hotels"

RECIPES = Path(__file__).parent
# the sort values RateHawk's own list uses (tested 21 Oct 2026): URL value -> the label the page shows
RATEHAWK_SORTS = {"price_asc": ("price.asc", "Price (low to high)"), "price_desc": ("price", "Price (high to low)"), "rating": ("rating", "Guests' rating (high to low)")}


def ratehawk_hotels_recipe(country: str, city: str, check_in: date, check_out: date, adults: int, sort: str = "price_asc", breakfast: bool = False,
                           free_cancellation: bool = False, stars: int | None = None, max_pages: int = 3, children_ages: list[int] | None = None, offset: int = 0,
                           limit: int | None = None) -> dict[str, Any]:
    if sort not in RATEHAWK_SORTS:
        raise ValueError(f"sort must be one of {sorted(RATEHAWK_SORTS)}")
    if not 1 <= max_pages <= 10:
        raise ValueError("max_pages must be between 1 and 10 (20 hotels a page)")
    if check_out <= check_in:
        raise ValueError("check_out must be after check_in")
    if offset < 0 or (limit is not None and not 1 <= limit <= 100):
        raise ValueError("offset must be 0 or more and limit 1-100")
    if limit is not None:      # the operator's window: items [offset, offset + limit) of the list, 20 a page
        start_page, skip = offset // 20 + 1, offset % 20
        max_pages = -(-(skip + limit) // 20)
    else:
        start_page, skip, limit = 1, 0, 9999
    slug = lambda t: re.sub(r"[^a-z0-9]+", "-", t.strip().lower()).strip("-")        # noqa: E731
    ages = list(children_ages or [])
    if any(not 0 <= a <= 17 for a in ages):
        raise ValueError("children's ages must be 0-17")
    # RateHawk writes guests as "<adults>and<age>and<age>" (seen 21 Oct 2026 with 2 adults and one child of 6: guests=2and6); one child is tested, more are the same pattern
    guests = "and".join([str(adults)] + [str(a) for a in ages])
    params: list[tuple[str, str]] = [("dates", f"{check_in:%d.%m.%Y}-{check_out:%d.%m.%Y}"), ("guests", guests)]
    if breakfast:
        params.append(("meal_types", "breakfast"))
    if free_cancellation:
        params.append(("payment", "freecancellation"))
    if stars:      # RateHawk writes several levels joined by dots: "4 stars and up" is stars=4.5 (seen on the page, 22 Oct 2026); stars=4 alone is exactly 4
        if not 1 <= stars <= 5:
            raise ValueError("stars must be 1-5 (the minimum star rating)")
        params.append(("stars", ".".join(str(s) for s in range(stars, 6))))
    value, label = RATEHAWK_SORTS[sort]
    params += [("sort", value), ("page", str(start_page))]
    url = f"https://www.ratehawk.com/hotel/{slug(country)}/{slug(city)}/?{urlencode(params)}"
    script = with_emit((RECIPES / "ratehawk_hotels.js").read_text(encoding="utf-8")).replace("__MAX_PAGES__", str(max_pages)).replace("__START_PAGE__", str(start_page)).replace("__SKIP__", str(skip)).replace("__LIMIT__", str(limit))
    script = script.replace("__EXPECT_SORT__", label)
    return {
        "required_next": "Your answer is the text compose_answer returns, shown unchanged: never write the table or the picks yourself. Order: task_plan -> the recipe tool -> run its script in Chrome -> compose_answer -> check_answer. The script's answer comes in parts (`part 1 of N`): run `window.__mytParts[1]`, `[2]` ... in the same tab with the javascript tool and pass EVERY part, unchanged, as its own item of site_results (only when the answer says `part 1 of N`; an `ingest` receipt has no parts).",
        "url": url, "expect_sort": label, "start_page": start_page, "script": script,
        "steps": ["Open `url` in the operator's logged-in RateHawk tab (Claude in Chrome navigate). If the page asks to log in, stop and tell the operator.",
                  "Wait about 10 seconds until the results show, then run `script` with the javascript tool (it only reads the page and presses Forward).",
                  "If its answer has ok=false, do what `error` says (usually: open the url again) and run it once more; never read the list by eye instead.",
                  "The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row. Only if the operator asks for the best rated, run the recipe again with sort='rating' and pass those parts too.",
                  "Children: the url already has them (guests=2and6 means 2 adults and a child of 6). One child was tested; with two or more, check the page's guest count says the same."],
        "never": "Do not retype, shorten or summarise the rows: compose_answer reads the script's own text.",
    }


def _price(text: str | None) -> tuple[float | None, str | None]:
    m = re.match(r"^([A-Z]{3})\s?([\d,]+(?:\.\d+)?)$", (text or "").strip())
    return (float(m.group(2).replace(",", "")), m.group(1)) if m else (None, None)


def _int(text: str | None) -> int | None:
    m = re.search(r"[\d,]+", text or "")
    return int(m.group(0).replace(",", "")) if m else None


def offers_from_ratehawk(results: list[str], urls: list[str], wishes: dict[str, Any] | None, group: str) -> tuple[list[Offer], list[SourceRead], list[str], bool]:
    """Turns the recipe's own JSON into Offers (no retyping by Claude). Returns offers, the source entry, problems, and whether a price-sorted list was read."""
    wishes = wishes or {}
    problems: list[str] = []
    by_path: dict[str, Offer] = {}
    read = 0
    total: int | None = None
    sorted_by_price = False
    for i, raw in enumerate(results):
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            problems.append(f"ratehawk_results[{i}] is not the script's JSON text: pass its answer unchanged")
            continue
        if not data.get("ok"):
            problems.append(f"the RateHawk script reported: {data.get('error', 'not ok')}")
            continue
        if data.get("header_settled") is False:
            problems.append("RateHawk was still adding results when the list was read (the count in its header kept changing): open the url again and run the script once more")
        if "filters_ticked" in data:        # a filter RateHawk kept from an earlier visit would change the list without the operator asking for it
            allowed = {"Breakfast included"} if wishes.get("breakfast") else set()
            allowed |= {"Free cancellation available"} if wishes.get("free_cancellation") else set()
            extra = [f for f in data["filters_ticked"] if f not in allowed]
            if extra or (data.get("unlabelled_ticked") and not wishes.get("stars_min")):
                problems.append(f"RateHawk shows filters the operator did not ask for ({', '.join(extra) or 'a star or other box'}): clear them on the page, open the url again and run the script once more")
        if data.get("start_page") != data.get("expected_start", 1):
            problems.append(f"the RateHawk list was read from page {data.get('start_page')}, not from page {data.get('expected_start', 1)}")
        if data.get("stopped") and "page counter" in str(data["stopped"]):
            problems.append(f"the RateHawk reader stopped early: {data['stopped']}")
        want = {"Price (low to high)": "ascending", "Price (high to low)": "descending"}.get(str(data.get("sort", "")))      # a rating-sorted list has no price order
        if want and data.get("price_order") != want:
            problems.append(f"the prices of the RateHawk list are {data.get('price_order')}, not {want}: the page may have changed while reading")
        read = max(read, int(data.get("rows_read") or 0))
        total = total or _int(data.get("header"))
        if data.get("sort") == "Price (low to high)":
            sorted_by_price = True
        for r in data.get("rows", []):
            price, cur = _price(r.get("price"))
            meal = r.get("meal") or ""
            canc = r.get("cancellation") or ""
            stars = r.get("stars")
            fits: bool | None = None
            if wishes:
                ok = True
                if wishes.get("breakfast"):
                    ok &= bool(re.search(r"breakfast|half board|full board|all inclusive", meal, re.I)) and "no meals" not in meal.lower()
                if wishes.get("free_cancellation"):
                    ok &= canc.lower().startswith("free cancellation")
                if wishes.get("stars_min"):
                    ok &= bool(stars) and stars >= int(wishes["stars_min"])
                ok &= meets_limits(price, r.get("distance"), wishes)
                fits = ok
            path = r.get("path") or f"{r.get('name')}-{r.get('price')}"
            offer = Offer(group=group, source="RateHawk", name=r.get("name") or "not shown", price_total=price, currency=cur,
                          price_basis=(r.get("basis") or "whole stay").replace("for ", "whole stay: ", 1),
                          details={"stars": stars, "score": r.get("score"), "reviews": _int(r.get("reviews")), "distance_from_centre": r.get("distance"),
                                   "meal": meal or None, "cancellation": canc or None, "room_bed": " / ".join(x for x in (r.get("room"), r.get("bed")) if x) or None},
                          flexible=canc.lower().startswith("free cancellation") or None, fits=fits, supplier=r.get("name"),
                          link=("https://www.ratehawk.com" + r["path"]) if r.get("path") else None)
            by_path.setdefault(path, offer)
    link = urls[0] if urls else None
    source = SourceRead(name="RateHawk", read=len(by_path) or None, of=total, link=link)
    if total is not None and len(by_path) > total:
        problems.append("more hotels were read than the page header says exist: the data is not trustworthy")
    return list(by_path.values()), [source], problems, sorted_by_price


def offset_given(result_json: str) -> bool:
    try:
        return bool(json.loads(result_json).get("offset"))
    except (TypeError, ValueError, AttributeError):
        return False


def convert(result_json: str, wishes: dict[str, Any], group: str) -> SiteRows:
    offers, sources, problems, by_price = offers_from_ratehawk([result_json], [], wishes, group)
    notes: list[str] = []
    try:
        offset = int(json.loads(result_json).get("offset") or 0)
    except (TypeError, ValueError, AttributeError):
        offset = 0
    if offset > 0 and offers:
        notes.append(f"These are options {offset + 1} to {offset + len(offers)} of the list (cheaper ones were shown before): the Cheapest here is not the cheapest overall.")
    if by_price and not offset_given(result_json):
        notes.append(f"RateHawk's list was read sorted by price (low to high): {sources[0].read} of {sources[0].of or 'its'} hotels, the cheapest first.")
    return SiteRows(offers=offers, read=sources[0].read, total=sources[0].of, problems=problems, sorted_by_price=by_price, extra_notes=notes)


ASK = {"stars": "Minimum star rating? (3, 4, 5 or no preference)", "budget": "Budget per night, in EUR? (or no preference)",
       "distance": "How far from the centre, or which area? (a distance in km, a neighbourhood, or no preference)"}
BATCH = 30          # items shown per batch; the operator can ask for the next batch


def ask_gate(stars: int | None, budget_per_night: float | None, max_distance_km: float | None, operator_answered: bool) -> dict[str, Any] | None:
    """Nothing is read until the operator has said what they want: stars, budget and distance (each may be 'no preference'). Returns the questions, or None."""
    missing = [q for q, given in ((ASK["stars"], stars is not None), (ASK["budget"], budget_per_night is not None), (ASK["distance"], max_distance_km is not None)) if not given]
    if not missing or operator_answered:
        return None
    return {"ok": False, "ask_operator": missing, "searched": False,
            "next": "Nothing was opened. Ask the operator these questions in ONE message (add the breakfast / free cancellation / children's ages question only if the request did not say them), "
                    "wait for the reply, then call this tool again with the answers. For 'no preference' leave that value out and set operator_answered=true "
                    "(only after the operator replied in this chat)."}


def limits(stars: int | None, budget_per_night: float | None, max_distance_km: float | None, breakfast: bool, free_cancellation: bool, nights: int) -> tuple[dict[str, Any], list[str]]:
    """The operator's wishes for compose_answer, and the same as 'Filters used' lines."""
    wishes = {"breakfast": breakfast, "free_cancellation": free_cancellation, "stars_min": stars, "max_distance_km": max_distance_km,
              "max_total": budget_per_night * nights if budget_per_night is not None else None}
    filters = [f"{label} (operator)" for on, label in ((breakfast, "Breakfast included"), (free_cancellation, "Free cancellation")) if on]
    filters += [f"{stars}+ stars (operator)"] if stars else []
    filters += [f"budget up to {budget_per_night:g} per night, {budget_per_night * nights:g} for {nights} night(s) (operator)"] if budget_per_night is not None else []
    filters += [f"within {max_distance_km:g} km of the centre (operator)"] if max_distance_km is not None else []
    return wishes, filters


def register(mcp: MCPServer) -> None:
    @mcp.tool(name="ratehawk_hotels_recipe", annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
    @tool_errors
    async def ratehawk_hotels_recipe_tool(country: str, city: str, check_in: date, check_out: date, adults: int = 2, sort: str = "price_asc",
                                          breakfast: bool = False, free_cancellation: bool = False, stars: int | None = None, budget_per_night: float | None = None,
                                          max_distance_km: float | None = None, operator_answered: bool = False, offset: int = 0, limit: int = BATCH,
                                          children_ages: list[int] | None = None) -> dict[str, Any]:
        """FOR HOTELS ON RATEHAWK (THE SERVER READS THE PAGE ITSELF in its own logged-in browser, because RateHawk's hotel pages do not let the operator's Chrome send data to the server: you open nothing and run no script; the answer is a short receipt with an `ingest` id: call compose_answer with `runs`=[that id]; ok=false: put RateHawk in not_checked with the reason it gives and never type a row; if the server has no browser it returns the url and a script for the operator's Chrome instead). ASK FIRST: without minimum `stars`, `budget_per_night` (EUR) and
        `max_distance_km` this tool opens nothing and returns `ask_operator`: ask those questions in ONE message, wait for the reply, call again with the
        answers (`operator_answered`=true for "no preference", only after the operator replied). Then it returns the exact results URL (filters already in
        it) and a tested read-only SCRIPT: open the url, run the script with the javascript tool; it reads the next `limit` (30) hotels from `offset`, checks the
        sort, the page and the count. The script sends its answer from the page to the server by itself and returns a short receipt (it holds the `ingest` id): then call compose_answer with `runs`=[that id]; never type or pass a row with the returned `wishes` and `filters_used`. When the operator wants more, call this tool again with offset=offset+limit.
        Never read the list by eye. `country` and `city` are the words in RateHawk's address (portugal, lisbon). Give `children_ages` for children."""
        asked = ask_gate(stars, budget_per_night, max_distance_km, operator_answered)
        if asked:
            return asked
        out = ratehawk_hotels_recipe(country, city, check_in, check_out, adults, sort, breakfast, free_cancellation, stars, 3, children_ages, offset, limit)
        wishes, filters = limits(stars, budget_per_night, max_distance_km, breakfast, free_cancellation, (check_out - check_in).days)
        out["wishes"], out["filters_used"] = wishes, filters + ["Guests: " + " and ".join([f"{adults} adults"] + [f"child {a}" for a in children_ages or []]) + " (operator)"]
        out["more"] = f"For the next {limit} hotels call this tool again with the same values and offset={offset + limit}; say so to the operator at the end of the answer."
        if server_reads("RATEHAWK_HOTELS_READ_IN_SERVER", default=False):
            # ratehawk.com's hotel pages only let the page talk to RateHawk's own hosts (default-src), so the operator's Chrome cannot send the answer to this server; the server reads the list in its
            # automation Chrome (logged in to RateHawk). OFF by default again since GetYourGuide blocked the shared IP on 24 Oct 2026: RATEHAWK_HOTELS_READ_IN_SERVER=1 switches it on. It is the agency's own login: see the safeguards of read_in_server_browser.
            result = await read_in_server_browser(NAME, "https://www.ratehawk.com", out["url"], out)
            result["more"] = out["more"]
            return result
        return out
