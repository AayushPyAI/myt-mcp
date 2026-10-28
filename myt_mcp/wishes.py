"""The operator's wishes, judged on EVERY row of an answer, whichever source it came from.

Each recipe gets the wishes of its own call, so a wish given to one list (a maximum of 50 EUR per person, 4 hours, rating 9) was never applied to the exact-price rows of the activity pages or to
another source's list (28 Oct 2026: tuk tuk tours at 80-130 EUR per person and day trips of 8 hours stayed in the answer as meeting every wish, and a pick had no rating at all).
Here the wishes of all the runs of one answer are put together once, and each row is judged on what it shows: a miss is `fits=False`, a wish the row cannot show is `unconfirmed`
(the row stays in the table, marked, and is never a pick), and a row that shows all of them is `fits=True`."""

from __future__ import annotations

import re
from typing import Any

from myt_mcp.compose import Offer, distance_km, mark_unconfirmed

_UNITS = {"day": 24.0, "hour": 1.0, "hr": 1.0, "minute": 1 / 60, "min": 1 / 60}


def shared_wishes(carried: dict[Any, dict[str, Any]], wishes: dict[str, Any] | None) -> dict[str, Any]:
    """The wishes every recipe of the answer shares: the strictest value wins. Ratings are put on 10 points (Viator and GetYourGuide rate on 5)."""
    out: dict[str, Any] = {}
    sources = [c.get("wishes") or {} for c in carried.values()] + ([wishes] if isinstance(wishes, dict) else [])
    for w in sources:
        e = w.get("expect") if isinstance(w.get("expect"), dict) else {}
        price = e.get("max_price", w.get("max_price"))
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            out["max_price_pp"] = min(out.get("max_price_pp", price), price)
        hours = e.get("max_hours", w.get("max_hours"))
        if isinstance(hours, (int, float)) and not isinstance(hours, bool):
            out["max_hours"] = min(out.get("max_hours", hours), hours)
        rating = e.get("min_rating_wish")                       # Booking.com: the wish on 10 points
        if rating is None and isinstance(e.get("min_rating"), (int, float)) and not isinstance(e.get("min_rating"), bool):
            rating = float(e["min_rating"]) * 2                  # Viator / GetYourGuide: 5 points
        if isinstance(rating, (int, float)):
            out["min_rating_10"] = max(out.get("min_rating_10", rating), rating)
        if w.get("free_cancellation") or e.get("free_cancellation"):
            out["free_cancellation"] = True
        stars = w.get("stars_min")                              # hotels: the stars and the distance asked on any one hotel recipe count for every hotel row of the answer
        if isinstance(stars, (int, float)) and not isinstance(stars, bool) and stars:
            out["stars_min"] = max(out.get("stars_min", stars), stars)
        km = w.get("max_distance_km")
        if isinstance(km, (int, float)) and not isinstance(km, bool):
            out["max_distance_km"] = min(out.get("max_distance_km", km), km)
    return out


def hours_range(text: Any) -> tuple[float, float] | None:
    """'2 hours 30 minutes' -> (2.5, 2.5); '1 hour - 5 hours' -> (1, 5); '1 to 4 hours' -> (1, 4); '50 minutes' -> (0.83, 0.83); nothing readable -> None."""
    parts = re.split(r"\s+to\s+|\s+-\s+", str(text or "").lower())
    values: list[float | None] = []
    unit_of_last = None
    for part in parts:
        found = re.findall(r"(\d+(?:\.\d+)?)\s*(day|hour|hr|minute|min)", part)
        if found:
            values.append(sum(float(n) * _UNITS[u] for n, u in found))
            unit_of_last = found[-1][1]
        else:
            bare = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*", part)
            values.append(float(bare.group(1)) if bare else None)       # '1' of '1 to 4 hours': the unit is the next part's
    if not parts or all(v is None for v in values):
        return None
    if values and values[0] is not None and len(parts) > 1 and not re.search(r"[a-z]", parts[0]) and unit_of_last:
        values[0] = values[0] * _UNITS[unit_of_last]
    known = [v for v in values if v is not None]
    return (min(known), max(known)) if known else None


def _rating10(o: Offer, text: Any) -> float | None:
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(text or ""))
    if not m:
        return None
    value = float(m.group(1))
    return value if "booking" in o.source.lower() else value * 2


def _page(link: str | None) -> str | None:
    return link.split("?")[0].split("#")[0].rstrip("/").lower() if link else None


def judge_activities(offers: list[Offer], shared: dict[str, Any]) -> None:
    """Apply the shared wishes to every activity row (lists and exact prices). The rating of an exact-price row is taken from the list row of the same page."""
    if not shared:
        return
    rating_of: dict[str, float] = {}
    for o in offers:
        page = _page(o.link)
        if page and not o.price_basis.startswith("whole group"):
            r = _rating10(o, o.details.get("rating"))
            if r is not None:
                rating_of[page] = r
    for o in offers:
        if o.fits is False or o.price_total is None:
            continue
        exact = o.price_basis.startswith("whole group")
        miss = False
        unknown: list[str] = []
        if exact and shared.get("max_price_pp") is not None:
            m = re.search(r"\((\d+) travellers", o.price_basis)
            if m and int(m.group(1)) > 0:
                miss = miss or o.price_total / int(m.group(1)) > float(shared["max_price_pp"])
            else:
                unknown.append("price per person")
        if shared.get("max_hours") is not None:
            span = hours_range(o.details.get("duration"))
            if span is None:
                unknown.append("duration")
            elif span[0] > float(shared["max_hours"]):
                miss = True
            elif span[1] > float(shared["max_hours"]):
                unknown.append("duration (a range that goes over the limit)")
        if shared.get("min_rating_10") is not None:
            rating = _rating10(o, o.details.get("rating")) if not exact else rating_of.get(_page(o.link) or "")
            if rating is None:
                unknown.append("rating")
            elif rating < float(shared["min_rating_10"]):
                miss = True
        if shared.get("free_cancellation") and o.flexible is None:
            unknown.append("free cancellation")
        if miss:
            o.fits = False
        elif unknown:
            for what in unknown:
                mark_unconfirmed(o, what)
        elif o.fits is None:
            o.fits = True


def judge_hotels(offers: list[Offer], shared: dict[str, Any]) -> None:
    """The stars and the distance the operator asked for, judged on EVERY hotel row, whichever source it came from (28 Oct 2026: the Bensaude rows show neither, were never given those wishes, and one of them
    became 'Best fit, meets every wish'). A miss is `fits=False`; a number the row cannot show is `unconfirmed` (the row stays in the table, marked, never a pick)."""
    if not shared.get("stars_min") and shared.get("max_distance_km") is None:
        return
    for o in offers:
        if o.fits is False or o.price_total is None:
            continue
        d = o.details or {}
        miss = False
        unknown: list[str] = []
        if shared.get("stars_min"):
            try:
                stars = float(str(d.get("stars")).replace("★", "").strip())
            except (TypeError, ValueError):
                stars = None
            if stars is None:
                unknown.append("stars")
            elif stars < float(shared["stars_min"]):
                miss = True
        if shared.get("max_distance_km") is not None:
            km = distance_km(d.get("distance_from_centre"))
            if km is None:
                unknown.append("distance from the centre")
            elif km > float(shared["max_distance_km"]):
                miss = True
        if miss:
            o.fits = False
        else:
            for what in unknown:
                mark_unconfirmed(o, what)


_COMFORT_YES = {"comfort", "business", "first", "premium", "executive", "luxury", "vip"}      # 'Comfort', 'Electro Comfort', 'Business MPV', 'First class', 'Premium Minibus'
_COMFORT_NO = {"micro", "economy", "standard", "cheapest"}


def comfort_of(name: str) -> bool | None:
    """Is a transfer vehicle class a comfortable one? RateHawk names its rows 'Micro: Opel Corsa...', 'Comfort: VW Passat...', Kiwitaxi 'Comfort (Sedan comfort...)', 'Minivan 4PAX (...)': only the class before the first ':' or '(' counts.
    True for Comfort, Business, First class, Premium...; False for Micro and Economy; None for a class that says nothing about comfort (MPV, Minivan, Minibus, Bus)."""
    cls = re.sub(r"\b\d+\s*pax\b", "", re.split(r"[:(]", str(name or ""), maxsplit=1)[0].lower())
    words = set(re.findall(r"[a-z]+", cls))
    if words & _COMFORT_YES:
        return True
    if words & _COMFORT_NO:
        return False
    return None


def comfort_unconfirmed(offers: list[Offer]) -> str | None:
    """A comfortable vehicle was asked (28 Oct 2026: a Micro, an Opel Corsa, became 'Best fit, meets every wish' because the wish only chose RateHawk's tab). A Micro or Economy row is a clear miss; a class that says nothing
    about comfort is marked 'not confirmed' and is never a pick."""
    cut, unsure = 0, 0
    for o in offers:
        if not o.quotable or o.fits is False:
            continue
        verdict = comfort_of(o.name)
        if verdict is False:
            o.fits = False
            cut += 1
        elif verdict is None:
            mark_unconfirmed(o, "vehicle comfort")
            unsure += 1
    if not cut and not unsure:
        return None
    parts = []
    if cut:
        parts.append(f"{cut} Micro/Economy row(s) are not comfortable vehicles and are left out of the table")
    if unsure:
        parts.append(f"{unsure} row(s) of a class that says nothing about comfort (MPV, Minivan, Minibus, Bus...) are marked 'not confirmed' and are not picks")
    return "A comfortable vehicle was asked: " + "; ".join(parts) + "."
