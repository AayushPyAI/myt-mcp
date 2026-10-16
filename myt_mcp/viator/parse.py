"""Turn Viator page data (the `globalState` JSON embedded in every page) into compact rows."""

from __future__ import annotations

import html
import re
from datetime import date, timedelta
from typing import Any

from myt_mcp.checks import close
from myt_mcp.labels import activity_shortlist

_TAG = re.compile(r"<[^>]+>")


def _text(v: Any, limit: int = 400) -> str | None:
    if isinstance(v, dict):
        v = v.get("text")
    if not isinstance(v, str):
        return None
    t = " ".join(html.unescape(_TAG.sub(" ", v)).split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def _duration_from_minutes(minutes: Any) -> str | None:
    if not isinstance(minutes, (int, float)) or minutes <= 0:
        return None
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m}m" if h and m else (f"{h}h" if h else f"{m}m")


def _search_duration(itinerary: Any) -> str | None:
    d = (itinerary or {}).get("duration") or {}
    if d.get("unit") == "MINUTES":
        return _duration_from_minutes(d.get("duration"))
    lo, hi = d.get("minDuration"), d.get("maxDuration")
    if lo and hi:
        return f"{_duration_from_minutes(lo)} – {_duration_from_minutes(hi)}"
    return None


def search_results(state: dict[str, Any]) -> dict[str, Any]:
    return (((state.get("__PRELOADED_DATA__") or {}).get("pageModel") or {}).get("preloadedData") or {}).get("search") or {}


def summarize_search(state: dict[str, Any], urls: dict[str, str], max_results: int) -> tuple[list[dict[str, Any]], int, int]:
    """(rows, total results on Viator, skipped)."""
    search = search_results(state)
    rows, skipped = [], 0
    for r in search.get("results") or []:
        item = r.get("item") if isinstance(r, dict) else None
        if not isinstance(item, dict) or not item.get("productCode"):
            skipped += 1
            continue
        code = item["productCode"]
        price = ((item.get("pricingInfo") or {}).get("fromPrice") or {})
        review = item.get("reviewSummary") or {}
        rows.append({
            "code": code,
            "title": _text(item.get("title"), 160) or item.get("canonicalName"),
            "from_price": price.get("amount"),
            "currency": price.get("currency"),
            "price_varies_by_group_size": bool((item.get("pricingInfo") or {}).get("priceVariesByGroupSize")),
            "rating": review.get("exactRating"),
            "reviews": review.get("count"),
            "duration": _search_duration(item.get("itinerary")),
            "free_cancellation": bool((item.get("cancellationPolicy") or {}).get("freeCancellation")),
            "languages": [lang.get("code") for lang in item.get("offeredLanguages") or [] if isinstance(lang, dict)],
            "badges": [b.get("type") for b in item.get("productBadges") or [] if isinstance(b, dict)],
            "destination": (item.get("primaryDestination") or {}).get("name"),
            "summary": _text(item.get("description"), 220),
            "url": urls.get(code),
        })
        if len(rows) >= max_results:
            break
    return rows, search.get("totalResults") or len(rows), skipped


def _location(point: dict[str, Any]) -> dict[str, Any]:
    loc = ((point.get("locationData") or {}).get("location") or {})
    return {
        "name": loc.get("name"),
        "address": (loc.get("address") or {}).get("readableFormat"),
        "instructions": _text(point.get("locationInstruction"), 300),
    }


def _start_times(schedules: dict[str, Any], on: date | None) -> list[dict[str, Any]]:
    """Per tour option: its start times in the season that contains `on` (all seasons when no date)."""
    by_grade = schedules.get("startTimesByTourGradeCode") or {}
    options = []
    for opt in schedules.get("tourOptions") or []:
        seasons = by_grade.get(opt.get("tourGradeCode")) or []
        times: list[str] = []
        for s in seasons:
            start, end = s.get("seasonStartDate"), s.get("seasonEndDate")
            if on and start and end and not (start <= on.isoformat() <= end):
                continue
            for t in s.get("startTimes") or []:
                label = t if isinstance(t, str) else (t or {}).get("time") or (t or {}).get("startTime")
                if label and label not in times:
                    times.append(label)
        options.append({"option": opt.get("title"), "start_times": times or None})
    return options


def availability(calendar: dict[str, Any], on: date | None, nearby: int = 5) -> dict[str, Any]:
    """Viator's price calendar lists only bookable dates, each with the cheapest per-person price that day
    (it is higher than the activity's general "from" price when the cheap options are sold out)."""
    dates: dict[str, Any] = calendar.get("dates") or {}
    result: dict[str, Any] = {"currency": calendar.get("currencyCode")}
    if on is None:
        result["next_available_dates"] = sorted(dates)[:nearby]
        return result
    day = dates.get(on.isoformat())
    result["date"] = on.isoformat()
    result["available"] = day is not None
    if day:
        result["price_per_person_from"] = day.get("formattedPrice")
        result["discounted"] = bool(day.get("isDiscounted"))
    else:
        later = sorted(d for d in dates if d > on.isoformat())[:nearby]
        earlier = sorted((d for d in dates if d < on.isoformat()), reverse=True)[:2]
        result["nearest_available_dates"] = sorted(earlier) + later
    return result


def _cancellation(policy: Any, free: Any) -> list[str] | None:
    if isinstance(policy, dict):
        lines = [_text(x, 300) for x in (policy.get("highlightedPolicies") or policy.get("policies") or [])]
        return [x for x in lines if x] or None
    text = _text(policy, 500)
    return [text] if text else (["Free cancellation"] if free else None)


def summarize_product(product: dict[str, Any], calendar: dict[str, Any], on: date | None) -> dict[str, Any]:
    d = product.get("description") or {}
    logistics = product.get("logisticsLocation") or {}
    schedules = (product.get("departureAndReturnLocations") or {}).get("tourOptionSchedules") or {}
    duration = product.get("duration") or {}
    dur_minutes = (duration.get("days") or 0) * 1440 + (duration.get("hours") or 0) * 60 + (duration.get("minutes") or 0)
    rating = product.get("rating") or {}
    price = ((product.get("pricing") or {}).get("price") or {}).get("retailPrice") or {}
    langs = product.get("productLanguages") or {}
    return {
        "code": product.get("productCode"),
        "title": _text(product.get("title"), 200),
        "supplier": product.get("supplierName"),
        "private_tour": bool(product.get("isPrivateTour")),
        "rating": rating.get("exactScore"),
        "reviews": rating.get("reviewCount"),
        "duration": _duration_from_minutes(dur_minutes),
        "lowest_price_any_date": price.get("amount"),
        "currency": price.get("currencyCode"),
        "availability": availability(calendar, on),
        "options": _start_times(schedules, on),
        "start_time_type": schedules.get("startTimeType"),
        "starts_at": _text(schedules.get("startsAt"), 40),
        "meeting_points": [_location(p) for p in logistics.get("meetingPoints") or []],
        "ends_at_start_point": bool(logistics.get("endsAtStartPoint")),
        "pickup_offered": bool(logistics.get("isPickupOffered")),
        "pickup_type": logistics.get("pickupOptionType"),
        "pickup_points": [_location(p) for p in logistics.get("pickupPoints") or []][:5] or None,
        "highlights": [_text(f, 160) for f in ((d.get("overview") or {}).get("features") or [])][:6],
        "overview": _text((d.get("overview") or {}).get("header"), 500),
        "included": [_text(f, 160) for f in ((d.get("inclusions") or {}).get("features") or [])],
        "not_included": [_text(f, 160) for f in ((d.get("exclusions") or {}).get("features") or [])],
        "cancellation_policy": _cancellation(d.get("cancellationPolicy"), product.get("hasFreeCancellation")),
        "languages": [lang.get("displayName") for lang in langs.get("offeredLanguages") or [] if isinstance(lang, dict)],
        "age_bands": [
            {"band": a.get("ageBand"), "ages": f"{a.get('ageMin')}-{a.get('ageMax')}"}
            for a in ((product.get("availabilityConfig") or {}).get("ageBandRanges") or [])
        ],
    }


class AgeBandError(ValueError):
    pass


def age_bands_for(product: dict[str, Any], adults: int, child_ages: list[int]) -> dict[str, int]:
    """Viator prices by the activity's own age bands (e.g. CHILD can be 4-11 on one tour and 0-3 on another)."""
    ranges = [r for r in (product.get("availabilityConfig") or {}).get("ageBandRanges") or [] if r.get("ageBand")]
    bands: dict[str, int] = {"ADULT": adults} if adults else {}
    for age in child_ages:
        band = next((r["ageBand"] for r in ranges if (r.get("ageMin") or 0) <= age <= (r.get("ageMax") or 120)), None)
        if band is None:
            accepted = ", ".join(f"{r['ageBand']} {r.get('ageMin')}-{r.get('ageMax')}" for r in ranges) or "not listed"
            raise AgeBandError(f"This activity does not take a traveller aged {age} (age groups: {accepted}).")
        bands[band] = bands.get(band, 0) + 1
    return bands


def _paid(price: Any) -> float | None:
    """What the customer pays: the discounted price when there is one. 0 means Viator gave no price."""
    price = price or {}
    amount = ((price.get("discountedPrice") or price.get("retailPrice")) or {}).get("amount")
    return amount if isinstance(amount, (int, float)) and amount > 0 else None


def _before_discount(price: Any) -> float | None:
    """The list price Viator crosses out, only when there is a real discount."""
    price = price or {}
    now = (price.get("discountedPrice") or {}).get("amount")
    was = (price.get("retailPrice") or {}).get("amount")
    ok = isinstance(now, (int, float)) and isinstance(was, (int, float)) and now > 0 and was > now
    return was if ok else None


def summarize_availability(answer: dict[str, Any]) -> dict[str, Any]:
    """Viator's availability check for one date and group: every option with its start times and total price."""
    grades = (answer.get("productAvailability") or {}).get("tourGrades") or []
    options = []
    for g in grades:
        times = [{
            "time": _text(t.get("startTime"), 20),
            "available": t.get("availabilityResult") == "AVAILABLE",
            "total_price": _paid(t.get("price")),
            "price_before_discount": _before_discount(t.get("price")),
        } for t in g.get("startTimes") or []]
        options.append({
            "option": _text(g.get("title"), 120),
            "available": bool(g.get("isAvailable")),
            "total_price_from": min((t["total_price"] for t in times if t["available"] and t["total_price"]), default=_paid(g.get("price"))),
            "currency": g.get("currency"),
            "start_times": times,
            "price_per_traveller": [{
                "age_group": b.get("ageBand"), "travellers": b.get("numberOfTravelers"),
                "price_each": _paid(b.get("price")), "total": _paid(b.get("totalPrice")),
            } for b in g.get("priceBreakdown") or []],
            "languages": g.get("languages"),
        })
    options.sort(key=lambda o: (not o["available"], o["total_price_from"] or float("inf")))
    cancel = answer.get("cancellationPolicyDetails") or {}
    return {
        "any_available": any(o["available"] for o in options),
        "options": options,
        "free_cancellation_until": cancel.get("refundEligibleUntilDate") if cancel.get("policyType") == "REFUNDABLE" else None,
        "refundable": cancel.get("policyType") == "REFUNDABLE" if cancel else None,
    }


def code_from_url(url: str) -> str | None:
    match = re.search(r"/d\d+-([A-Za-z0-9_.]+)(?:[/?#]|$)", url)
    return match[1] if match else None


def check_search(rows: list[dict[str, Any]]) -> list[str]:
    bad = sorted({r["currency"] for r in rows if r.get("currency") not in (None, "EUR")})
    return [f"prices are in {', '.join(bad)}, not EUR (switch Viator's currency to EUR in the automation browser)"] if bad else []


def check_product(product: dict[str, Any], calendar: dict[str, Any], url: str) -> list[str]:
    problems = []
    if code_from_url(url) and product.get("productCode") != code_from_url(url):
        problems.append(f"the page is activity {product.get('productCode')}, not {code_from_url(url)} from the link")
    currency = (((product.get("pricing") or {}).get("price") or {}).get("retailPrice") or {}).get("currencyCode")
    for label, value in (("activity", currency), ("calendar", calendar.get("currencyCode"))):
        if value not in (None, "EUR"):
            problems.append(f"{label} prices are in {value}, not EUR (switch Viator's currency to EUR in the automation browser)")
    return problems


def check_availability(answer: dict[str, Any], code: str, day: date, bands: dict[str, int]) -> list[str]:
    """The group check must be for this activity, this day and exactly these travellers, and add up."""
    problems = []
    for g in (answer.get("productAvailability") or {}).get("tourGrades") or []:
        if g.get("productCode") not in (None, code) or g.get("date") not in (None, day.isoformat()):
            problems.append(f"option {g.get('title')!r} is for {g.get('productCode')} on {g.get('date')}, not {code} on {day.isoformat()}")
            break
        if g.get("currency") not in (None, "EUR"):
            problems.append(f"prices are in {g.get('currency')}, not EUR")
            break
        for t in g.get("startTimes") or []:
            breakdown = t.get("priceBreakdown") or g.get("priceBreakdown") or []
            if t.get("availabilityResult") != "AVAILABLE" or not breakdown:
                continue
            counted = {b.get("ageBand"): b.get("numberOfTravelers") for b in breakdown}
            if counted != {k: v for k, v in bands.items() if v}:
                problems.append(f"priced for {counted} instead of {bands}")
                return problems
            parts = sum(_paid(b.get("totalPrice")) or 0 for b in breakdown)
            if not close(parts, _paid(t.get("price")), 0.05):
                problems.append(f"{g.get('title')!r} at {_text(t.get('startTime'), 20)}: total {_paid(t.get('price'))} does not add up ({parts})")
                return problems
    return problems


def bookable_on(calendar: dict[str, Any], day: date) -> bool:
    """True unless Viator's calendar (which lists only bookable days) is there and does not list `day`.
    Without a calendar we cannot tell, so the group check is allowed to run."""
    dates = calendar.get("dates") or {}
    return not dates or day.isoformat() in dates


def related(query: str, rows: list[dict[str, Any]]) -> bool:
    """Do any results contain a word of the search? (Viator pads thin searches with general results.)"""
    words = {w for w in re.findall(r"[^\W_]{4,}", query.lower())}
    if not words:
        return True
    text = " ".join(f"{r.get('title') or ''} {r.get('destination') or ''} {r.get('summary') or ''}".lower() for r in rows)
    return any(w in text or w.rstrip("s") in text for w in words)


PAGE_SIZE = 24      # results per Viator search page
SORTS = ("featured", "price", "rating", "reviews", "duration")
MIN_REVIEWS_FOR_RATING_SORT = 20    # a 5.0 from one review does not outrank a 4.9 from 800


def duration_minutes(text: str | None) -> int | None:
    """'2h 30m' -> 150, '1h 30m – 2h' -> 90 (the shortest), '45m' -> 45."""
    if not text:
        return None
    first = text.split("–")[0]
    h, m = re.search(r"(\d+)\s*h", first), re.search(r"(\d+)\s*m", first)
    total = (int(h.group(1)) * 60 if h else 0) + (int(m.group(1)) if m else 0)
    return total or None


def sort_rows(rows: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    """Viator cannot sort by price; we do. Rows without the value go last; by rating, results with fewer than 20 reviews
    come after the others. 'featured' keeps Viator's own order."""
    big = 10 ** 9
    keys = {
        "price": lambda r: (r["from_price"] if r.get("from_price") is not None else big, -(r.get("reviews") or 0)),
        "rating": lambda r: ((r.get("reviews") or 0) < MIN_REVIEWS_FOR_RATING_SORT, -(r.get("rating") or 0), -(r.get("reviews") or 0)),
        "reviews": lambda r: (-(r.get("reviews") or 0), -(r.get("rating") or 0)),
        "duration": lambda r: (duration_minutes(r.get("duration")) or big, r["from_price"] if r.get("from_price") is not None else big),
    }
    return rows if sort_by == "featured" else sorted(rows, key=keys[sort_by])


def shortlist(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return activity_shortlist(rows, "code", MIN_REVIEWS_FOR_RATING_SORT)


def price_range(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    prices = sorted(r["from_price"] for r in rows if r.get("from_price") is not None)
    if not prices:
        return None
    mid = len(prices) // 2
    median = prices[mid] if len(prices) % 2 else round((prices[mid - 1] + prices[mid]) / 2, 2)
    return {"min": prices[0], "median": median, "max": prices[-1], "of_results": len(prices), "currency": "EUR"}
