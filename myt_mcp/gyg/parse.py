"""GetYourGuide activity page data -> what the Claude GetYourGuide connector does not give:
slot-wise availability, the exact price for the group, start times, meeting point, cancellation, inclusions.

Two sources, both read through the automation browser (see client.py):
- the activity page: `window.__INITIAL_STATE__` (traveller categories with their age limits, highlights, includes)
- the availability service answer for one date and group: a server-driven UI tree. Its visible texts, read in
  order, hold the options, start times and prices ("2 Adult × €18.00", "Total price", "€36.00").
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from myt_mcp.checks import close
from myt_mcp.labels import activity_shortlist

_MONEY = re.compile(r"^(?:€|EUR\s?)\s?([\d.,]+)$")
_TIME = re.compile(r"^\d{1,2}:\d{2}\s?(?:AM|PM)$", re.I)
_LINE = re.compile(r"^(\d+)\s+(.+?)\s+×\s+€\s?([\d.,]+)$")
_SECTION_STOP = {"Meeting point", "Not included", "Not suitable for", "Important information", "Know before you go",
                 "What to bring", "Cancellation policy", "Excluded", "Additional information", "Customer reviews"}
_UNAVAILABLE = ("not available", "unavailable", "sold out", "no availability")


class AgeGroupError(ValueError):
    pass


def money(text: str) -> float | None:
    m = _MONEY.match(text.strip())
    if not m:
        return None
    try:
        return round(float(m[1].replace(",", "")), 2)
    except ValueError:
        return None


def texts(node: Any, out: list[str] | None = None) -> list[str]:
    """Every visible text of a server-driven UI tree, in reading order."""
    out = [] if out is None else out
    if isinstance(node, dict):
        value = node.get("text")
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
        for key, child in node.items():
            if key not in ("controller", "layoutModifier", "overrides", "script", "meta", "styles"):
                texts(child, out)
    elif isinstance(node, list):
        for child in node:
            texts(child, out)
    return out


def state_from_script(script: str) -> dict[str, Any]:
    """The JSON object after `window.__INITIAL_STATE__ =` in the page's script."""
    start = script.index("{", script.index("__INITIAL_STATE__"))
    state, _ = json.JSONDecoder().raw_decode(script[start:])
    return state


def activity_id_from_url(url: str) -> int | None:
    m = re.search(r"-t(\d+)/?(?:[?#]|$)", url)
    return int(m[1]) if m else None


def _find_key(node: Any, key: str, depth: int = 0) -> Any:
    if depth > 40:
        return None
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for child in node.values():
            found = _find_key(child, key, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _find_key(child, key, depth + 1)
            if found is not None:
                return found
    return None


def _section(tokens: list[str], heading: str, stop: set[str]) -> list[str]:
    if heading not in tokens:
        return []
    out = []
    for t in tokens[tokens.index(heading) + 1:]:
        if t in stop or t.startswith("DESC:"):
            break
        out.append(t)
    return out


_ITEM_ID = re.compile(r"^(inclusion|exclusion)-\d+$")


def _listed_items(node: Any, found: dict[str, list[str]], depth: int = 0) -> None:
    """The page lists what is included (check icon, ids 'inclusion-N') and what is not (cross icon, ids 'exclusion-N') in one
    'Includes' list; the text alone does not tell them apart ('Hotel pickup and drop-off' is a cross)."""
    if depth > 60:
        return
    if isinstance(node, dict):
        match = _ITEM_ID.match(str(node.get("id") or ""))
        if match and node.get("type") == "granular":
            found[match[1]].extend(" ".join(x.split()) for x in texts(node) if x.strip())
            return
        for child in node.values():
            _listed_items(child, found, depth + 1)
    elif isinstance(node, list):
        for child in node:
            _listed_items(child, found, depth + 1)


def activity_info(state: dict[str, Any]) -> dict[str, Any]:
    """Title, id, traveller categories, highlights, includes and the cancellation sentence from the page state."""
    activity = state.get("activity") or {}
    sdui = state.get("sdui") or {}
    tokens = texts(sdui)
    participants = _find_key(sdui, "participants") or []
    categories = [{
        "id": p["categoryId"], "name": p.get("title"), "min_age": p.get("minimumAge"), "max_age": p.get("maximumAge"),
        "min_travellers": p.get("minimumParticipants"), "max_travellers": p.get("maximumParticipants"),
    } for p in participants if isinstance(p, dict) and isinstance(p.get("categoryId"), int)]
    heading_stop = _SECTION_STOP | {"Full description", "Includes"}
    listed: dict[str, list[str]] = {"inclusion": [], "exclusion": []}
    _listed_items(sdui, listed)
    return {
        "activity_id": activity.get("id"),
        "title": activity.get("title"),
        "categories": categories,
        "highlights": _section(tokens, "Highlights", heading_stop),
        "includes": listed["inclusion"] or ([] if listed["exclusion"] else _section(tokens, "Includes", _SECTION_STOP)),
        "not_included": listed["exclusion"],
        "cancellation": next((t for t in tokens if t.lower().startswith("cancel up to")), None),
        "visitor_id": (re.search(r'"visitorId"\s*:\s*"([A-Z0-9]{8,})"', json.dumps(state)) or [None, None])[1],
    }


def participants_for(categories: list[dict[str, Any]], adults: int, child_ages: list[int]) -> tuple[list[dict[str, int]], dict[str, int]]:
    """GetYourGuide traveller categories are per activity (e.g. Adult 4-99, Child 0-3). Put each traveller in the
    category whose age range holds their age. Returns ([{categoryId, count}], {category name: count})."""
    if not categories:
        raise AgeGroupError("Could not read this activity's traveller categories; check the activity page.")
    counts = {c["id"]: 0 for c in categories}
    ages = [30] * adults + list(child_ages)   # adults have no age: any adult age (30) falls in the adult group
    for age in ages:
        fits = [c for c in categories if (c["min_age"] if c["min_age"] is not None else 0) <= age <= (c["max_age"] if c["max_age"] is not None else 120)]
        if not fits:
            accepted = ", ".join(f"{c['name']} {c['min_age']}-{c['max_age']}" for c in categories)
            raise AgeGroupError(f"This activity does not take a traveller aged {age} (age groups: {accepted}).")
        best = min(fits, key=lambda c: (c["max_age"] or 120) - (c["min_age"] or 0))   # the narrowest group that fits
        counts[best["id"]] += 1
    names = {c["id"]: c["name"] for c in categories}
    return ([{"categoryId": cid, "count": n} for cid, n in counts.items()],
            {names[cid]: n for cid, n in counts.items() if n})


def long_date(day: date) -> str:
    return f"{day:%A}, {day:%B} {day.day}, {day.year}"


def parse_availability(answer: dict[str, Any]) -> dict[str, Any]:
    """The options, start times and prices in an availability answer."""
    tokens = [" ".join(t.replace("\u202f", " ").replace("\xa0", " ").split()) for t in texts(answer.get("content"))]
    header = next((t for t in tokens if (t.lower().startswith("choose from") and "option" in t.lower()) or re.match(r"^\d+ options? available$", t, re.I)), None)
    if not header:
        reasons = [t for t in tokens if any(m in t.lower() for m in _UNAVAILABLE) and len(t) < 120]
        return {"any_available": False, "options": [], "note": next((r for r in reasons if "day" in r.lower() or "date" in r.lower()), reasons[0] if reasons else
                                                                    "GetYourGuide shows no options for this date and group."), "dates_seen": []}
    start = tokens.index(header) + 1
    segments, current = [], []
    for t in tokens[start:]:
        current.append(t)
        if t == "Add to cart":
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    options = []
    for seg in segments:
        if "Tour option" not in seg or seg.index("Tour option") + 1 >= len(seg):
            continue
        option = _option(seg)
        if option:
            options.append(option)
    return {"any_available": bool(options), "options": options, "note": None,
            "dates_seen": sorted({t for t in tokens[start:] if re.match(r"^[A-Z][a-z]+day, [A-Z][a-z]+ \d{1,2}, \d{4}$", t)})}


def _option(seg: list[str]) -> dict[str, Any] | None:
    title = seg[seg.index("Tour option") + 1]
    cancellation = [t for t in seg if re.match(r"^(cancel|free cancellation|non-?refundable)", t, re.I) and len(t) < 90]
    meeting = next((t for t in seg if t.startswith(("Meet at", "Pickup", "Pick-up"))), None)
    times: list[dict[str, Any]] = []
    for t in seg[seg.index("Select a starting time") + 1:] if "Select a starting time" in seg else []:
        if _TIME.match(t):
            times.append({"time": " ".join(t.upper().split()), "price_lines": [], "_money": []})
        elif times:
            line = _LINE.match(t)
            if line:
                times[-1]["price_lines"].append({"travellers": int(line[1]), "group": line[2], "price_each": float(line[3].replace(",", ""))})
            elif t == "Total price":
                times[-1]["_total_next"] = True
            elif money(t) is not None and times[-1].get("_total_next"):
                times[-1]["_money"].append(money(t))
            elif re.match(r"^-\d+%$", t):
                times[-1]["discount"] = t
            elif t.lower().startswith("all taxes and fees included"):
                times[-1]["taxes_included"] = True
            elif money(t) is not None and times[-1]["price_lines"]:
                times[-1].setdefault("_line_totals", []).append(money(t))
    for entry in times:
        amounts = entry.pop("_money")
        entry.pop("_total_next", None)
        entry.pop("_line_totals", None)
        entry["total_price"] = amounts[0] if amounts else None
        entry["price_before_discount"] = amounts[1] if len(amounts) > 1 and amounts[1] != amounts[0] else None
        entry["currency"] = "EUR"
    return {
        "option": title,
        "duration": next((t.split(":", 1)[1].strip() for t in seg if t.startswith("Duration:")), None),
        "language": next((t.split(":", 1)[1].strip() for t in seg if t.startswith("Instructor:")), None),
        "cancellation": cancellation[0] if cancellation else None,
        "pay_later": "Reserve now & pay later" in seg,
        "meeting_point": meeting.removeprefix("Meet at ").strip() if meeting else None,
        "start_times": times,
        **({} if times else {"note": "GetYourGuide lists no start times or prices for this option in this view; check the activity page."}),
    }


def check_availability(parsed: dict[str, Any], day: date, total_travellers: int) -> list[str]:
    """The answer must be for the asked day, in EUR, for the whole group, and its prices must add up."""
    problems = []
    seen = parsed.get("dates_seen") or []
    if parsed["any_available"] and seen and seen != [long_date(day)]:
        problems.append(f"answer is for {', '.join(seen)}, not {long_date(day)}")
    for option in parsed["options"]:
        for t in option["start_times"]:
            lines = t["price_lines"]
            if t["total_price"] is None or not lines:
                problems.append(f"{option['option']!r} at {t['time']} has no price")
                break
            if sum(line["travellers"] for line in lines) != total_travellers:
                problems.append(f"{option['option']!r} at {t['time']} is priced for "
                                f"{sum(line['travellers'] for line in lines)} travellers, not {total_travellers}")
                break
            if not close(sum(line["travellers"] * line["price_each"] for line in lines), t["total_price"], 0.05):
                problems.append(f"{option['option']!r} at {t['time']}: total {t['total_price']} does not add up")
                break
    return problems


def group_note(option: dict[str, Any], requested: dict[str, int]) -> str | None:
    """GetYourGuide prices each option by its own traveller groups (a child may be charged as an adult)."""
    for t in option["start_times"]:
        charged: dict[str, int] = {}
        for line in t["price_lines"]:
            charged[line["group"]] = charged.get(line["group"], 0) + line["travellers"]
        if charged and charged != requested:
            return (f"GetYourGuide priced this option as {', '.join(f'{n} {g}' for g, n in charged.items())}, "
                    f"not as {', '.join(f'{n} {g}' for g, n in requested.items())}: this option has no price for that traveller group.")
    return None


SORTS = ("popularity", "price", "rating", "reviews", "duration")
PAGE_SIZE = 24      # results per GetYourGuide search page
MIN_REVIEWS_FOR_RATING_SORT = 20    # a 5.0 from one review does not outrank a 4.9 from 800
_DETAIL_TYPES = {"smallGroup": "Small group", "bookableAsPrivate": "Private option available", "private": "Private", "skipTheLine": "Skip the line",
                 "wheelchairAccessible": "Wheelchair accessible", "transportationIncluded": "Transport included", "audioguide": "Audio guide"}
_BADGE_TEXTS = {"top pick", "top rated", "new activity", "likely to sell out", "best seller", "bestseller"}


def _card_data(node: Any) -> dict[str, Any] | None:
    """The activity record GetYourGuide embeds in each search card (price, reviews, attributes, availability)."""
    if isinstance(node, dict):
        if "review_statistics" in node and "price" in node and "attributes" in node:
            return node
        node = list(node.values())
    if isinstance(node, list):
        for child in node:
            found = _card_data(child)
            if found:
                return found
    return None


def _texts(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [node["text"]] if isinstance(node.get("text"), str) else [x for v in node.values() for x in _texts(v)]
    if isinstance(node, list):
        return [x for v in node for x in _texts(v)]
    return []


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def search_page(answer: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    """One answer of GetYourGuide's search service -> (rows, total results). Prices are the "from" price in EUR,
    per person or per group as the card says; the exact price for a date and group comes from the details tool."""
    grid = next((b for b in answer.get("content") or [] if isinstance(b, dict) and b.get("id") == "activities-grid"), None)
    rows: list[dict[str, Any]] = []
    for card in (grid or {}).get("content") or []:
        data = _card_data(card)
        if not data or not data.get("url"):
            continue
        attributes = {a.get("type"): a.get("label") for a in data["attributes"] if isinstance(a, dict)}
        price, stats, availability = data.get("price") or {}, data.get("review_statistics") or {}, data.get("availability") or {}
        reviews = stats.get("quantity") or 0
        city = re.search(r'"classifier_label\\?":\\?"([^"\\]+)', json.dumps(card))
        link = data["url"].split("?")[0]
        link = link if link.startswith("http") else f"https://www.getyourguide.com{link}"
        badges = list(dict.fromkeys(x for x in _texts(card) if x.lower() in _BADGE_TEXTS))
        rows.append({
            "activity_id": data.get("tour_id") or data.get("id"), "title": " ".join(str(data.get("title") or "").split()), "url": link,
            "city": city[1] if city else None, "duration": attributes.get("duration"),
            "from_price": _number(price.get("starting_price")), "currency": price.get("currency"),
            "price_basis": "per group" if price.get("price_category") == "group" else "per person",
            "rating": round(stats["rating"], 1) if reviews and _number(stats.get("rating")) else None, "reviews": reviews or None,
            "free_cancellation": "freeCancellation" in attributes,
            "details": [label for kind, label in _DETAIL_TYPES.items() if kind in attributes],
            "badges": badges,
            "available_on_date": availability.get("message") if availability.get("type") in ("positive", "urgent") else None,
            "first_start": availability.get("next_available_date_time"),
            "book_at_least": (attributes.get("cutOffTime") or "").replace("Must book at least ", "") or None,
        })
    tracked = [e.get("event", {}).get("properties", {}) for e in answer.get("trackingEvents") or [] if isinstance(e, dict)]
    total = next((p.get("result_count") for p in tracked if isinstance(p.get("result_count"), int)), None)
    return rows, total


def duration_minutes(text: str | None) -> int | None:
    """'2 - 2.5 hours' -> 120 (the shortest), '45 minutes' -> 45, '11 days' -> 15840."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)(?:\s*-\s*\d+(?:\.\d+)?)?\s*(minute|hour|day)", text or "")
    return round(float(m[1]) * {"minute": 1, "hour": 60, "day": 1440}[m[2]]) if m else None


def sort_rows(rows: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    """GetYourGuide's own order is by popularity (its price sort ranks all results of the city, not the search words), so every other
    order is made here from the results read. Rows without the value go last; group-priced rows come after per-person rows;
    by rating, results with fewer than 20 reviews come after the well-reviewed ones."""
    big = 10 ** 9
    keys = {
        "price": lambda r: (r.get("price_basis") == "per group", r["from_price"] if r.get("from_price") is not None else big, -(r.get("reviews") or 0)),
        "rating": lambda r: ((r.get("reviews") or 0) < MIN_REVIEWS_FOR_RATING_SORT, -(r.get("rating") or 0), -(r.get("reviews") or 0)),
        "reviews": lambda r: (-(r.get("reviews") or 0), -(r.get("rating") or 0)),
        "duration": lambda r: (duration_minutes(r.get("duration")) or big, r["from_price"] if r.get("from_price") is not None else big),
    }
    return sorted(rows, key=keys[sort_by]) if sort_by in keys else rows


def shortlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return activity_shortlist(rows, "activity_id", MIN_REVIEWS_FOR_RATING_SORT)


def price_range(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    prices = sorted(r["from_price"] for r in rows if r.get("from_price") is not None and r.get("price_basis") == "per person")
    if not prices:
        return None
    mid = len(prices) // 2
    median = prices[mid] if len(prices) % 2 else round((prices[mid - 1] + prices[mid]) / 2, 2)
    return {"min": prices[0], "median": median, "max": prices[-1], "of_results": len(prices), "per": "person", "currency": "EUR"}


def check_search(rows: list[dict[str, Any]]) -> list[str]:
    """Every result must carry a GetYourGuide activity link and a title (so no guessed or empty links are passed on)."""
    problems = []
    for row in rows:
        if not re.match(r"^https://www\.getyourguide\.com/.+-t\d+/?$", row["url"]):
            problems.append(f"result {row.get('title')!r} has no GetYourGuide activity link")
        if not row.get("title"):
            problems.append(f"result {row['activity_id']} has no title")
    return problems
