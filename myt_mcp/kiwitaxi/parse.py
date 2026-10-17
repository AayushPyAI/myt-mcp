"""Kiwitaxi results page -> the private-transfer offers for one route, date and group.

The page (kiwitaxi.com/en/<country>/<route>) shows the searched route, date and passenger count in a header and one
`car-class-card` form per vehicle class: name, description, passenger and luggage capacity, the free-cancellation
rule in a tooltip and the price on the select button.
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import date
from typing import Any

_CURRENCY = {"€": "EUR", "$": "USD", "£": "GBP", "₪": "ILS"}
_CARD = re.compile(r"<form class=\"car-class-card[^\"]*\"[^>]*>.*?</form>", re.S)
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _first(pattern: str, block: str) -> str | None:
    m = re.search(pattern, block, re.S)
    return _text(m.group(1)) if m else None


def date_label(day: date) -> str:
    """How the page writes the date: '1 MAR 2027'."""
    return f"{day.day} {_MONTHS[day.month - 1]} {day.year}"


_GENERIC = {"airport", "hotel", "hostel", "apartment", "apartments", "resort", "the", "de", "di", "da", "la", "le", "of", "and", "hotels",
            "city", "centre", "center", "station", "port", "international", "aeroporto", "aeropuerto"}


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()).split())


def place_matches(query: str, place: dict[str, Any]) -> bool:
    """True when the place Kiwitaxi suggested is plausibly the one typed. Its first suggestion can be another town
    ("Florence Airport" -> Budapest Airport, "Furnas" -> Burgas): every distinctive word of the query (airport, hotel and
    similar words are ignored) must appear in the place's name or address, or at least its first four letters (Rome/Roma),
    and a three-letter airport code must appear in brackets in the name."""
    words = _plain(query).split()
    haystack = _plain(f"{place.get('title') or ''} {place.get('address') or ''}")
    if len(words) == 1 and len(words[0]) == 3:
        return f"({words[0]})" in (place.get("title") or "").lower() or words[0] in haystack.split()
    distinctive = [w for w in words if w not in _GENERIC and len(w) > 1]
    return all(w in haystack or (len(w) >= 4 and w[:4] in haystack) for w in distinctive) if distinctive else True


def _price(text: str | None) -> tuple[float | None, str | None]:
    m = re.match(r"^\s*([€$£₪])\s?([\d.,\s]+)$", text or "")
    if not m:
        return None, None
    try:
        return round(float(m.group(2).replace(",", "").replace(" ", "")), 2), _CURRENCY[m.group(1)]
    except ValueError:
        return None, None


def parse_results(page: str) -> dict[str, Any]:
    """{route, offers}: route = what the page says was searched; offers = one per vehicle class."""
    route = {
        "from": _first(r'search-data-route-departure.*?search-data-route-place-title">(.*?)</p>', page),
        "to": _first(r'search-data-route-destination.*?search-data-route-place-title">(.*?)</p>', page),
        "to_address": _first(r'search-data-route-destination.*?search-data-route-place-address">(.*?)</p>', page),
        "date": _first(r'search-data-date">(.*?)</p>', page),
        "passengers": _first(r'search-data-pax-value">(.*?)</p>', page),
        "driving_time": _first(r'search-data-time-in-way">(.*?)<i ', page),
    }
    offers = []
    for card in _CARD.findall(page):
        amount, currency = _price(_first(r'class="car-class-select-button[^"]*"[^>]*>(.*?)</button>', card))
        pax = _first(r'class="car-class-pax">(.*?)</p>', card)
        bags = _first(r'class="car-class-luggage">(.*?)</p>', card)
        hint = re.search(r'car-class-option-hint"[^>]*data-tippy="([^"]*)"', card)
        hours = re.search(r"no later than\s*(?:<strong>)?\s*(\d+)\s*h", html.unescape(hint.group(1))) if hint else None
        name = _first(r'class="car-class-name">(.*?)</p>', card)
        if not name:
            continue
        offers.append({
            "vehicle": name,
            "description": _first(r'class="car-class-description">(.*?)</p>', card),
            "max_passengers": int(pax) if pax and pax.isdigit() else None,
            "max_standard_bags": int(bags) if bags and bags.isdigit() else None,
            "price": amount, "currency": currency,
            "free_cancellation_hours_before": int(hours.group(1)) if hours else None,
        })
    return {"route": route, "offers": offers}


def check_results(parsed: dict[str, Any], day: date, passengers: int) -> list[str]:
    """The page must show the asked date and group, EUR prices, and at least one priced vehicle."""
    problems = []
    route, offers = parsed["route"], parsed["offers"]
    if route["date"] != date_label(day):
        problems.append(f"the page shows the date {route['date']!r}, not {date_label(day)!r}")
    if route["passengers"] != str(passengers):
        problems.append(f"the page shows {route['passengers']!r} passengers, not {passengers}")
    priced = [o for o in offers if o["price"] is not None]
    if not priced:
        problems.append("no vehicle with a price was found on the page")
    if any(o["currency"] != "EUR" for o in priced):
        problems.append(f"prices are in {', '.join(sorted({o['currency'] or '?' for o in priced}))}, not EUR")
    return problems
