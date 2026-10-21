"""Fixed browser recipes: a URL and a script that the operator's own logged-in Chrome runs through Claude in Chrome.

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

from myt_mcp.compose import Offer, SourceRead

RECIPES = Path(__file__).parent / "recipes"
# the sort values RateHawk's own list uses (tested 21 Oct 2026): URL value -> the label the page shows
RATEHAWK_SORTS = {"price_asc": ("price.asc", "Price (low to high)"), "price_desc": ("price", "Price (high to low)"), "rating": ("rating", "Guests' rating (high to low)")}


def ratehawk_hotels_recipe(country: str, city: str, check_in: date, check_out: date, adults: int, sort: str = "price_asc", breakfast: bool = False,
                           free_cancellation: bool = False, stars: int | None = None, max_pages: int = 3, children_ages: list[int] | None = None) -> dict[str, Any]:
    if sort not in RATEHAWK_SORTS:
        raise ValueError(f"sort must be one of {sorted(RATEHAWK_SORTS)}")
    if not 1 <= max_pages <= 10:
        raise ValueError("max_pages must be between 1 and 10 (20 hotels a page)")
    if check_out <= check_in:
        raise ValueError("check_out must be after check_in")
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
    if stars:
        params.append(("stars", str(stars)))
    value, label = RATEHAWK_SORTS[sort]
    params += [("sort", value), ("page", "1")]
    url = f"https://www.ratehawk.com/hotel/{slug(country)}/{slug(city)}/?{urlencode(params)}"
    script = (RECIPES / "ratehawk_hotels.js").read_text(encoding="utf-8").replace("__MAX_PAGES__", str(max_pages)).replace("__EXPECT_SORT__", label)
    return {
        "url": url, "expect_sort": label, "script": script,
        "steps": ["Open `url` in the operator's logged-in RateHawk tab (Claude in Chrome navigate). If the page asks to log in, stop and tell the operator.",
                  "Wait about 10 seconds until the results show, then run `script` with the javascript tool (it only reads the page and presses Forward).",
                  "If its answer has ok=false, do what `error` says (usually: open the url again) and run it once more; never read the list by eye instead.",
                  "Pass the answer text, unchanged, as `ratehawk_results` (and this `url` as `ratehawk_urls`) to compose_answer. Run the recipe a second time with sort='rating' and pass both.",
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
        if data.get("start_page") != 1:
            problems.append("the RateHawk list was not read from page 1")
        if data.get("stopped") and "page counter" in str(data["stopped"]):
            problems.append(f"the RateHawk reader stopped early: {data['stopped']}")
        if data.get("price_order") == "mixed":
            problems.append("the prices of the RateHawk list are not in one order: the page may have changed while reading")
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
